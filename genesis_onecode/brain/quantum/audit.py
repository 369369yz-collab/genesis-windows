# ---------------------------------------------------------------------------
# VENDORED COPY - GENESIS embed step 7, Phase 2 (2026-10-21).
# Source: ~/workspace/content_team/quantum/audit.py (369 quantum seed layer, content_team).
# Copied verbatim except where a "VENDORING ADAPTATION" note says
# otherwise. The upstream file remains the canonical world copy; this
# embed exists so the shipped app carries the seed layer inside itself
# (YZ law 2026-10-16: the whole 369 world lives inside GENESIS).
# Runtime state (mother seed, consumers, audit log) lives in the
# sibling state/ directory of THIS copy - separate from the world copy.
# ---------------------------------------------------------------------------
"""
369 Quantum Audit — every decision logged, every decision provable.

Log: state/decisions.jsonl — one JSON object per line, append-only.
Each record carries everything the proof checker needs to REPLAY it:
  domain, counter, eligible (ordered candidate list at draw time),
  index, choice, seed_source, quantum, date, window, excluded_recent.

Proof (MATHEMATICAL PRECISION LAW):
  for each record in chronological order:
      expected_index = SHAKE128(mother_seed(date) || domain || date || counter) -> [0, len(eligible))
      assert expected_index == record.index and eligible[expected_index] == record.choice
      assert choice not in excluded_recent (unless window_reset)
Any mismatch -> flag. Repeats inside a domain's window -> flag.

Note: mother seeds are cached per day in state/mother_seed.json; the checker
re-reads them (or the current one for today's records). Historical seeds persist
because the file is only overwritten when the date changes — for a full
multi-day replay the checker keeps a seed archive (state/seed_archive.jsonl).
"""

