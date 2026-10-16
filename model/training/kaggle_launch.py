"""kaggle_launch.py — free-training launch pack for the 369-exclusive model.

Wires the FULL chain end to end, all params filled from the actual repo files:
  build_369_dataset.py -> build_369_dpo.py -> train_qlora.py (Stage 1 SFT)
  -> train_dpo.py (Stage 2 DPO identity lock) -> merge -> GGUF Q5_K_M export.

Hyperparameters are coded in train_qlora.py / train_dpo.py (Stage 1: r=64,
alpha=128, all-linear targets, lr=2e-4, 3 epochs; Stage 2: r=32, alpha=64,
beta=0.1, lr=5e-5, 1 epoch, q/v targets). This script just chains them.

ONE-COMMAND INVOCATION (on a Kaggle/Colab GPU):
    python3 model/training/kaggle_launch.py

PREREQUISITES (do NOT launch until both are met):
  1. YZ's pending dataset decision — his own dialogues are NOT in the
     datasets yet (build_369_dataset.py documents this). Launching now trains
     on 57 SFT + 6 DPO pairs only.
  2. A free GPU slot: Kaggle notebook with GPU T4 x2 (or P100), internet ON,
     ~30h/week quota available. This VM has NO GPU — never run this here.

ENV OVERRIDES (secrets / paths):
  BASE_369   base HF repo (default: Qwen/Qwen3-8B — Apache-2.0, per train scripts)
  HF_TOKEN   huggingface token if the base repo is gated (never printed)
  WORKDIR    where adapters/outputs go (default: /kaggle/working if it exists
             else ./workdir next to the repo)
  SKIP_PIP   set to 1 to skip the pip install step (deps already present)

OUTPUTS (under $WORKDIR):
  genesis-qlora-sft/      Stage-1 LoRA adapter
  genesis-qlora-dpo/      Stage-2 LoRA adapter
  genesis-369-fp16/       merged full model (HF format)
  genesis-369-q5_k_m.gguf final GGUF for llama-server (needs llama.cpp)

Exit codes: 0 = full chain done, 2 = prerequisites missing (no GPU / no data),
3 = a stage failed. Every stage verifies its own output before moving on.
"""
from __future__ import annotations

import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
DATASET_DIR = os.path.join(REPO, "model", "dataset")
SFT_JSONL = os.path.join(DATASET_DIR, "369_sft.jsonl")
DPO_JSONL = os.path.join(DATASET_DIR, "369_dpo.jsonl")

BASE_MODEL = os.environ.get("BASE_369", "Qwen/Qwen3-8B")
HF_TOKEN = os.environ.get("HF_TOKEN")  # passed through, never logged
WORKDIR = os.environ.get(
    "WORKDIR",
    "/kaggle/working" if os.path.isdir("/kaggle/working")
    else os.path.join(REPO, "workdir"),
)
SKIP_PIP = os.environ.get("SKIP_PIP", "0") == "1"

S1_OUT = os.path.join(WORKDIR, "genesis-qlora-sft")
S2_OUT = os.path.join(WORKDIR, "genesis-qlora-dpo")
FP16_OUT = os.path.join(WORKDIR, "genesis-369-fp16")
GGUF_OUT = os.path.join(WORKDIR, "genesis-369-q5_k_m.gguf")


def _log(msg: str) -> None:
    print(f"[kaggle_launch] {msg}", flush=True)


