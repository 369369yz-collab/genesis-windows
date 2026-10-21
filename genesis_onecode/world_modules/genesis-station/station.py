"""genesis-station: 369 PRODUCTION STATION.

A local, persistent (SQLite) job queue for production work on the Windows PC.

Job kinds:
  - "render":  execute a caller-supplied ffmpeg command line (bounded, no shell).
  - "produce": execute the documented production pipeline (declarative steps:
               mkdir / write_file / copy_file / ffmpeg / zip) inside a job
               work directory.

Public API (all return plain dicts with a "status" key, except submit_job
which returns the job id string per contract):
  submit_job(job: dict) -> str
  job_status(job_id: str) -> dict
  cancel_job(job_id: str) -> dict
  probe_hardware() -> dict

Processing model: jobs persist in SQLite. The in-process worker
(process_next_job / start_worker) picks the highest-priority pending job and
runs it synchronously. Cancellation of a RUNNING job works only when the
worker runs in the same process (the supported deployment model).

100% stdlib. No network calls anywhere in this module. ffmpeg inputs and outputs are confined to the job workdir by two layers:

1. Submit-time content validation (_validate_ffmpeg_args, applied to render
   jobs and produce ffmpeg steps at submit AND re-checked at run time):
   absolute paths (any platform), ".." segments, and local-access / network
   URL schemes (file:, pipe:, http:, ipfs:, ...) are rejected even when
   EMBEDDED in option/filter values ("movie=/abs/x.mp4",
   "subtitles=http://host/x.srt", "-i file:/abs/x.mp4", backslash-escaped
   variants — ffmpeg unescapes filter values TWICE, so validation unescapes
   twice too); the concat demuxer additionally requires exactly one
   "-safe 1" (ffmpeg honors the LAST -safe); callers may not override
   -protocol_whitelist; device/capture formats (gdigrab, dshow, v4l2,
   alsa, ...) are rejected outright.
2. ffmpeg-level backstop: every ffmpeg invocation runs with
   "-protocol_whitelist file,pipe,lavfi", so ffmpeg itself refuses any
   non-whitelisted protocol before any connection or file open.

INDIRECTION (round-3): validation never trusts an arg string alone. Files
ffmpeg reads beyond the argv strings have their CONTENTS validated and
confined: -filter_script / -filter_complex_script files (same content rules
as inline filter text), HLS/DASH playlists and manifests (every segment URI
and URI attribute confined to the workdir), and concat list files (only
documented directives; every "file" reference confined). The tee muxer's
"|"-separated branch outputs are each confined like normal outputs.
Missing indirect files are skipped at submit and validated at run time.

PARSER SELECTION (round-5, re-review G1; hardened round-6, re-review
V1/V2): the validator picks its playlist/manifest parser the way ffmpeg
picks its demuxer — the explicit format flag wins. An input-position "-f"
(tracked per "-i" with ffmpeg's positional option semantics) or the
movie/amovie filter's format option forces the grammar (dash/hls)
regardless of extension or content; without a forced format, an MPD
content sniff (<MPD root element, BOM/whitespace/XML-prolog tolerant)
beats the "#EXTM3U"-at-byte-0 sniff, which beats the extension. The
movie/amovie option string is parsed as real AVOptions (key=value with
"filename="/"f="/"format_name=", bare positionals, single-quote
protection, whitespace tolerance — verified variant-by-variant against
ffmpeg 8.1.2), and DASH attributes/elements are parsed with ffmpeg's
actual grammar (quote styles, spacing, XML entities, namespaced/cased
BaseURL/Location). The chosen parser is exhaustive for its format. This
runs at submit AND at run time (_execute_render / the produce ffmpeg
step), so write_file-planted manifests are caught too.

copy_file src is likewise confined to the workdir. Job claiming is atomic
(UPDATE ... WHERE state='pending', rowcount arbitrates), so concurrent
workers can never execute the same job twice.

Residual risks (NOT covered; documented honestly): symlink indirection
inside the workdir, pre-existing workdir contents, and the workdir path
itself (caller-chosen) are outside the enforced boundary — the boundary
covers the arg strings, the process cwd, and the protocol whitelist.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import threading
import uuid
import zipfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RENDER_KIND = "render"
PRODUCE_KIND = "produce"
_JOB_KINDS = (RENDER_KIND, PRODUCE_KIND)

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    params      TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    state       TEXT NOT NULL DEFAULT 'pending',
    progress    REAL NOT NULL DEFAULT 0.0,
    error       TEXT,
    result      TEXT,
    created_utc TEXT NOT NULL,
    started_utc TEXT,
    finished_utc TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs (state, priority, created_utc);
"""

_PRODUCE_OPS = ("mkdir", "write_file", "copy_file", "ffmpeg", "zip")

_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Paths / database
# ---------------------------------------------------------------------------

def _default_db_path() -> str:
    """Resolve the default SQLite path (Windows LOCALAPPDATA, else ~/.genesis)."""
    override = os.environ.get("GENESIS_STATION_DB")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "GENESIS", "station", "jobs.db")
    return os.path.join(os.path.expanduser("~"), ".genesis", "station", "jobs.db")


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _default_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

_URL_SCHEME_RE = None  # compiled lazily to keep import time trivial

# Splits an ffmpeg arg on every character that can separate a path segment
# (path separators plus the ffmpeg option/filter separators that can carry
# an embedded path, e.g. "subtitles=../evil.srt"). Used to spot ".." escapes.
_DOTDOT_SEG_RE = re.compile(r"[\\/=:;,]")

# ffmpeg protocols that read local files/devices or perform network I/O.
# Any "<scheme>:" prefix built from one of these names — anywhere inside an
# ffmpeg arg, including embedded in option/filter values such as
# "subtitles=http://host/x.srt", "movie=file:/abs/x.mp4" or "-i pipe:0"
# (matched case-insensitively) — is rejected at submit. This is the
# submit-time gate; the hard backstop is _FFMPEG_PROTOCOL_WHITELIST, passed
# to every ffmpeg invocation so ffmpeg itself refuses non-whitelisted
# protocols even if validation ever missed one.
_LOCAL_FILE_PROTOCOLS = frozenset({
    "file", "subfile", "concat", "concatf", "pipe", "data", "fd", "unix",
    "bluray", "dvd", "md5",
})
_NETWORK_PROTOCOLS = frozenset({
    "http", "https", "httpproxy", "ffrtmphttp",
    "ftp", "ftps", "sftp",
    "rtmp", "rtmpe", "rtmps", "rtmpt", "rtmpte", "rtmpts",
    "rtsp", "rtsps", "rtp", "srt", "srtp",
    "tcp", "tls", "dtls", "udp", "udplite", "sctp",
    "smb", "gopher", "gophers",
    "hls", "icecast", "mmsh", "mmst", "prompeg",
    "amqp", "rist", "zmq",
    "async", "cache", "tee", "crypto",
    # P2P protocols (round-3 hardening G-1: missing vs ffmpeg 8.1.2's
    # live "-protocols" list; embedded "subtitles=ipfs://..." passed
    # submit-time validation before this).
    "ipfs", "ipns",
})
_REJECTED_SCHEMES = _LOCAL_FILE_PROTOCOLS | _NETWORK_PROTOCOLS

# Every ffmpeg invocation is locked to this protocol whitelist. ffmpeg
# resolves even scheme-less local paths through the "file" protocol, and
# generated inputs ("-f lavfi -i testsrc=...") work under it (verified live);
# everything else (http, tcp, rtmp, data:, concat:, ...) is refused by
# ffmpeg itself before any connection or file open happens. Callers may not
# override it: "-protocol_whitelist" in ffmpeg_args is rejected at submit.
_FFMPEG_PROTOCOL_WHITELIST = "file,pipe,lavfi"

_SCHEME_PREFIX_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")

# Token separators for content-checking ffmpeg args: whitespace plus the
# ffmpeg option/filter separators that can carry embedded paths/URLs
# ("subtitles=http://...", "movie=/abs/x.mp4", "text='a;b'"). ":" and "/"
# are deliberately KEPT inside tokens so scheme prefixes and absolute
# paths stay detectable as units.
_ARG_TOKEN_RE = re.compile(r"[\s=,;'\"()\[\]{}]")
_UNESCAPE_RE = re.compile(r"\\\\|\\(.)", re.DOTALL)


def _unescape_once(text: str) -> str:
    """Undo one level of ffmpeg backslash-escaping ("\\:" -> ":", "\\\\" -> "\\")."""
    return _UNESCAPE_RE.sub(
        lambda m: m.group(1) if m.group(1) is not None else "\\", text)