import hashlib
import json
import os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
DECISIONS = os.path.join(STATE, "decisions.jsonl")
SEED_ARCHIVE = os.path.join(STATE, "seed_archive.jsonl")
# Network check-ins are connection proofs, NOT seed decisions: since the
# 2026-10-11 hub cut-over they live in their own append-only ledger so
# decisions.jsonl stays purely seed decisions (replayable by proof_check).
NETWORK_LOG = os.path.join(STATE, "network_checkins.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"


def log(record: dict):
    record = dict(record)
    if "ts" not in record:
        record["ts"] = utc_now()
    with open(DECISIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _archive_seed(record)


def _archive_seed(record: dict):
    """Keep every mother seed ever used, so replay works across days."""
    from . import qrng
    rec = _mother_seed_record(_load_json(qrng.MOTHER_FILE, {}))
    if not rec:
        return
    have = set()
    try:
        with open(SEED_ARCHIVE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    have.add(json.loads(line)["date"])
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    if rec["date"] in have:
        return
    with open(SEED_ARCHIVE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "date": rec["date"],
            "seed_hex": rec["seed_hex"],
            "source": rec.get("source"),
            "quantum": rec.get("quantum"),
        }) + "\n")


def read_all() -> list:
    out = []
    try:
        with open(DECISIONS, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except OSError:
        pass
    return out


def log_checkin(record: dict):
    """Append a network connection-proof record to the check-in ledger.

    Check-ins are NOT seed decisions and must never enter decisions.jsonl
    (they would break proof_check replay: they carry no seed fields).
    """
    record = dict(record)
    if "ts" not in record:
        record["ts"] = utc_now()
    os.makedirs(os.path.dirname(NETWORK_LOG), exist_ok=True)
    with open(NETWORK_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_checkins() -> list:
    """Read the network check-in ledger (connection proofs)."""
    out = []
    try:
        with open(NETWORK_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except OSError:
        pass
    return out


def recent_choices(domain: str, k: int) -> list:
    """Newest-first list of the last k choices for a domain."""
    out = []
    for rec in reversed(read_all()):
        if rec.get("domain") == domain:
            out.append(rec["choice"])
            if len(out) >= k:
                break
    return out


def next_counter(domain: str) -> int:
    n = 0
    for rec in read_all():
        if rec.get("domain") == domain:
            n = max(n, rec.get("counter", -1) + 1)
    return n


def _mother_seed_record(info):
    """Normalize a mother-seed payload to a flat record dict, or None.

    Accepts BOTH schemas:
      * flat legacy: {"date": ..., "seed_hex": ..., "source": ..., "quantum": ...}
      * LAW-099 nested-sealed: {"seed": {"date": ..., "seed_hex": ...},
                                "seal": <hex>, "law": "LAW-099", "sealed_at": ...}
    The nested form is trusted only when the seal STRUCTURE is present
    (non-empty str seal, law == "LAW-099", and a dict seed holding
    date + seed_hex). Cryptographic HMAC verification stays in seed_seal.py;
    this reader validates structure. FAIL CLOSED: any malformed shape
    returns None, never raises.
    """
    if not isinstance(info, dict):
        return None
    if info.get("date") and info.get("seed_hex"):
        # flat legacy schema
        return {
            "date": info.get("date"),
            "seed_hex": info.get("seed_hex"),
            "source": info.get("source"),
            "quantum": info.get("quantum"),
        }
    seed = info.get("seed")
    if not isinstance(seed, dict):
        return None
    if not (isinstance(info.get("seal"), str) and info.get("seal")):
        return None  # LAW-099 tamper-evidence tag missing or not a string
    if info.get("law") != "LAW-099":
        return None  # sealed under an unknown law — do not trust
    if not (seed.get("date") and seed.get("seed_hex")):
        return None
    return {
        "date": seed.get("date"),
        "seed_hex": seed.get("seed_hex"),
        "source": seed.get("source"),
        "quantum": seed.get("quantum"),
    }


def _seed_for(date: str):
    """Return the mother seed bytes for a date (archive, then today's cache).

    The mother-seed file exists in two schemas (flat legacy, LAW-099
    nested-sealed); both are accepted via _mother_seed_record. Fail closed:
    malformed payloads or bad hex -> None, never an exception.
    """
    try:
        with open(SEED_ARCHIVE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("date") == date and d.get("seed_hex"):
                    try:
                        return bytes.fromhex(d["seed_hex"])
                    except (ValueError, TypeError):
                        continue
    except OSError:
        pass
    from . import qrng
    rec = _mother_seed_record(_load_json(qrng.MOTHER_FILE, {}))
    if rec is not None and rec["date"] == date and rec["seed_hex"]:
        try:
            return bytes.fromhex(rec["seed_hex"])
        except (ValueError, TypeError):
            return None
    return None


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _expected_index(seed: bytes, record: dict) -> int:
    h = hashlib.shake_128()
    h.update(seed)
    h.update(b"|".join([b"369q", record["date"].encode(),
                        record["domain"].encode(), str(record["counter"]).encode()]))
    nbytes = max(4, (len(record["eligible"]).bit_length() + 7) // 8 + 1)
    span = len(record["eligible"])
    limit = (256 ** nbytes) // span * span
    ctr = record["counter"]
    # mirror draw_int's rejection loop deterministically
    while True:
        hh = hashlib.shake_128()
        hh.update(seed)
        hh.update(b"|".join([b"369q", record["date"].encode(),
                             record["domain"].encode(), str(ctr).encode()]))
        val = int.from_bytes(hh.digest(nbytes), "big")
        if val < limit:
            return val % span
        ctr += 1


def proof_check() -> dict:
    """
    Replay every logged decision and verify:
      1. the index re-derives from the archived mother seed (not fabricated)
      2. eligible[index] == choice
      3. no repeat inside the domain's exclusion window (unless window_reset)
    Returns {ok, checked, replays_ok, repeats, errors}.
    """
    records = read_all()
    repeats, errors = [], []
    replays_ok = 0
    seen_windows = {}  # domain -> list of recent choices (newest-first), replayed

    for i, rec in enumerate(records):
        domain = rec.get("domain", "?")
        # hub "bytes" records (round ids, salts): no eligible pool — verify by
        # re-derivation from the archived mother seed (same cryptographic
        # strength as index replay). Lazy import: seed_hub imports audit.
        if str(rec.get("hub", "")).startswith("seed_hub/") and \
                rec.get("kind") == "bytes":
            from . import seed_hub as _hub
            v = _hub.verify_record(rec)
            if v["ok"]:
                replays_ok += 1
            else:
                errors.append({"i": i, "domain": domain, "error": v["reason"]})
            continue
        try:
            seed = _seed_for(rec["date"])
            if seed is None:
                errors.append({"i": i, "domain": domain, "error": "mother seed not archived"})
                continue
            exp = _expected_index(seed, rec)
            if exp != rec["index"] or rec["eligible"][exp] != rec["choice"]:
                errors.append({"i": i, "domain": domain,
                               "error": f"replay mismatch: expected {exp}, logged {rec['index']}"})
                continue
            replays_ok += 1

            # repeat check against replayed window
            win = seen_windows.setdefault(domain, [])
            window = rec.get("window", 0)
            if not rec.get("window_reset") and rec["choice"] in win[:window]:
                repeats.append({"i": i, "domain": domain, "choice": rec["choice"],
                                "error": f"repeat inside exclusion window ({window})"})
            win.insert(0, rec["choice"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            errors.append({"i": i, "domain": domain, "error": f"{type(e).__name__}: {e}"})

    return {
        "ok": not repeats and not errors,
        "checked": len(records),
        "replays_ok": replays_ok,
        "repeats": repeats,
        "errors": errors,
    }


def summary() -> dict:
    records = read_all()
    by_domain, quantum_n = {}, 0
    for rec in records:
        d = rec.get("domain", "?")
        by_domain[d] = by_domain.get(d, 0) + 1
        if rec.get("quantum"):
            quantum_n += 1
    return {
        "total_decisions": len(records),
        "by_domain": by_domain,
        "quantum_sourced": quantum_n,
        "non_quantum_sourced": len(records) - quantum_n,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "proof":
        print(json.dumps(proof_check(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(summary(), indent=2, ensure_ascii=False))
