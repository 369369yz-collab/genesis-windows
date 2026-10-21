# ---------------------------------------------------------------------------
# VENDORED COPY - GENESIS embed step 7, Phase 2 (2026-10-21).
# Source: ~/workspace/content_team/quantum/qrng.py (369 quantum seed layer, content_team).
# Copied verbatim except where a "VENDORING ADAPTATION" note says
# otherwise. The upstream file remains the canonical world copy; this
# embed exists so the shipped app carries the seed layer inside itself
# (YZ law 2026-10-16: the whole 369 world lives inside GENESIS).
# Runtime state (mother seed, consumers, audit log) lives in the
# sibling state/ directory of THIS copy - separate from the world copy.
# ---------------------------------------------------------------------------
"""
369 Quantum Seed Bank — multi-source quantum randomness with automatic failover.

Failover order (quantum-first, all free, no signup):
  1. ANU QRNG public API (true quantum, vacuum fluctuations)      [quantum=True]
  2. drand League of Entropy quicknet (distributed BLS beacon)   [quantum=False, verifiable]
  3. NIST Randomness Beacon (signed 60s pulses)                   [quantum=False, signed]
  4. os.urandom (local CSPRNG)                                    [quantum=False, LAST RESORT, always logged]

Design:
  - One mother seed (64 bytes) per UTC day, cached in state/mother_seed.json.
  - Every decision derives from the mother seed via SHAKE128 with domain
    separation: derive(domain, n_bytes, counter). Deterministic + auditable.
  - The network is polled AT MOST once per day (mother seed fetch). Politeness
    is therefore trivially satisfied; per-source min-interval guards still apply.
  - Fallback to a lower source is ALWAYS logged to state/failover.log — never silent.

Public API:
  get_mother_seed()          -> (seed: bytes, source: str, quantum: bool, date: str)
  derive(domain, n=32, counter=0) -> bytes   (uses today's mother seed)
  draw_int(domain, lo, hi, counter=0) -> int (unbiased, rejection sampling)
  get_bytes(n, purpose="")    -> (bytes, source, quantum)  (direct fetch, failover chain)
"""

import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
MOTHER_FILE = os.path.join(STATE, "mother_seed.json")
FAILOVER_LOG = os.path.join(STATE, "failover.log")
POLL_FILE = os.path.join(STATE, "source_polls.json")

TIMEOUT = 15  # seconds per HTTP attempt


# ---------------------------------------------------------------- sources

def _parse_anu_jsonI(payload: bytes, n: int) -> bytes:
    d = json.loads(payload.decode("utf-8"))
    if not d.get("success"):
        raise ValueError("ANU success=false")
    data = d["data"]
    if len(data) < n:
        raise ValueError(f"ANU short read: {len(data)} < {n}")
    return bytes(data[:n])


def _parse_drand(payload: bytes, n: int) -> bytes:
    d = json.loads(payload.decode("utf-8"))
    raw = bytes.fromhex(d["randomness"])
    if len(raw) < n:
        raise ValueError(f"drand short read: {len(raw)} < {n}")
    return raw[:n]


def _parse_nist(payload: bytes, n: int) -> bytes:
    d = json.loads(payload.decode("utf-8"))
    raw = bytes.fromhex(d["pulse"]["outputValue"])
    if len(raw) < n:
        raise ValueError(f"NIST short read: {len(raw)} < {n}")
    return raw[:n]


def _parse_drand_v2(payload: bytes, n: int) -> bytes:
    # v2 quicknet: {"round": N, "randomness": "<64hex>", "signature": ...}
    # v1 (/public/latest): {"round": N, "randomness": "<64hex>", ...} — same field
    d = json.loads(payload.decode("utf-8"))
    raw = bytes.fromhex(d["randomness"])
    if len(raw) < n:
        raise ValueError(f"drand short read: {len(raw)} < {n}")
    return raw[:n]


SOURCES = [
    {
        "name": "anu_qrng",
        "quantum": True,
        "urls": ["https://qrng.anu.edu.au/API/jsonI.php?length={n}&type=uint8"],
        "parse": _parse_anu_jsonI,
        "min_interval_s": 180,
        "note": "True quantum RNG (vacuum fluctuations). Free public endpoint.",
    },
    {
        "name": "drand_quicknet",
        "quantum": False,
        "urls": [
            "https://api.drand.sh/v2/beacons/quicknet/rounds/latest",
            "https://drand.cloudflare.com/v2/beacons/quicknet/rounds/latest",
            "https://api2.drand.sh/v2/beacons/quicknet/rounds/latest",
        ],
        "parse": _parse_drand_v2,
        "min_interval_s": 10,
        "note": "League of Entropy distributed beacon, 3s rounds, publicly verifiable. Not quantum hardware.",
    },
    {
        "name": "nist_beacon",
        "quantum": False,
        "urls": ["https://beacon.nist.gov/beacon/2.0/pulse/last"],
        "parse": _parse_nist,
        "min_interval_s": 60,
        "note": "NIST public randomness beacon, 60s signed pulses. Not quantum hardware.",
    },
]