def _unescape_ffmpeg(text: str) -> str:
    """Undo TWO levels of ffmpeg backslash-escaping.

    Proven live (independent re-review, round 2): ffmpeg applies two
    unescape passes to filter values — filter-graph token extraction, then
    option key/value parsing. Oracle: "subtitles=SENT1\\:SENT2" (one real
    backslash) splits on the resulting ":"; "subtitles=SENT1\\\\:SENT2"
    (two real backslashes) opens literally "SENT1:SENT2". Consequence: the
    validator must unescape twice to see what ffmpeg sees. A single pass
    misses the 2-backslash drive path "movie=C\\\\:/evil/x.mp4" (raw has no
    "C:" match, once-unescaped "C\\:/evil/x.mp4" still has none; ffmpeg's
    second pass yields "C:/evil/x.mp4") and the double-escaped URL
    "http\\\\://host/x" (only the second pass yields "http://host/x").
    """
    return _unescape_once(_unescape_once(text))


def _arg_tokens(arg: str):
    """Yield content tokens of an ffmpeg arg (raw and unescaped forms)."""
    for variant in {arg, _unescape_ffmpeg(arg)}:
        for tok in _ARG_TOKEN_RE.split(variant):
            if tok:
                yield tok


# Device/capture formats: reading from these pulls data from OUTSIDE the
# workdir (screen via gdigrab/x11grab, camera/mic via dshow/v4l2/avfoundation,
# audio devices via alsa/oss/pulse/jack/openal, raw devices via fbdev/kmsgrab/
# decklink/libdc1394/iec61883/libcdio) into job output — an exfiltration
# primitive no path check can confine. A production renderer has no
# legitimate use for them, so the format name may never appear (either as
# input or output). (Round-3 adversarial sweep finding; gdigrab/dshow are
# absent from this Linux ffmpeg build but present on the Windows target, so
# they are blocked pre-emptively.)
_BLOCKED_INPUT_FORMATS = frozenset({
    "gdigrab", "dshow", "v4l2", "video4linux2", "alsa", "oss", "sndio",
    "x11grab", "avfoundation", "decklink", "fbdev", "kmsgrab", "libcdio",
    "iec61883", "openal", "pulse", "jack", "libdc1394", "vfwcap", "qtkit",
})

# ffmpeg options whose VALUES name files ffmpeg reads/writes beyond the
# argv strings themselves (indirection vectors). "-filter_script[:s]" and
# "-filter_complex_script" name filter-script files; "-i" names inputs
# (playlists, concat lists); "-f"/"-fifo_format" select muxers with
# multi-output syntax (tee).
_SCRIPT_OPTION_NAMES = ("-filter_script", "-filter_complex_script")

# Playlist/manifest extensions whose file CONTENTS ffmpeg interprets as
# references to further files (HLS segments, DASH segments, EXT-X-KEY URIs).
_PLAYLIST_EXTS = (".m3u8", ".m3u", ".mpd")

# Playlist/manifest GRAMMARS keyed by the explicit ffmpeg "-f" format names
# that force them (re-review G1, round 5). The validator must pick its parser
# with the same rule ffmpeg uses to pick its demuxer: the input-position
# "-f" flag (or the movie/amovie filter's "f=" option) forces the grammar —
# extension and content only matter when no format is forced.
_PLAYLIST_GRAMMARS = frozenset({"hls", "dash"})

# Content-sniff window for playlist/manifest detection (MPD needs more than
# the 16 bytes the old #EXTM3U sniff used: XML prolog + whitespace + BOM).
_MPD_SNIFF_LEN = 512
_UTF8_BOM = b"\xef\xbb\xbf"

# Cap on indirect-file reads during validation (scripts, playlists, concat
# lists): validation must stay cheap; anything larger is rejected.
_MAX_INDIRECT_FILE_BYTES = 1_000_000


def _option_values(args: list, names: tuple) -> list:
    """Values of the named CLI options, robust to spacing variants.

    Handles "-opt value" (two argv elements) and "-opt value" / "-opt
    value with spaces" (one argv element). A value containing spaces as a
    SINGLE argv element (e.g. a script path "my script.txt") is returned
    whole — naive whitespace tokenizing would truncate it and miss the
    real file (indirection gap). Matching is case-insensitive; stream
    specifiers ("-filter_script:v") are accepted.
    """
    values = []
    i = 0
    n = len(args)
    while i < n:
        parts = args[i].split()
        head = parts[0] if parts else ""
        matched = False
        for name in names:
            hl = head.lower()
            if hl == name or hl.startswith(name + ":"):
                matched = True
                break
        if matched:
            if len(parts) > 1:
                values.append(" ".join(parts[1:]))
            elif i + 1 < n:
                values.append(args[i + 1])
                i += 1
        i += 1
    return values


def _concat_demuxer_used(args: list) -> bool:
    """True when "-f concat" appears in INPUT position (before some "-i").

    "-f concat" as an OUTPUT muxer only writes a list file (confined like
    any output); only the demuxer reads attacker-influenced list files, so
    only input-position usage triggers the "-safe 1" rule.
    """
    toks = [t for a in args for t in a.split()]
    for i, tok in enumerate(toks):
        if tok.lower() == "-f" and i + 1 < len(toks) and toks[i + 1].lower() == "concat":
            if any(t.lower() == "-i" for t in toks[i + 2:]):
                return True
    return False


def _require_concat_safe(args: list) -> None:
    """The concat demuxer reads paths from a file list; require exactly one "-safe 1".

    ffmpeg honors the LAST "-safe" value, so "-safe 1 -safe 0" runs the
    demuxer with "-safe 0" and the list file may reference absolute paths
    outside the workdir (re-review F-A, demonstrated live end-to-end with
    frame-identical exfil). The only honest rule: exactly one "-safe"
    occurrence, and its value must be "1". Duplicates or any other value
    are rejected. Matching is case-insensitive ("-f CONCAT" is caught too).
    """
    if not _concat_demuxer_used(args):
        return
    toks = [t for a in args for t in _ARG_TOKEN_RE.split(a) if t]
    values = [toks[i + 1] for i, tok in enumerate(toks)
              if tok.lower() == "-safe" and i + 1 < len(toks)]
    if len(values) != 1 or values[0] != "1":
        raise ValueError(
            "ffmpeg_args using the concat demuxer (-f concat) must pass "
            "exactly one '-safe 1': ffmpeg honors the LAST -safe value, so "
            "duplicates ('-safe 1 -safe 0') or any other value would let "
            "the list file reference paths outside the workdir")


def _is_url(text: str) -> bool:
    """True for scheme:// URLs (http, https, rtmp, ...)."""
    import re
    global _URL_SCHEME_RE
    if _URL_SCHEME_RE is None:
        _URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
    return bool(_URL_SCHEME_RE.match(text))


def _is_abs_anywhere(path: str) -> bool:
    """Absolute path on any platform (POSIX, Windows drive, UNC).

    Also treats Windows drive-RELATIVE references ("C:evil.mp4", re-review
    H-1) as rooted: the Windows path resolver anchors them on that drive's
    per-drive cwd, so the validator must see them as absolute-drive
    references, not as plain relative paths.
    """
    import re
    if os.path.isabs(path):
        return True
    if re.match(r"^[a-zA-Z]:", path):  # C:\..., C:/..., C:evil.mp4
        return True
    if path.startswith("\\\\"):  # UNC \\server\share
        return True
    return False


