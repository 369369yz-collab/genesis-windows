# PROVENANCE — nexus_world/ (NEXUS world code)

Vendored for presence + importability inside the shipped app.
Per YZ's three-worlds sequencing, NEXUS stays design/spec until the
369 world completes — this code is NOT wired as a live fabric.
See README.md in this directory for the import smoke results.
- Source: `/home/hatch/workspace/content_team/nexus`
- Vendored: 2026-10-21T00:32:09+00:00Z (GENESIS embed step 7, Phase 3);
  `__init__.py` + `NEXUS_LAWS.json` completed 2026-10-21 (pre-push fix
  pass — Phase 3's enumerated list had missed the package init, which
  left the set incomplete as a package)
- Files: 9
- Total size: 111871 bytes

Copies are byte-for-byte verbatim (md5 of each vendored file below,
computed after copying, matches the source at vendor time).

| File | Bytes | MD5 |
|---|---|---|
| `nexus_laws.py` | 15883 | `e6bca3445e1c651c93c9cc06566c1dc3` |
| `gates.py` | 39793 | `41e671644e1cede0120bf220a3ac36ce` |
| `connection_graph.py` | 10629 | `17032d52cdb58c78e4a2458ec5405896` |
| `reflection.py` | 10700 | `6d552f7c71fbcae6645cb50afc8cb28b` |
| `threshold.py` | 12242 | `78d40b090c0bbd3dee697d19d3756f43` |
| `womb.py` | 14518 | `150753ddf518f22c99d1d535c4ecb2af` |
| `ledger.py` | 4621 | `dc18313ce1a6d0c9b583009c7111c82a` |
| `__init__.py` | 1912 | `419807dc55b69238a377d31daee9ffe9` |
| `NEXUS_LAWS.json` | 1573 | `78c8cfbcfb0b56db67cb78cde7e05201` |

Deliberately NOT vendored: the source package's `state/` directory
(runtime ledgers the world writes when the code actually runs there —
`gates_ledger.jsonl`, a 3.4 MB `prior_art_baseline.json`) and its
`tests/`, `HUDDLE.md`, `NEXUS_CONSTRUCTION_REPORT.md` (world-side
working documents). Runtime state is not source; the vendored tree
ships clean.
