"""brain.quantum — the 369 quantum seed layer, vendored into the app.

GENESIS embed step 7, Phase 2 (2026-10-21). Source of every module here:
~/workspace/content_team/quantum/ (the canonical world copy). These are
verbatim copies with provenance headers; the ONLY code adaptation is in
qrng.py, where the lazy absolute import `from quantum import seed_seal`
became the relative `from . import seed_seal` (marked in place).

Contents:
  qrng.py      — multi-source quantum randomness (ANU QRNG first; drand /
                 NIST beacons; os.urandom last resort, always logged).
                 One integrity-sealed mother seed per UTC day.
  seed_seal.py — LAW-099 mother-seed tamper evidence (HMAC seal, fail-closed).
  audit.py     — append-only decision log; every hub draw is replayable.
  seed_hub.py  — the ONLY sanctioned seed-consumption path. Fail-closed:
                 unregistered consumers and quantum_required consumers on a
                 non-quantum mother seed are refused (the halt is logged).

QUANTUM-NAME INTEGRITY (YZ, 2026-10-11): nothing in this app may call
itself quantum unless it consumes proven quantum seeds through this hub.
Consumers that cannot get a certified draw must say so — see
brain.womb, which records every birth's seed provenance
("quantum-certified" vs "degraded-stdlib") instead of claiming silently.

Runtime state for THIS copy lives in brain/quantum/state/ (mother seed,
consumer registry, audit log, halts) — fully separate from the world
copy's state in content_team.
"""