def _reject_capture_formats(args: list) -> None:
    """Reject device/capture "-f" formats (screen/camera/mic/device reads)."""
    for val in _option_values(args, ("-f",)):
        if val.lower() in _BLOCKED_INPUT_FORMATS:
            raise ValueError(
                "ffmpeg_args must not use device/capture format %r: it "
                "reads data from outside the workdir (screen, camera, "
                "microphone, hardware devices)" % val)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _read_indirect_file(abs_path: str, kind: str) -> str:
    """Read a validator-inspected indirect file (script/playlist/list)."""
    if os.path.getsize(abs_path) > _MAX_INDIRECT_FILE_BYTES:
        raise ValueError(f"{kind} file too large to validate: {abs_path!r}")
    try:
        with open(abs_path, "r", encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except UnicodeDecodeError:
        # A binary file forced under a playlist grammar (e.g. "-f dash -i
        # video.mp4") is rejected cleanly: ffmpeg itself cannot parse it
        # as a manifest either ("Invalid data found" — verified live).
        raise ValueError(f"{kind} file is not decodable text: {abs_path!r}")


def _sniff_playlist_grammar(head: bytes) -> str | None:
    """Content-sniff which playlist/manifest grammar a file uses (G1).

    HLS: ffmpeg's HLS probe requires "#EXTM3U" at byte 0 (a UTF-8 BOM
    breaks it — verified live), so this sniff keeps byte-0 parity and is
    never looser than ffmpeg.
    MPD: the DASH demuxer keys on the <MPD root element. Sniff it with
    leading BOM/whitespace tolerance plus an XML prolog (<?xml ...?>,
    comments, processing instructions) skip — over-recognition here is
    safe: no real media file starts with <MPD, and a stricter validator
    can only reject, never exfiltrate.
    """
    if head.startswith(b"#EXTM3U"):
        return "hls"
    h = head
    if h.startswith(_UTF8_BOM):
        h = h[len(_UTF8_BOM):]
    h = h.lstrip(b" \t\r\n")
    # Skip an XML prolog (declaration, comments, PIs) before the root.
    while True:
        if h.startswith(b"<?xml"):
            end = h.find(b"?>")
            if end == -1:
                return None
            h = h[end + 2:].lstrip(b" \t\r\n")
            continue
        if h.startswith(b"<!--"):
            end = h.find(b"-->")
            if end == -1:
                return None
            h = h[end + 3:].lstrip(b" \t\r\n")
            continue
        if h.startswith(b"<?"):
            end = h.find(b"?>")
            if end == -1:
                return None
            h = h[end + 2:].lstrip(b" \t\r\n")
            continue
        break
    if h.startswith(b"<MPD"):
        return "dash"
    return None


def _grammar_for_file(abs_path: str, forced: str | None = None) -> str | None:
    """Resolve the playlist/manifest grammar that applies to a file (G1).

    Priority — the explicit format flag ffmpeg honors beats everything:
    1. forced: the "-f" value (input position) or movie/amovie "f=" option
       that selects ffmpeg's demuxer for this file;
    2. content sniff (_sniff_playlist_grammar);
    3. extension fallback (.mpd -> dash, .m3u8/.m3u -> hls).
    Returns None when the file is not a playlist/manifest by any signal.
    """
    if forced and forced.lower() in _PLAYLIST_GRAMMARS:
        return forced.lower()
    with open(abs_path, "rb") as fh:
        head = fh.read(_MPD_SNIFF_LEN)
    sniffed = _sniff_playlist_grammar(head)
    if sniffed is not None:
        return sniffed
    low = abs_path.lower()
    if low.endswith(".mpd"):
        return "dash"
    if low.endswith((".m3u8", ".m3u")):
        return "hls"
    return None


def _forced_input_formats(args: list) -> dict:
    """Map each "-i" input value to the set of "-f" formats forced on it (G1).

    ffmpeg's input options are positional: an "-f" applies to the NEXT "-i"
    that follows it (consumed per input); an "-f" after the final "-i" is an
    OUTPUT option and forces nothing. The validator must choose its
    playlist/manifest parser with this same rule, because ffmpeg's actual
    parser is the forced demuxer — e.g. "-f dash -i x.dat" parses x.dat as
    DASH no matter what the extension or content says. An input repeated
    under two "-f" flags keeps every forced format (ffmpeg parses it once
    per occurrence, so the validator must check each grammar).
    """
    mapping: dict[str, set[str]] = {}
    pending: str | None = None
    i, n = 0, len(args)
    while i < n:
        parts = str(args[i]).split()
        head = parts[0].lower() if parts else ""
        if head == "-f":
            if len(parts) > 1:
                pending = _strip_quotes(" ".join(parts[1:]))
            elif i + 1 < n:
                pending = _strip_quotes(str(args[i + 1]))
                i += 1
        elif head == "-i":
            if len(parts) > 1:
                val = _strip_quotes(" ".join(parts[1:]))
            elif i + 1 < n:
                val = _strip_quotes(str(args[i + 1]))
                i += 1
            else:
                val = ""
            if val and val != "-":
                entry = mapping.setdefault(val, set())
                if pending:
                    entry.add(pending.lower())
            pending = None  # consumed: ffmpeg applies input options per input
        i += 1
    return mapping


# ffmpeg's movie/amovie filter parses its option string as AVOptions
# (re-review V1, round 6): colon-separated segments, each either a bare
# positional value (1st -> filename, 2nd -> format_name) or "key=value".
# Keys are CASE-SENSITIVE ("FILENAME=" is rejected by ffmpeg — verified
# live); the demuxer-forcing keys are "f" and "format_name" (LAST one in
# segment order wins; values are case-insensitive, "f=DASH" works —
# verified live); whitespace around the key, "=", and the value is
# tolerated ("format_name = dash : filename = x.dat" exfiltrates —
# verified live). Single quotes protect ":" and are stripped; DOUBLE
# quotes are LITERAL in this ffmpeg's filter parser (verified live:
# movie="x.dat" tries to open '"x.dat"'). Unknown keys make ffmpeg fail
# the job ("Option not found" — verified live).
_MOVIE_FORMAT_KEYS = frozenset({"f", "format_name"})


def _split_movie_segments(opt_string: str) -> list[str]:
    """Split a movie/amovie option string on ffmpeg's ":" separators.

    A ":" inside single quotes does not split (the quotes are stripped);
    double quotes are literal characters (NOT quoting — verified live
    against ffmpeg 8.1.2); a backslash quotes the next character for
    splitting purposes. The returned segments keep their backslashes;
    callers unescape per level (ffmpeg applies several unescape passes —
    filter-graph token extraction, then option key/value parsing).
    """
    segments: list[str] = []
    buf: list[str] = []
    quote = False
    escaped = False
    for ch in opt_string:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            buf.append(ch)
            continue
        if ch == "'":
            quote = not quote
            continue  # strip the quote char
        if ch == ":" and not quote:
            segments.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    segments.append("".join(buf))
    return segments


def _movie_segment_candidates(segment: str) -> list[str]:
    """Fail-closed filename candidates for one movie option segment.

    The "-f lavfi -i movie=..." input path and the -vf / filter-script
    path DISAGREE on whether quotes/backslash protect ":" (verified live:
    lavfi splits 'a:b.dat' and a\\:b.dat; the filter-arg level protects
    them), and ffmpeg applies up to two backslash-unescape passes. The
    validator cannot know which path an arg will take, so every
    ":"-separated piece AND the whole segment — at each unescape level —
    is a candidate: whichever filename ffmpeg actually opens is always in
    the set. Over-collection is safe: non-existent or confined-relative
    candidates are no-ops in _maybe_validate_playlist_ref.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        text = text.strip()
        if text and text not in seen:
            seen.add(text)
            candidates.append(text)

    level = segment
    for _ in range(3):  # raw, 1x, 2x unescaped: cover every ffmpeg level
        _add(level)
        for piece in level.split(":"):
            _add(piece)
        unescaped = _unescape_once(level)
        if unescaped == level:
            break
        level = unescaped
    return candidates


def _parse_movie_options(opt_string: str) -> tuple[list[str], str | None]:
    """Parse a movie/amovie filter option string (re-review V1).

    Returns (filename_candidates, forced_format). The format comes from
    "f="/"format_name=" (last wins) or the 2nd bare positional segment
    ("movie=x.dat:dash" forces DASH — verified live). Every bare segment,
    every "filename=" value, and every UNKNOWN "key=" value is a filename
    candidate (fail-closed: unknown keys fail the job in ffmpeg, but the
    validator still checks their values rather than skipping them).
    """
    candidates: list[str] = []
    fmt: str | None = None
    positional = 0
    for segment in _split_movie_segments(opt_string):
        seg = segment.strip()
        if not seg:
            continue  # ffmpeg ignores empty segments (verified live)
        if "=" in seg:
            key, _, value = seg.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "filename":
                candidates.extend(_movie_segment_candidates(value))
            elif key in _MOVIE_FORMAT_KEYS:
                fmt = value  # last one wins (verified live)
            else:
                # Unknown key: ffmpeg fails the job ("Option not found"),
                # but fail-closed means validating the value anyway —
                # never skipping what we cannot parse.
                candidates.extend(_movie_segment_candidates(value))
        else:
            positional += 1
            if positional == 2:
                fmt = seg  # 2nd bare positional = format_name (verified)
            candidates.extend(_movie_segment_candidates(seg))
    return candidates, (fmt.strip() if fmt else None)


def _split_media_format_option(token: str) -> tuple[str, str | None]:
    """Split a "name:f=fmt" filter token into (filename, forced format).

    Built on the real movie-option parser: handles "f=", "format_name=",
    and "filename=" forms, not just the ":f=" alias. (In practice the
    token path never sees "=" — _arg_tokens splits on it — so the
    "=" forms are covered by _movie_filter_refs; this stays correct for
    the documented "name:f=fmt" contract and any future caller.)
    """
    candidates, fmt = _parse_movie_options(token)
    return (candidates[0] if candidates else token), fmt


def _movie_filter_refs(arg: str) -> list[tuple[str, str | None]]:
    """Extract movie=/amovie= filter references from a raw arg (G1/V1).

    Parses the filter's AVOption string the way ffmpeg does — key=value
    pairs ("filename=", "f="/"format_name="), bare positionals, quoting,
    whitespace — and yields (filename, forced_format) for EVERY filename
    candidate (fail-closed set; see _movie_segment_candidates), so the
    real filename is never lost the way "movie=format_name=dash:
    filename=x.dat" lost it (re-review V1). The option string ends at the
    next filter separator (",", ";", "[", "]").
    """
    refs: list[tuple[str, str | None]] = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])(?:a?movie)\s*=\s*", arg):
        i = m.end()
        n = len(arg)
        buf: list[str] = []
        quote = False
        escaped = False
        while i < n:
            ch = arg[i]
            if escaped:
                buf.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
                buf.append(ch)
            elif ch == "'":
                quote = not quote
                buf.append(ch)
            elif not quote and ch in ",;[]":
                break
            else:
                buf.append(ch)
            i += 1
        opt_string = "".join(buf)
        candidates, fmt = _parse_movie_options(opt_string)
        for candidate in candidates:
            refs.append((candidate, fmt))
    return refs


def _validate_segment_uri(uri: str, playlist_dir: str, workdir_base: str,
                          seen: set, kind: str) -> None:
    """Validate one playlist/concat-list referenced path.

    Segments must be plain workdir-relative paths: absolute paths (any
    platform), ".." segments, and ANY scheme prefix are rejected, and the
    resolved real path must stay inside the workdir. Nested playlists are
    validated recursively (with a visited set against reference loops).
    """
    u = _strip_quotes(uri)
    if not u or u == "-":
        return
    if _is_abs_anywhere(u):
        raise ValueError(f"{kind} must not reference absolute paths: {u!r}")
    if any(seg == ".." for seg in _DOTDOT_SEG_RE.split(_unescape_ffmpeg(u))):
        raise ValueError(f"{kind} must not contain '..' segments: {u!r}")
    if _is_url(u):
        raise ValueError(f"{kind} must not reference URLs: {u!r}")
    scheme = _SCHEME_PREFIX_RE.match(u)
    if scheme:
        raise ValueError(
            f"{kind} must not reference scheme {scheme.group(1)!r}: {u!r} "
            "(referenced files must be plain workdir-relative paths)")
    target = os.path.realpath(os.path.join(playlist_dir, u))
    if os.path.commonpath([workdir_base, target]) != workdir_base:
        raise ValueError(f"{kind} reference escapes the workdir: {u!r}")
    # F-G + G1: ffmpeg follows nested playlists by CONTENT, not by file
    # extension — the HLS demuxer probes variant/rendition playlists with
    # the "#EXTM3U"-at-byte-0 probe, and a forced DASH demuxer keys on the
    # <MPD root element. Recursion must therefore follow the same signals
    # (_grammar_for_file: content sniff, then extension), never the
    # extension alone. The "seen" set is keyed (path, grammar) so the same
    # file is still parsed at most once per grammar (loop-safe).
    if os.path.isfile(target):
        nested_grammar = _grammar_for_file(target)
        if nested_grammar is not None:
            _validate_playlist_file(target, workdir_base, seen,
                                    nested_grammar)


# HLS tag attribute values: ffmpeg's HLS parser handles backslash escapes
# inside the double-quoted value (verified live: URI="/nope\"/x" opens
# '/nope"/x'), so the regex must too — otherwise the validator and ffmpeg
# disagree on where the value ends. Single-quoted, spaced ("URI = "),
# and lowercase ("uri=") forms are NOT honored by ffmpeg (verified live),
# so the regex stays strict on those: parity, not leniency.
_URI_ATTR_RE = re.compile(r'URI="((?:[^"\\]|\\.)*)"')

# DASH SegmentTemplate/SegmentURL media|initialization attributes
# (re-review V2, round 6): ffmpeg's DASH demuxer (libxml2) honors single
# quotes and whitespace around "=" (verified live) — the old
# double-quote-only, space-intolerant regex missed them. Attribute NAMES
# stay lowercase-only: uppercase MEDIA= is NOT honored (verified live).
_MPD_URL_ATTRS_RE = re.compile(
    r"(?:media|initialization)\s*=\s*('[^']*'|\"[^\"]*\")")

# DASH <BaseURL>/<Location> elements (round-6 audit): ffmpeg honors
# attributes on the element (<BaseURL serviceLocation="x">), whitespace
# before ">", namespace prefixes (<mpd:BaseURL>), and any case
# (<BASEURL>) — all verified live. The old "<BaseURL>([^<]*)</BaseURL>"
# missed every one of those.
_MPD_BASEURL_RE = re.compile(
    r"<(?:[A-Za-z_][\w.\-]*:)?baseurl\b[^>]*>([^<]*)"
    r"</(?:[A-Za-z_][\w.\-]*:)?baseurl\s*>",
    re.IGNORECASE)
_MPD_LOCATION_RE = re.compile(
    r"<(?:[A-Za-z_][\w.\-]*:)?location\b[^>]*>([^<]*)"
    r"</(?:[A-Za-z_][\w.\-]*:)?location\s*>",
    re.IGNORECASE)

# XML character/entity references (round-6 audit): libxml2 resolves these
# in attribute values AND element text before ffmpeg sees the URL, so
# media='&#47;tmp&#47;x.mp4' opens /tmp/x.mp4 (verified live exfil) while
# a naive regex sees no leading "/". Single-pass resolution matches
# libxml2 ("&amp;#47;" stays literal "&#47;", not "/").
_XML_PREDEFINED_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
}
_XML_CHARREF_RE = re.compile(
    r"&#([0-9]+);|&#x([0-9a-fA-F]+);|&(amp|lt|gt|quot|apos);")


def _xml_unescape(text: str) -> str:
    """Resolve one pass of XML character/entity references (libxml2 parity)."""

    def _replace(m: re.Match) -> str:
        if m.group(3):
            return _XML_PREDEFINED_ENTITIES[m.group(3)]
        code = int(m.group(1)) if m.group(1) else int(m.group(2), 16)
        try:
            return chr(code)
        except (ValueError, OverflowError):
            return m.group(0)

    return _XML_CHARREF_RE.sub(_replace, text)


def _hls_unescape(text: str) -> str:
    """Undo one level of HLS attribute backslash-escaping (ffmpeg parity)."""
    return re.sub(r"\\(.)", r"\1", text, flags=re.DOTALL)


def _validate_playlist_file(abs_path: str, workdir_base: str, seen: set,
                            grammar: str | None = None) -> None:
    """Content-validate an HLS playlist or DASH manifest.

    Re-review F-D: the HLS demuxer opens segment URIs through the
    whitelisted "file" protocol, so a playlist listing an absolute-path
    "segment" exfiltrates arbitrary local files into job output. Every
    segment URI (and EXT-X-KEY / EXT-X-MAP / EXT-X-MEDIA URI attributes,
    DASH SegmentTemplate media/initialization and BaseURL) is confined to
    the workdir; absolute paths, "..", and any scheme are rejected.

    Re-review G1: the grammar is chosen by _grammar_for_file — the
    explicit format flag ffmpeg honors beats extension/content — and the
    chosen parser is EXHAUSTIVE: it handles every reference type of its
    format (HLS: bare segment lines plus every URI="..." attribute tag;
    DASH: media=/initialization= attributes, BaseURL elements, and nested
    manifest references). A format's references are never silently
    skipped because the wrong branch was taken.
    Re-review V1/V2 (round 6): the validator's parser must be no narrower
    than ffmpeg's for EVERY hand-parsed syntax — movie/amovie AVOptions
    (key=value, quoting, whitespace), DASH attributes (quote styles,
    spacing, entities), BaseURL/Location elements (attributes, namespaces,
    case), HLS URI attributes (backslash escapes). Each variant verified
    against direct-ffmpeg recon; see BUILDER_NOTES.md parity table.
    """
    if grammar is None:
        grammar = _grammar_for_file(abs_path) or "hls"
    key = (abs_path, grammar)
    if key in seen:
        return
    seen.add(key)
    text = _read_indirect_file(abs_path, "playlist")
    pldir = os.path.dirname(abs_path)
    if grammar == "dash":
        for uri in _MPD_URL_ATTRS_RE.findall(text):
            # libxml2 resolves entities before ffmpeg sees the URL
            # (media='&#47;tmp&#47;x' opens /tmp/x — verified live).
            _validate_segment_uri(_xml_unescape(uri), pldir, workdir_base,
                                  seen, "DASH manifest")
        for uri in _MPD_BASEURL_RE.findall(text):
            # Padded values are NOT honored by ffmpeg (verified live), but
            # stripping can only make validation stricter — fail-closed.
            _validate_segment_uri(_xml_unescape(uri.strip()), pldir,
                                  workdir_base, seen, "DASH manifest")
        for uri in _MPD_LOCATION_RE.findall(text):
            # <Location> is a manifest redirect: the DASH demuxer follows
            # it (even file:///outside.mpd — verified live exfil), so the
            # target is confined AND content-validated as a nested DASH
            # manifest via _validate_segment_uri's recursion.
            _validate_segment_uri(_xml_unescape(uri.strip()), pldir,
                                  workdir_base, seen, "DASH Location")
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            for uri in _URI_ATTR_RE.findall(line):
                _validate_segment_uri(_hls_unescape(uri), pldir, workdir_base,
                                      seen, "playlist")
            continue
        _validate_segment_uri(line, pldir, workdir_base, seen, "playlist")


_CONCAT_FILE_LINE_RE = re.compile(
    r"""^file\s+(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|(\S+))\s*$""")


def _validate_concat_list(abs_path: str, workdir_base: str, seen: set) -> None:
    """Content-validate a concat-demuxer list file (defense in depth).

    Beyond the mandatory exactly-one "-safe 1" (which makes ffmpeg itself
    reject unsafe entries), the list file is content-checked here too: only
    the documented ffconcat directives are accepted and every "file"
    reference is confined to the workdir like a playlist segment.
    """
    if abs_path in seen:
        return
    seen.add(abs_path)
    text = _read_indirect_file(abs_path, "concat list")
    pldir = os.path.dirname(abs_path)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if (line.startswith("ffconcat version") or line.startswith("duration")
                or line.startswith("file_packet_metadata")
                or line.startswith("stream")):
            continue
        m = _CONCAT_FILE_LINE_RE.match(line)
        if not m:
            raise ValueError(f"concat list: unsupported directive: {line!r}")
        path = m.group(1) or m.group(2) or m.group(3)
        path = _unescape_once(path)  # ffconcat quoting uses backslash escapes
        _validate_segment_uri(path, pldir, workdir_base, seen, "concat list")


def _maybe_validate_script(value: str, workdir: str, seen: set) -> None:
    """Validate a -filter_script / -filter_complex_script file's contents.

    Re-review F-C: validation inspected arg STRINGS only, while ffmpeg's
    real input included the script FILE's contents (attacker-writable via
    write_file). The script file is confined to the workdir and its
    contents are validated with the SAME content rules as inline filter
    text. A script that does not exist yet is skipped at submit (a produce
    job may create it with write_file) and validated at run time, when
    _execute_render / _execute_produce_step re-run the full validator.
    """
    v = _strip_quotes(value)
    if not v:
        raise ValueError("filter script option requires a file path")
    try:
        abs_path = _confine(workdir, v)
    except ValueError:
        raise ValueError(f"filter script must stay inside the workdir: {v!r}")
    if not os.path.isfile(abs_path):
        return  # deferred to run-time validation
    content = _read_indirect_file(abs_path, "filter script")
    # Script content IS filter-graph text: same content rules as inline
    # -vf/-filter_complex text, plus playlist references inside it
    # (e.g. "movie=x.m3u8") are content-validated too — including the
    # movie/amovie "f=" forced-demuxer option (G1 door D).
    _validate_ffmpeg_args([content], workdir=None)
    for fname, fmt in _movie_filter_refs(content):
        if fname:
            _maybe_validate_playlist_ref(fname, workdir, seen, fmt)
    for tok in _arg_tokens(content):
        t = _strip_quotes(tok)
        fname, fmt = _split_media_format_option(t)
        if (fname.lower().endswith(_PLAYLIST_EXTS)
                or (fmt or "").lower() in _PLAYLIST_GRAMMARS):
            _maybe_validate_playlist_ref(fname, workdir, seen, fmt)


def _maybe_validate_playlist_ref(value: str, workdir: str, seen: set,
                                 forced: str | None = None) -> None:
    """Content-validate a referenced playlist/manifest file if it exists.

    The grammar comes from _grammar_for_file (forced format flag beats
    content sniff beats extension), so a lying extension or a forced
    demuxer can no longer select the wrong parser (re-review G1).
    """
    v = _strip_quotes(value)
    if not v:
        return
    try:
        abs_path = _confine(workdir, v)
    except ValueError:
        raise ValueError(f"playlist reference escapes the workdir: {v!r}")
    if not os.path.isfile(abs_path):
        return  # deferred to run-time validation
    abs_path = os.path.realpath(abs_path)
    grammar = _grammar_for_file(abs_path, forced)
    if grammar is None:
        return  # not a playlist/manifest by any signal
    _validate_playlist_file(abs_path,
                            os.path.realpath(os.path.abspath(workdir)),
                            seen, grammar)


def _maybe_validate_key_info_file(value: str, workdir: str, seen: set) -> None:
    """Content-validate an -hls_key_info_file's lines (re-review H-2).

    The key-info file's lines (key URI, key file path, optional IV) are
    read by ffmpeg when writing encrypted HLS. Reject absolute paths and
    URLs in them at submit for consistency with the rest of the
    indirection class: every line must be a plain workdir-relative path
    (the IV line is hex and passes trivially). A file that does not exist
    yet is skipped at submit and validated at run time.
    """
    v = _strip_quotes(value)
    if not v:
        return
    try:
        abs_path = _confine(workdir, v)
    except ValueError:
        raise ValueError(f"key info file escapes the workdir: {v!r}")
    if not os.path.isfile(abs_path):
        return  # deferred to run-time validation
    text = _read_indirect_file(abs_path, "key info file")
    base = os.path.realpath(os.path.abspath(workdir))
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        _validate_segment_uri(line, os.path.dirname(abs_path), base, seen,
                              "key info file")


def _maybe_validate_input_file(value: str, workdir: str, seen: set,
                               concat_mode: bool,
                               forced_map: dict | None = None) -> None:
    """Validate an "-i" input file's interpretable contents.

    Media files need no content validation (ffmpeg demuxes them as data),
    but files whose CONTENTS ffmpeg interprets as further file references
    do: playlists/manifests, concat lists — including when the extension
    lies (content sniffing: a ".mp4" starting with "#EXTM3U" or "ffconcat"
    is still opened by the sniffed demuxer).

    Re-review G1: the parser is picked the way ffmpeg picks its demuxer —
    the input-position "-f" flag (forced_map) beats the MPD/#EXTM3U
    content sniff, which beats the extension. Without this, "-f dash -i
    x.dat" parses MPD XML through the HLS branch and the absolute
    media="..." paths sail through unexamined.
    """
    v = _strip_quotes(value)
    if not v or v == "-":
        return
    try:
        abs_path = _confine(workdir, v)
    except ValueError:
        raise ValueError(f"input file escapes the workdir: {v!r}")
    if not os.path.isfile(abs_path):
        return  # deferred to run-time validation
    abs_path = os.path.realpath(abs_path)
    base = os.path.realpath(os.path.abspath(workdir))
    forced = (forced_map or {}).get(v, set())
    playlist_forced = sorted(g for g in forced if g in _PLAYLIST_GRAMMARS)
    if playlist_forced:
        # ffmpeg parses a repeated input once per occurrence, so the
        # validator checks every forced playlist grammar (same (path,
        # grammar) loop guard as everywhere else).
        for grammar in playlist_forced:
            _validate_playlist_file(abs_path, base, seen, grammar)
        return
    with open(abs_path, "rb") as fh:
        head = fh.read(_MPD_SNIFF_LEN)
    grammar = _sniff_playlist_grammar(head)
    if grammar is None:
        low = v.lower()
        if low.endswith(".mpd"):
            grammar = "dash"
        elif low.endswith((".m3u8", ".m3u")):
            grammar = "hls"
    if grammar is not None:
        _validate_playlist_file(abs_path, base, seen, grammar)
    elif head.startswith(b"ffconcat") or concat_mode:
        _validate_concat_list(abs_path, base, seen)


def _validate_tee_branches(args: list, workdir: str) -> None:
    """Validate every tee-muxer branch output (re-review F-E).

    ffmpeg's tee muxer splits its output spec on "|" and opens EACH branch
    as a separate file: "-f tee 't.mp4|/tmp/atk/TEED.mp4'" writes outside
    the workdir while per-token checks see only a token that neither
    starts with "/" nor contains a scheme. When tee is selected ("-f tee"
    or "-fifo_format tee"), every "|" separated branch (unescaped "\\|"
    respected, leading "[...]" tee option blocks stripped) is validated
    with the same output-confinement rule as normal outputs. The "tee:"
    output PROTOCOL form needs no handling: "tee:" is a rejected scheme.
    """
    fmt_vals = [v.lower() for v in _option_values(args, ("-f", "-fifo_format"))]
    if "tee" not in fmt_vals:
        return
    for a in args:
        if "|" not in a:
            continue
        for branch in re.split(r"(?<!\\)\|", a):
            br = branch.strip()
            br = re.sub(r"^\[[^\]]*\]", "", br).strip()  # [f=mp4] blocks
            br = br.replace("\\|", "|").replace("\\\\", "\\")
            if not br:
                raise ValueError(
                    "tee muxer output has an empty branch: %r" % a)
            if br == "-":
                continue  # stdout (DEVNULL in _run_ffmpeg): harmless
            if _is_abs_anywhere(br):
                raise ValueError(
                    "tee muxer branch must not be an absolute path "
                    "(workdir-relative only): %r" % br)
            if any(seg == ".." for seg in _DOTDOT_SEG_RE.split(_unescape_ffmpeg(br))):
                raise ValueError(
                    "tee muxer branch must not contain '..' segments: %r" % br)
            if _is_url(br):
                raise ValueError(
                    "tee muxer branch must not be a URL: %r" % br)
            scheme = _SCHEME_PREFIX_RE.match(br)
            if scheme:
                raise ValueError(
                    "tee muxer branch must not use scheme %r: %r"
                    % (scheme.group(1), br))
            _confine(workdir, br)  # raises ValueError on escape


def _validate_referenced_files(args: list, workdir: str) -> None:
    """Close the INDIRECTION class: files ffmpeg reads beyond argv strings.

    Validates the contents of filter-script files, playlist/manifest files,
    and concat-list files referenced by the args (at submit when they
    exist; always again at run time, when produce write_file steps may have
    created them). See _maybe_validate_script / _maybe_validate_input_file /
    _maybe_validate_playlist_ref.
    """
    seen: set = set()
    concat_mode = _concat_demuxer_used(args)
    # G1: which "-f" format each "-i" input is forced to (positional ffmpeg
    # semantics) — the playlist/manifest parser must agree with ffmpeg's
    # forced demuxer, at submit AND at run time (both _execute_render and
    # the produce ffmpeg step re-run this validator).
    forced_map = _forced_input_formats(args)
    for v in _option_values(args, _SCRIPT_OPTION_NAMES):
        _maybe_validate_script(v, workdir, seen)
    for v in _option_values(args, ("-i",)):
        _maybe_validate_input_file(v, workdir, seen, concat_mode, forced_map)
    # Key-info files (-hls_key_info_file) are read by ffmpeg when writing
    # encrypted HLS: validate their contents like other indirect files.
    for v in _option_values(args, ("-hls_key_info_file",)):
        _maybe_validate_key_info_file(v, workdir, seen)
    # Playlist-looking references anywhere in filter/option values
    # (e.g. "movie=pl.m3u8" inside -vf text).
    for a in args:
        # G1 door D: the movie/amovie filter's "f=" option forces the
        # demuxer independently of the extension ("movie=x.dat:f=dash"
        # parses x.dat as DASH — verified live); quote-aware scan so
        # "movie='x.dat':f=dash" is not missed by token splitting.
        for fname, fmt in _movie_filter_refs(a):
            if fname:
                _maybe_validate_playlist_ref(fname, workdir, seen, fmt)
        for tok in _arg_tokens(a):
            t = _strip_quotes(tok)
            fname, fmt = _split_media_format_option(t)
            if (fname.lower().endswith(_PLAYLIST_EXTS)
                    or (fmt or "").lower() in _PLAYLIST_GRAMMARS):
                _maybe_validate_playlist_ref(fname, workdir, seen, fmt)


def _validate_ffmpeg_args(args: list, workdir: str | None = None) -> list:
    """Reject ffmpeg args that escape the job workdir or reach the network.

    Content-checking, not shape-trusting (re-review R1/R2/R3 root cause):
    each arg is examined on both its raw and TWICE-backslash-unescaped
    forms (ffmpeg unescapes filter values twice — proven live, see
    _unescape_ffmpeg), split into tokens on ffmpeg value separators, and every token is
    checked for absolute paths (any platform), ".." segments, and
    local-access / network URL schemes (file:, http:, pipe:, ipfs:, ...), so
    values EMBEDDED in option/filter strings ("movie=/abs/x.mp4",
    "subtitles=http://host/x.srt", "-i file:/abs/x.mp4") are caught too.
    The concat demuxer additionally requires exactly one "-safe 1"
    (ffmpeg honors the LAST -safe); the tee muxer's "|" separated branch
    outputs are each confined; device/capture formats are rejected; and
    callers may not override the module's -protocol_whitelist.

    When workdir is given, the INDIRECTION class is closed as well: files
    ffmpeg reads beyond the argv strings — filter-script files, HLS/DASH
    playlists and manifests, concat list files — have their CONTENTS
    validated and confined (_validate_referenced_files). Missing files are
    skipped here and validated at run time, when _execute_render /
    _execute_produce_step re-run this validator with the workdir.
    """
    for element in args:
        if _is_abs_anywhere(element):
            raise ValueError(
                "ffmpeg_args must not contain absolute paths "
                "(workdir-relative only): %r" % element)
        if _is_url(element):
            raise ValueError(
                "ffmpeg_args must not contain URLs (no network I/O): %r"
                % element)
        for variant in {element, _unescape_ffmpeg(element)}:
            if any(seg == ".." for seg in _DOTDOT_SEG_RE.split(variant)):
                raise ValueError(
                    "ffmpeg_args must not contain '..' path segments "
                    "(workdir-relative only): %r" % element)
            # Comma-terminated protocol syntax: the subfile protocol writes
            # its scheme as "subfile,,start,0,end,100,,:/abs/path" (comma,
            # not colon) — a byte-range read of an arbitrary file whose
            # absolute path hides after ",,:" (round-3 sweep finding; the
            # runtime whitelist backstop blocks it, this closes the
            # submit-time layer). Checked on the whole variant because the
            # token splitter consumes commas.
            for _scheme in _REJECTED_SCHEMES:
                if re.search(r"(?:^|[\s=;'\"])" + re.escape(_scheme) + r",",
                             variant, re.IGNORECASE):
                    raise ValueError(
                        "ffmpeg_args must not contain URL/protocol values "
                        "(no network I/O, no local-protocol reads), including "
                        "comma-terminated protocol syntax: %r" % element)
        for tok in _arg_tokens(element):
            if _is_abs_anywhere(tok):
                raise ValueError(
                    "ffmpeg_args must not contain absolute paths, including "
                    "embedded in option/filter values (workdir-relative "
                    "only): %r" % element)
            scheme = _SCHEME_PREFIX_RE.match(tok)
            if scheme and scheme.group(1).lower() in _REJECTED_SCHEMES:
                raise ValueError(
                    "ffmpeg_args must not contain URL/protocol values "
                    "(no network I/O, no local-protocol reads), including "
                    "embedded in option/filter values: %r" % element)
            if (tok in ("-protocol_whitelist", "--protocol_whitelist")
                    or tok.startswith(("-protocol_whitelist=",
                                       "--protocol_whitelist="))):
                raise ValueError(
                    "ffmpeg_args must not set -protocol_whitelist "
                    "(the module locks it to %r)" % _FFMPEG_PROTOCOL_WHITELIST)
    _require_concat_safe(args)
    _reject_capture_formats(args)
    if workdir is not None:
        _validate_tee_branches(args, workdir)
        _validate_referenced_files(args, workdir)
    return args


def _confine(workdir: str, rel_path: str) -> str:
    """Resolve rel_path inside workdir; raise ValueError on escape attempts."""
    base = os.path.realpath(os.path.abspath(workdir))
    target = os.path.realpath(os.path.abspath(os.path.join(base, rel_path)))
    if os.path.commonpath([base, target]) != base:
        raise ValueError(f"path escapes workdir: {rel_path!r}")
    return target


def _ensure_workdir(workdir: str) -> str:
    absdir = os.path.abspath(workdir)
    os.makedirs(absdir, exist_ok=True)
    return absdir


# ---------------------------------------------------------------------------
# Job submission / status / cancellation
# ---------------------------------------------------------------------------

def _validate_render_params(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("render params must be a dict")
    args = params.get("ffmpeg_args")
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        raise ValueError("render params['ffmpeg_args'] must be a non-empty list of strings")
    _validate_ffmpeg_args(args, params.get("workdir"))  # no absolute paths, no URLs: workdir-relative only
    output = params.get("output")
    if not isinstance(output, str) or not output:
        raise ValueError("render params['output'] must be a non-empty string")
    workdir = params.get("workdir")
    if not isinstance(workdir, str) or not workdir:
        raise ValueError("render params['workdir'] must be a non-empty string")
    timeout = params.get("timeout_s", 3600)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("render params['timeout_s'] must be a positive number")
    duration = params.get("duration_s")
    if duration is not None and (not isinstance(duration, (int, float)) or duration <= 0):
        raise ValueError("render params['duration_s'] must be a positive number or omitted")
    return {"ffmpeg_args": args, "output": output, "workdir": workdir,
            "timeout_s": float(timeout), "duration_s": duration}


def _validate_produce_params(params: dict) -> dict:
    if not isinstance(params, dict):
        raise ValueError("produce params must be a dict")
    workdir = params.get("workdir")
    if not isinstance(workdir, str) or not workdir:
        raise ValueError("produce params['workdir'] must be a non-empty string")
    steps = params.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("produce params['steps'] must be a non-empty list")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"produce step {i} must be a dict")
        op = step.get("op")
        if op not in _PRODUCE_OPS:
            raise ValueError(f"produce step {i}: unknown op {op!r}; allowed: {_PRODUCE_OPS}")
        sp = step.get("params", {})
        if not isinstance(sp, dict):
            raise ValueError(f"produce step {i}: params must be a dict")
        if op == "ffmpeg":
            # Fail fast at submit, like the render path: ffmpeg_args must be
            # workdir-confined (no absolute paths, no URLs, no ".." escapes).
            fargs = sp.get("ffmpeg_args")
            if isinstance(fargs, list) and fargs and all(isinstance(a, str) for a in fargs):
                _validate_ffmpeg_args(fargs, params.get("workdir"))
    timeout = params.get("timeout_s", 3600)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("produce params['timeout_s'] must be a positive number")
    return {"workdir": workdir, "steps": steps, "timeout_s": float(timeout)}


def submit_job(job: dict) -> str:
    """Validate and enqueue a job. Returns the new job id (str).

    job = {"kind": "render"|"produce", "name": str, "params": {...},
           "priority": int (optional)}
    Raises ValueError on invalid input.
    """
    if not isinstance(job, dict):
        raise ValueError("job must be a dict")
    kind = job.get("kind")
    if kind not in _JOB_KINDS:
        raise ValueError(f"job['kind'] must be one of {_JOB_KINDS}, got {kind!r}")
    name = job.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("job['name'] must be a non-empty string")
    priority = job.get("priority", 0)
    if not isinstance(priority, int):
        raise ValueError("job['priority'] must be an int")
    raw_params = job.get("params", {})
    params = (_validate_render_params(raw_params) if kind == RENDER_KIND
              else _validate_produce_params(raw_params))
    # Fail fast: workdir must be creatable; output must stay inside it.
    workdir = _ensure_workdir(params["workdir"])
    params["workdir"] = workdir
    if kind == RENDER_KIND:
        _confine(workdir, params["output"])
    else:
        # Confine every produce ffmpeg step's output at submit (fail fast,
        # same as the render path).
        for step in params["steps"]:
            if step.get("op") == "ffmpeg":
                sp = step.get("params", {})
                output = sp.get("output")
                if isinstance(output, str) and output:
                    _confine(workdir, output)

    job_id = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO jobs (id, kind, name, params, priority, state, created_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, name.strip(), json.dumps(params), priority,
             STATE_PENDING, _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def _row_to_status(row: sqlite3.Row) -> dict:
    result = json.loads(row["result"]) if row["result"] else None
    return {
        "status": "ok",
        "job_id": row["id"],
        "kind": row["kind"],
        "name": row["name"],
        "priority": row["priority"],
        "state": row["state"],
        "progress": row["progress"],
        "error": row["error"],
        "result": result,
        "created_utc": row["created_utc"],
        "started_utc": row["started_utc"],
        "finished_utc": row["finished_utc"],
    }


def job_status(job_id: str) -> dict:
    """Return the current status dict for a job, or {"status": "not_found"}."""
    if not isinstance(job_id, str) or not job_id:
        return {"status": "not_found", "job_id": job_id}
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"status": "not_found", "job_id": job_id}
    return _row_to_status(row)


def cancel_job(job_id: str) -> dict:
    """Cancel a pending job, or request cancellation of a running job.

    Running-job cancellation works only when the worker runs in-process.
    """
    if not isinstance(job_id, str) or not job_id:
        return {"status": "not_found", "job_id": job_id}
    conn = _connect()
    try:
        row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return {"status": "not_found", "job_id": job_id}
        state = row["state"]
        if state == STATE_PENDING:
            conn.execute(
                "UPDATE jobs SET state = ?, finished_utc = ? WHERE id = ?",
                (STATE_CANCELLED, _utcnow(), job_id),
            )
            conn.commit()
            return {"status": "ok", "job_id": job_id, "state": STATE_CANCELLED}
        if state == STATE_RUNNING:
            with _cancel_lock:
                ev = _cancel_events.get(job_id)
            if ev is not None:
                ev.set()
                return {"status": "ok", "job_id": job_id,
                        "state": STATE_RUNNING, "note": "cancellation requested"}
            return {"status": "not_cancellable", "job_id": job_id,
                    "reason": "worker not running in-process; cannot signal running job"}
        return {"status": "not_cancellable", "job_id": job_id,
                "reason": f"job already in terminal state {state!r}"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Worker: job execution
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _parse_ffmpeg_time(stderr_tail: str) -> float | None:
    """Parse the last 'time=HH:MM:SS.xx' from ffmpeg stderr. Returns seconds."""
    matches = _TIME_RE.findall(stderr_tail)
    if not matches:
        return None
    h, m, s = matches[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _run_ffmpeg(args: list[str], output_path: str, workdir: str,
                timeout_s: float, duration_s: float | None,
                cancel_event: threading.Event,
                progress_cb) -> dict:
    """Run ffmpeg with a list-form command (no shell). Returns a result dict.

    Raises CancelledError / TimeoutError / RuntimeError on failure.
    """
    ffmpeg_bin = _find_ffmpeg()
    if ffmpeg_bin is None:
        raise RuntimeError("ffmpeg executable not found on PATH")
    # Lock ffmpeg to the module's protocol whitelist (file/pipe/lavfi):
    # even a URL that slipped past submit-time validation is refused by
    # ffmpeg itself before any connection or file open. Callers cannot
    # override it ("-protocol_whitelist" is rejected in ffmpeg_args).
    cmd = [ffmpeg_bin, "-protocol_whitelist", _FFMPEG_PROTOCOL_WHITELIST] + args
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL, text=True, cwd=workdir,
    )
    stderr_chunks: list[str] = []
    stderr_lock = threading.Lock()

    def _drain() -> None:
        # ffmpeg writes progress to stderr; drain continuously so the
        # pipe never fills and blocks the encoder.
        assert proc.stderr is not None
        for line in proc.stderr:
            with stderr_lock:
                stderr_chunks.append(line)

    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()
    try:
        elapsed = 0.0
        poll = 0.2
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            if cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise _Cancelled()
            if elapsed >= timeout_s:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TimeoutError(f"ffmpeg exceeded timeout_s={timeout_s}")
            try:
                proc.wait(timeout=poll)
            except subprocess.TimeoutExpired:
                elapsed += poll
                # Report live progress from drained stderr when duration known.
                if duration_s:
                    with stderr_lock:
                        tail = "".join(stderr_chunks)
                    secs = _parse_ffmpeg_time(tail)
                    if secs is not None:
                        progress_cb(min(0.99, secs / duration_s))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        drain_thread.join(timeout=5)

    with stderr_lock:
        tail = "".join(stderr_chunks)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited with code {proc.returncode}; stderr tail: {tail[-2000:]}")
    if duration_s:
        progress_cb(1.0)
    result = {"returncode": proc.returncode, "output": output_path}
    secs = _parse_ffmpeg_time(tail)
    if secs is not None:
        result["encoded_seconds"] = secs
    return result


class _Cancelled(Exception):
    """Internal: job was cancelled while running."""


def _execute_render(params: dict, cancel_event: threading.Event,
                    progress_cb) -> dict:
    workdir = params["workdir"]
    # Re-validate at run time: params come from the SQLite row, so the
    # submit-time gate is not the only check standing between the queue
    # and ffmpeg. Referenced indirect files (filter scripts, playlists,
    # concat lists) are re-validated here too — a produce job may have
    # created them with write_file after submit.
    _validate_ffmpeg_args(params["ffmpeg_args"], workdir)
    output_rel = params["output"]
    output_abs = _confine(workdir, output_rel)
    os.makedirs(os.path.dirname(output_abs) or workdir, exist_ok=True)
    res = _run_ffmpeg(params["ffmpeg_args"], output_abs, workdir,
                      params["timeout_s"], params.get("duration_s"),
                      cancel_event, progress_cb)
    if not os.path.isfile(output_abs):
        raise RuntimeError(f"ffmpeg reported success but output missing: {output_abs}")
    res["output"] = output_abs
    return res


def _execute_produce_step(step: dict, workdir: str, timeout_s: float,
                          cancel_event: threading.Event, progress_cb) -> dict:
    op = step["op"]
    sp = step.get("params", {})
    if cancel_event.is_set():
        raise _Cancelled()
    if op == "mkdir":
        path = sp.get("path")
        if not isinstance(path, str):
            raise ValueError("mkdir step requires params['path'] (str)")
        target = _confine(workdir, path)
        os.makedirs(target, exist_ok=True)
        return {"op": op, "status": "ok", "path": target}
    if op == "write_file":
        path = sp.get("path")
        content = sp.get("content", "")
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError("write_file step requires str params['path'] and params['content']")
        target = _confine(workdir, path)
        os.makedirs(os.path.dirname(target) or workdir, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"op": op, "status": "ok", "path": target, "bytes": len(content.encode("utf-8"))}
    if op == "copy_file":
        src = sp.get("src")
        dst = sp.get("dst")
        if not isinstance(src, str) or not isinstance(dst, str):
            raise ValueError("copy_file step requires str params['src'] and params['dst']")
        # copy_file src is ALWAYS confined to the workdir (review-C finding:
        # the old absolute-src allowance was an exfiltration primitive).
        src_abs = _confine(workdir, src)
        if not os.path.isfile(src_abs):
            raise ValueError(f"copy_file source not found: {src!r}")
        dst_abs = _confine(workdir, dst)
        os.makedirs(os.path.dirname(dst_abs) or workdir, exist_ok=True)
        shutil.copy2(src_abs, dst_abs)
        return {"op": op, "status": "ok", "src": src_abs, "dst": dst_abs}
    if op == "ffmpeg":
        args = sp.get("ffmpeg_args")
        output = sp.get("output")
        if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
            raise ValueError("ffmpeg step requires params['ffmpeg_args'] (non-empty list of str)")
        _validate_ffmpeg_args(args, workdir)  # no absolute paths, no URLs; indirect files re-checked
        if not isinstance(output, str) or not output:
            raise ValueError("ffmpeg step requires params['output'] (str)")
        step_timeout = sp.get("timeout_s", timeout_s)
        output_abs = _confine(workdir, output)
        os.makedirs(os.path.dirname(output_abs) or workdir, exist_ok=True)
        res = _run_ffmpeg(args, output_abs, workdir, float(step_timeout),
                          sp.get("duration_s"), cancel_event, progress_cb)
        if not os.path.isfile(output_abs):
            raise RuntimeError(f"ffmpeg step reported success but output missing: {output_abs}")
        res["output"] = output_abs
        res["op"] = op
        res["status"] = "ok"
        return res
    if op == "zip":
        sources = sp.get("sources")
        output = sp.get("output")
        if not isinstance(sources, list) or not sources:
            raise ValueError("zip step requires params['sources'] (non-empty list)")
        if not isinstance(output, str) or not output:
            raise ValueError("zip step requires params['output'] (str)")
        out_abs = _confine(workdir, output)
        os.makedirs(os.path.dirname(out_abs) or workdir, exist_ok=True)
        added = []
        with zipfile.ZipFile(out_abs, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in sources:
                if not isinstance(s, str):
                    raise ValueError("zip sources must be strings")
                s_abs = _confine(workdir, s)
                if not os.path.isfile(s_abs):
                    raise ValueError(f"zip source not found: {s!r}")
                zf.write(s_abs, arcname=os.path.basename(s_abs))
                added.append(s_abs)
        return {"op": op, "status": "ok", "output": out_abs, "files": added}
    raise ValueError(f"unknown op {op!r}")  # unreachable: validated at submit


def _execute_produce(params: dict, cancel_event: threading.Event,
                     progress_cb) -> dict:
    workdir = _ensure_workdir(params["workdir"])
    steps = params["steps"]
    timeout_s = params["timeout_s"]
    done_steps = []
    for i, step in enumerate(steps):
        if cancel_event.is_set():
            raise _Cancelled()
        detail = _execute_produce_step(step, workdir, timeout_s, cancel_event,
                                       lambda p, i=i: progress_cb((i + p) / len(steps)))
        done_steps.append(detail)
        progress_cb((i + 1) / len(steps))
    return {"workdir": workdir, "steps": done_steps}


def _set_state(db_path: str | None, job_id: str, state: str,
               progress: float | None = None, error: str | None = None,
               result: dict | None = None) -> None:
    conn = _connect(db_path)
    try:
        fields = ["state = ?"]
        values: list = [state]
        if progress is not None:
            fields.append("progress = ?")
            values.append(progress)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if result is not None:
            fields.append("result = ?")
            values.append(json.dumps(result))
        if state in (STATE_DONE, STATE_FAILED, STATE_CANCELLED):
            fields.append("finished_utc = ?")
            values.append(_utcnow())
        values.append(job_id)
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def process_next_job(db_path: str | None = None) -> dict:
    """Run the highest-priority pending job synchronously.

    Returns {"status": "processed", "job_id": ..., "state": ...} or
    {"status": "idle"} when the queue is empty.
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY priority DESC, created_utc ASC LIMIT 1",
            (STATE_PENDING,),
        ).fetchone()
        if row is None:
            return {"status": "idle"}
        job_id = row["id"]
        kind = row["kind"]
        params = json.loads(row["params"])
        # ATOMIC CLAIM (re-review F-F): the UPDATE flips pending->running
        # only if the row is STILL pending. A racing worker's UPDATE then
        # matches zero rows and it backs off, so a job can never execute
        # twice. cur.rowcount is the arbiter, not the earlier SELECT.
        cur = conn.execute(
            "UPDATE jobs SET state = ?, started_utc = ?, progress = 0 "
            "WHERE id = ? AND state = ?",
            (STATE_RUNNING, _utcnow(), job_id, STATE_PENDING),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"status": "idle"}  # lost the race; another worker owns it
    finally:
        conn.close()

    cancel_event = threading.Event()
    with _cancel_lock:
        _cancel_events[job_id] = cancel_event

    def progress_cb(p: float) -> None:
        _set_state(db_path, job_id, STATE_RUNNING, progress=max(0.0, min(1.0, p)))

    try:
        if kind == RENDER_KIND:
            result = _execute_render(params, cancel_event, progress_cb)
        else:
            result = _execute_produce(params, cancel_event, progress_cb)
    except _Cancelled:
        _set_state(db_path, job_id, STATE_CANCELLED, error="cancelled by user")
        return {"status": "processed", "job_id": job_id, "state": STATE_CANCELLED}
    except Exception as exc:  # noqa: BLE001 - worker must record, not crash
        _set_state(db_path, job_id, STATE_FAILED, error=f"{type(exc).__name__}: {exc}")
        return {"status": "processed", "job_id": job_id, "state": STATE_FAILED}
    finally:
        with _cancel_lock:
            _cancel_events.pop(job_id, None)

    _set_state(db_path, job_id, STATE_DONE, progress=1.0, result=result)
    return {"status": "processed", "job_id": job_id, "state": STATE_DONE}


