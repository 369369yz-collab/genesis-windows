# Dialogue-Enriched Dataset — Build Report
**Date:** 2026-10-16 ~14:30–15:05 Tehran
**Authorization:** YZ direct 2026-10-16 ~14:27 Tehran («بله، دیالوگ‌هام بره توی دیتاست»)
**Builder:** `build_369_dialogue.py` (reproducible; no commit, no training launch)

## Source
- `runtime.messages` ⋈ `runtime.events`, `transcript_surface='main_chat'`
- Verified totals: **2,773 YZ messages / 5,028 assistant messages** (2026-10-06 → 2026-10-16)
- Curation backbone: `history_chunks/` — 420 typed items
  (decision 138 · law 121 · doctrine 52 · correction 49 · milestone 28 · identity 18 · other 14)

## Pipeline
1. Parsed 420 chunk items → 414 unique timestamps
2. Fetched 501 YZ messages at those timestamps (3 batched queries)
3. Fetched each message's next assistant reply (scalar-subquery batches;
   `unnest`/`LATERAL` are outside the DB tool's safe set — worked around)
4. Cleaned: stripped `[image:/file:/video:/audio:]` markers, `[[hatch_widget:]]`
   markup, collapsed whitespace, trimmed replies to ≤1500 chars at sentence boundary
5. Filtered: user <15 chars (32), URL-only (3), empty reply — widget-only (77),
   reply <20 chars (1), duplicates (0)
6. Built ShareGPT SFT records (same SYSTEM prompt as existing set)
7. Mined 32 DPO pairs from 36 documented corrections (wrong→right);
   merged near-duplicates (GTA wording ×3→1, banner ×2→1); dropped 1 mismatched
   chunk item; 4 corrections lacked usable wrong/right
8. Merged with existing files; validated from disk

## Results
| File | Records | Notes |
|---|---|---|
| `369_sft.jsonl` (existing) | 57 | untouched |
| `369_dpo.jsonl` (existing) | 6 | untouched |
| `369_sft_dialogue.jsonl` | **388** | new: real YZ↔GENESIS exchanges |
| `369_dpo_dialogue.jsonl` | **32** | new: correction-derived preferences |
| `369_sft_full.jsonl` | **445** | 57 + 388, deduped on user text |
| `369_dpo_full.jsonl` | **38** | 6 + 32 |

**Reconciliation:** 501 in = 388 pairs + 113 skipped (32+3+77+1+0) ✓
**Validation:** every line parses; roles exact; no empty content; no duplicate
user texts; no widget/media markup leaks; chosen ≠ rejected; existing 57/6 intact.
Arithmetic: 57+388=445, 6+32=38 ✓

## Quality notes
- Twin-duplex honored: user side is YZ verbatim, assistant side is GENESIS's real reply.
- SFT pair length: user median 111 chars (15–2107), reply median 328 chars (22–1464).
- DPO chosen/rejected written in GENESIS's Persian voice, faithful to each
  correction's documented right/wrong behavior (consistent with the existing
  hand-written DPO set's nature).
- Not committed. Training launch still gated on free GPU slot (Kaggle/Colab).
