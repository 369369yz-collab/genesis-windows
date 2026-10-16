# 369-Exclusive Model — the free training path

**Zero spend. No YZ hardware.** Everything runs on Kaggle's free GPU
(30h/week). YZ's RTX 5070 is never touched.

## The 3 stages (per the research dossier)

| Stage | What | Script | Output |
|---|---|---|---|
| 1. QLoRA SFT | knowledge + Persian daughter-tone | `training/train_qlora.py` | `genesis-qlora-sft/` |
| 2. QLoRA DPO | identity lock (what she never breaks) | `training/train_dpo.py` | `genesis-qlora-dpo/` |
| 3. Merge + GGUF | Q5_K_M for llama-server | `export/to_gguf.sh` | `genesis-369-q5_k_m.gguf` |

## Datasets (built, no YZ dialogues yet)

- `dataset/369_sft.jsonl` — 57 pairs (built by `build_369_dataset.py`
  from seed_facts + world + codex + persona seeds)
- `dataset/369_dpo.jsonl` — 6 pairs (built by `build_369_dpo.py`)

**Pending YZ's tap:** including his own words/dialogues in the dataset.
When he approves, we append them and rebuild — the pipeline doesn't change.

## Run it (Kaggle, free)

1. Kaggle → new Notebook → GPU **T4 x2** → Internet **ON**.
2. Upload `369_sft.jsonl` (Add data → Upload).
3. `!pip install -q transformers peft bitsandbytes accelerate datasets trl`
4. Paste/upload `train_qlora.py`, set `DATA_369` to the dataset path, Run.
5. Download `genesis-qlora-sft/` → Stage 2 the same way with `369_dpo.jsonl`.
6. Stage 3 (`export/to_gguf.sh`): merge adapters into the base, quantize
   to Q5_K_M with llama.cpp's `llama-quantize`. The GGUF ships inside the
   Windows installer (replaces the generic model).

## Honesty notes

- Training is **not** run yet — this is the prepared pipeline. The run
  needs a Kaggle account (YZ's) and his dialogue-approval tap.
- DPO pairs are few (6) — they grow as real corrections arrive; the
  identity lock strengthens with every law YZ decrees.
- If free-GPU training ever stalls, the fallback stays: Tier A (prompt) +
  Tier C (living memory) carry the full 369 identity with zero training.