def start_worker(stop_event: threading.Event, db_path: str | None = None,
                 poll_s: float = 2.0) -> threading.Thread:
    """Start a daemon worker thread processing the queue until stop_event is set."""
    def _loop() -> None:
        while not stop_event.is_set():
            try:
                res = process_next_job(db_path)
            except Exception:  # noqa: BLE001 - worker loop must not die
                res = {"status": "error"}
            if res.get("status") == "idle":
                stop_event.wait(poll_s)

    thread = threading.Thread(target=_loop, name="genesis-station-worker", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Hardware probing (honest: only reports what the OS actually exposes)
# ---------------------------------------------------------------------------

def _cpu_brand() -> str:
    """Best-effort CPU brand string; 'unknown' when not detectable."""
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            lines = [ln.strip() for ln in out.splitlines()
                     if ln.strip() and ln.strip().lower() != "name"]
            if lines:
                return lines[0]
        else:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001 - probing must never crash
        pass
    return "unknown"


def _memory_bytes() -> tuple[int | None, str]:
    """(total_bytes or None, source description)."""
    try:
        if os.name == "nt":
            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys), "GlobalMemoryStatusEx"
        else:
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb * 1024, "/proc/meminfo"
    except Exception:  # noqa: BLE001
        pass
    return None, "undetectable"