# v1 compatibility: some relays only speak v1 (/public/latest) — same "randomness" field
SOURCES[1]["urls"].append("https://api.drand.sh/public/latest")


# ---------------------------------------------------------------- helpers

def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def _log_failover(message: str):
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(FAILOVER_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}Z] {message}\n")


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "369-quantum-seedbank/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if r.status != 200:
            raise ValueError(f"HTTP {r.status}")
        return r.read()


def _polite(source: dict) -> bool:
    """True if we may poll this source now (respects min_interval_s)."""
    polls = _load_json(POLL_FILE, {})
    last = polls.get(source["name"], 0)
    if time.time() - last < source["min_interval_s"]:
        return False
    polls[source["name"]] = time.time()
    _save_json(POLL_FILE, polls)
    return True


# ---------------------------------------------------------------- core

def get_bytes(n: int, purpose: str = "") -> tuple:
    """
    Fetch n raw bytes from the first available source in failover order.
    Returns (bytes, source_name, is_quantum). Every fallback is logged.
    Last resort is os.urandom (CSPRNG) — honest, never silent.
    """
    if n <= 0 or n > 4096:
        raise ValueError("n must be 1..4096")
    attempted = []
    for src in SOURCES:
        if not _polite(src):
            attempted.append(f"{src['name']}(polite-skip)")
            continue
        for url_t in src["urls"]:
            url = url_t.format(n=n)
            try:
                raw = src["parse"](_http_get(url), n)
                if attempted:
                    _log_failover(
                        f"get_bytes(n={n}, purpose={purpose!r}) fell through "
                        f"{attempted} -> using {src['name']} ({url})"
                    )
                return raw, src["name"], src["quantum"]
            except Exception as e:  # noqa: BLE001 - any failure moves to next source
                attempted.append(f"{src['name']}({type(e).__name__})")
                continue
    # ---- last resort: local CSPRNG, ALWAYS logged
    _log_failover(
        f"get_bytes(n={n}, purpose={purpose!r}) ALL network sources failed "
        f"[{', '.join(attempted)}] -> FALLBACK os.urandom (NOT quantum)"
    )
    return os.urandom(n), "os_urandom", False


def get_mother_seed() -> tuple:
    """
    One 64-byte mother seed per UTC day, cached in state/mother_seed.json.
    Returns (seed, source_name, is_quantum, date_str).

    LAW-099: the cached seed is integrity-sealed. Any tamper fails closed.
    """
    # VENDORING ADAPTATION: upstream reads "from quantum import seed_seal";
    # inside the vendored brain.quantum package this is a relative import.
    from . import seed_seal  # noqa: PLC0415 — lazy, keeps import light

    today = _utc_today()
    try:
        cached = seed_seal.read_sealed()
    except seed_seal.SeedTamperError:
        raise
    except Exception:
        cached = {}
    if cached.get("date") == today and cached.get("seed_hex"):
        return bytes.fromhex(cached["seed_hex"]), cached["source"], cached["quantum"], today
    seed, source, quantum = get_bytes(64, purpose="mother-seed")
    seed_seal.write_sealed({
        "date": today,
        "seed_hex": seed.hex(),
        "source": source,
        "quantum": quantum,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
    })
    return seed, source, quantum, today


def _domain_key(domain: str, date: str, counter: int) -> bytes:
    return b"|".join([b"369q", date.encode(), domain.encode(), str(counter).encode()])


def derive(domain: str, n: int = 32, counter: int = 0) -> bytes:
    """SHAKE128-derived bytes, domain-separated. Deterministic for audit replay."""
    if not domain or n <= 0 or n > 1024:
        raise ValueError("bad domain/n")
    seed, _src, _q, date = get_mother_seed()
    h = hashlib.shake_128()
    h.update(seed)
    h.update(_domain_key(domain, date, counter))
    return h.digest(n)


def draw_int(domain: str, lo: int, hi: int, counter: int = 0) -> int:
    """Unbiased integer in [lo, hi) via rejection sampling over SHAKE128 stream."""
    if not (0 <= lo < hi):
        raise ValueError("need 0 <= lo < hi")
    span = hi - lo
    # bytes needed: enough bits to cover span, rejection-sampled
    bitlen = span.bit_length()
    nbytes = max(4, (bitlen + 7) // 8 + 1)
    limit = (256 ** nbytes) // span * span
    ctr = counter
    while True:
        val = int.from_bytes(derive(domain, nbytes, ctr), "big")
        if val < limit:
            return lo + (val % span)
        ctr += 1  # astronomically rare; counter domain keeps it deterministic


def mother_info() -> dict:
    seed, source, quantum, date = get_mother_seed()
    return {
        "date": date,
        "source": source,
        "quantum": quantum,
        "seed_sha256": hashlib.sha256(seed).hexdigest(),
    }


if __name__ == "__main__":
    info = mother_info()
    print(json.dumps(info, indent=2))
    print("draw_int('smoke', 0, 100) =", draw_int("smoke", 0, 100))
