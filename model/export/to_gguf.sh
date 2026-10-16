#!/bin/bash
# to_gguf.sh — Stage 3: merge LoRA adapters into the base model, quantize to
# GGUF Q5_K_M for llama-server. Run where llama.cpp is built.
# Usage: ./to_gguf.sh <base_model_dir> <sft_adapter> <dpo_adapter> <out_dir>
set -e
BASE="${1:?base model dir}"; SFT="${2:?sft adapter}"; DPO="${3:?dpo adapter}"
OUT="${4:?output dir}"
mkdir -p "$OUT"
python3 - "$BASE" "$SFT" "$DPO" "$OUT" << 'EOF'
import sys, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
base, sft, dpo, out = sys.argv[1:5]
tok = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
m = AutoModelForCausalLM.from_pretrained(base, trust_remote_code=True,
                                         torch_dtype=torch.float16)
m = PeftModel.from_pretrained(m, sft); m = m.merge_and_unload()
m = PeftModel.from_pretrained(m, dpo); m = m.merge_and_unload()
m.save_pretrained(f"{out}/genesis-369-fp16"); tok.save_pretrained(f"{out}/genesis-369-fp16")
print("merged ->", out + "/genesis-369-fp16")
EOF
# convert to GGUF then quantize (needs llama.cpp built with convert_hf_to_gguf.py)
# python3 /path/to/llama.cpp/convert_hf_to_gguf.py "$OUT/genesis-369-fp16" --outfile "$OUT/genesis-369-f16.gguf"
# /path/to/llama.cpp/build/bin/llama-quantize "$OUT/genesis-369-f16.gguf" "$OUT/genesis-369-q5_k_m.gguf" Q5_K_M
echo "merged FP16 ready. Convert + quantize with llama.cpp (see commented lines)."