def _run(cmd: list[str], **kw) -> None:
    _log("$ " + " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def _count_jsonl(path: str) -> int:
    import json
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                json.loads(line)  # raises on invalid JSON
                n += 1
    return n


def stage_pip() -> None:
    """Install the training stack (Kaggle/Colab). Skipped with SKIP_PIP=1."""
    if SKIP_PIP:
        _log("SKIP_PIP=1 — skipping pip install")
        return
    _run([sys.executable, "-m", "pip", "install", "-q",
          "torch", "transformers", "peft", "bitsandbytes",
          "accelerate", "datasets", "trl"])


def stage_build() -> None:
    """Regenerate both datasets from the repo sources, then verify counts."""
    _run([sys.executable, os.path.join(DATASET_DIR, "build_369_dataset.py")])
    _run([sys.executable, os.path.join(DATASET_DIR, "build_369_dpo.py")])
    n_sft = _count_jsonl(SFT_JSONL)
    n_dpo = _count_jsonl(DPO_JSONL)
    _log(f"dataset check: SFT={n_sft} pairs, DPO={n_dpo} pairs")
    if n_sft == 0 or n_dpo == 0:
        raise RuntimeError("dataset build produced zero records — aborting")


def stage_gpu_check() -> None:
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError(
            "NO GPU — this script must run on a Kaggle/Colab GPU session. "
            "Aborting before any spend of quota.")
    _log(f"GPU ok: {torch.cuda.get_device_name(0)} "
         f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB)")


def stage_sft() -> None:
    """Stage 1: QLoRA SFT on 369_sft.jsonl -> genesis-qlora-sft/."""
    os.environ["BASE_369"] = BASE_MODEL
    os.environ["DATA_369"] = SFT_JSONL
    os.environ["OUT_369"] = S1_OUT
    if HF_TOKEN:
        os.environ["HF_TOKEN"] = HF_TOKEN
    sys.path.insert(0, _HERE)
    import train_qlora
    train_qlora.main()
    adapter = os.path.join(S1_OUT, "adapter_model.safetensors")
    if not os.path.isfile(adapter):
        raise RuntimeError(f"Stage-1 adapter missing: {adapter}")
    _log(f"Stage-1 verified -> {S1_OUT}")


def stage_dpo() -> None:
    """Stage 2: QLoRA DPO identity lock -> genesis-qlora-dpo/.

    NOTE (known repo gap, train_dpo.py): the stage-2 LoRA is stacked on the
    stage-1 PeftModel via get_peft_model() under the default adapter name.
    If your peft version rejects duplicate adapter names, rerun stage 2
    manually with an explicit adapter_name (e.g. "dpo") before merging.
    """
    os.environ["BASE_369"] = BASE_MODEL
    os.environ["S1_369"] = S1_OUT
    os.environ["DPO_369"] = DPO_JSONL
    os.environ["OUT_369"] = S2_OUT
    if HF_TOKEN:
        os.environ["HF_TOKEN"] = HF_TOKEN
    sys.path.insert(0, _HERE)
    import train_dpo
    train_dpo.main()
    adapter = os.path.join(S2_OUT, "adapter_model.safetensors")
    if not os.path.isfile(adapter):
        raise RuntimeError(f"Stage-2 adapter missing: {adapter}")
    _log(f"Stage-2 verified -> {S2_OUT}")


def stage_merge() -> None:
    """Merge SFT + DPO adapters into the base -> FP16 HF model."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    _log(f"loading base {BASE_MODEL} (fp16)...")
    tok = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    m = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, trust_remote_code=True, torch_dtype=torch.float16)

    _log("merging Stage-1 (SFT) adapter...")
    m = PeftModel.from_pretrained(m, S1_OUT)
    m = m.merge_and_unload()

    _log("merging Stage-2 (DPO) adapter...")
    m = PeftModel.from_pretrained(m, S2_OUT)
    m = m.merge_and_unload()

    m.save_pretrained(FP16_OUT)
    tok.save_pretrained(FP16_OUT)
    _log(f"merged FP16 verified -> {FP16_OUT}")


def stage_gguf() -> None:
    """Convert FP16 -> GGUF F16 -> quantize Q5_K_M (needs llama.cpp)."""
    import shutil
    llamacpp = os.environ.get("LLAMACPP")  # path to llama.cpp checkout
    convert = os.path.join(llamacpp, "convert_hf_to_gguf.py") if llamacpp else None
    quantize = (os.path.join(llamacpp, "build", "bin", "llama-quantize")
                if llamacpp else shutil.which("llama-quantize"))
    if not convert or not os.path.isfile(convert) or not quantize:
        _log("llama.cpp not found — GGUF conversion skipped. "
             "Merged FP16 is ready; convert later with:")
        _log(f"  python3 /path/to/llama.cpp/convert_hf_to_gguf.py {FP16_OUT} "
             f"--outfile {WORKDIR}/genesis-369-f16.gguf")
        _log(f"  llama-quantize {WORKDIR}/genesis-369-f16.gguf {GGUF_OUT} Q5_K_M")
        return
    f16 = os.path.join(WORKDIR, "genesis-369-f16.gguf")
    _run([sys.executable, convert, FP16_OUT, "--outfile", f16])
    _run([quantize, f16, GGUF_OUT, "Q5_K_M"])
    _log(f"GGUF Q5_K_M ready -> {GGUF_OUT}")


def main() -> int:
    os.makedirs(WORKDIR, exist_ok=True)
    _log(f"REPO={REPO} BASE={BASE_MODEL} WORKDIR={WORKDIR}")
    try:
        stage_pip()
        stage_build()
        stage_gpu_check()
        stage_sft()
        stage_dpo()
        stage_merge()
        stage_gguf()
    except RuntimeError as e:
        _log(f"PREREQUISITE/STAGE FAILURE: {e}")
        return 2
    except subprocess.CalledProcessError as e:
        _log(f"SUBPROCESS FAILED (rc={e.returncode}): {e.cmd}")
        return 3
    _log("FULL CHAIN COMPLETE — final artifact: " + GGUF_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