def _gpu_info() -> dict:
    """Detect GPUs without claiming capabilities we cannot verify."""
    devices: list[str] = []
    source = "none"
    try:
        nvidia = shutil.which("nvidia-smi")
        if nvidia:
            out = subprocess.run(
                [nvidia, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            names = [ln.strip() for ln in out.splitlines() if ln.strip()]
            if names:
                devices.extend(names)
                source = "nvidia-smi"
        if os.name == "nt" and not devices:
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=15,
            ).stdout
            names = [ln.strip() for ln in out.splitlines()
                     if ln.strip() and ln.strip().lower() != "name"]
            if names:
                devices.extend(names)
                source = "wmic win32_VideoController"
    except Exception:  # noqa: BLE001
        pass
    return {"detected": bool(devices), "devices": devices, "source": source}


def _ffmpeg_info() -> dict:
    path = shutil.which("ffmpeg")
    if not path:
        return {"present": False, "path": None, "version": None}
    version = None
    try:
        out = subprocess.run([path, "-version"], capture_output=True,
                             text=True, timeout=10).stdout
        first = out.splitlines()[0] if out else ""
        m = re.search(r"ffmpeg version (\S+)", first)
        if m:
            version = m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return {"present": True, "path": path, "version": version or "unknown"}


def probe_hardware() -> dict:
    """Honestly probe local hardware. Never claims undetected capabilities."""
    total, mem_source = _memory_bytes()
    return {
        "status": "ok",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "logical_count": os.cpu_count(),
            "brand": _cpu_brand(),
        },
        "memory": {
            "total_bytes": total,
            "source": mem_source,
        },
        "gpu": _gpu_info(),
        "ffmpeg": _ffmpeg_info(),
        "note": ("Values come from live OS queries at call time. 'unknown' means "
                 "not detectable on this machine, not absent."),
    }


__all__ = ["submit_job", "job_status", "cancel_job", "probe_hardware",
           "process_next_job", "start_worker"]
