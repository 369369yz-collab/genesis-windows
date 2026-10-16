"""train_qlora.py — Stage 1: QLoRA SFT for the 369-exclusive model.

FREE path: run on Kaggle (30h/week free GPU) — no spend, no YZ hardware.
  1. Kaggle: new notebook, GPU T4 x2 (or P100), internet ON.
  2. Upload model/dataset/369_sft.jsonl as a dataset (or paste it).
  3. pip install -q transformers peft bitsandbytes accelerate datasets
  4. Run this script. Output: ./genesis-qlora-sft/ (LoRA adapter).

Per the research dossier: r=64, alpha=128, all-linear targets, 4-bit base.
~7.5GB VRAM — fits Kaggle's free T4 (16GB).

Base model: Qwen3 8B-class Apache-2.0 (set BASE_MODEL below to the exact
8B base chosen at training time).
"""
import os

BASE_MODEL = os.environ.get("BASE_369", "Qwen/Qwen3-8B")
DATA = os.environ.get("DATA_369", "369_sft.jsonl")
OUT = os.environ.get("OUT_369", "./genesis-qlora-sft")

# --- imports are inside main() so --help-style inspection never needs GPU ---

def main():
    import torch
    from datasets import load_dataset
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              TrainingArguments)
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, trust_remote_code=True,
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    model = prepare_model_for_kbit_training(model)

    # all-linear targets (dossier spec)
    target = ["q_proj", "k_proj", "v_proj", "o_proj",
              "gate_proj", "up_proj", "down_proj"]
    lora = LoraConfig(r=64, lora_alpha=128, target_modules=target,
                      lora_dropout=0.05, bias="none",
                      task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)

    ds = load_dataset("json", data_files=DATA)["train"]

    def _fmt(ex):
        parts = []
        for m in ex["messages"]:
            parts.append(f"<|{m['role']}|>\n{m['content']}")
        return {"text": "\n".join(parts) + "\n<|assistant|>\n"}

    ds = ds.map(_fmt, remove_columns=ds.column_names)

    args = TrainingArguments(
        output_dir=OUT,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        num_train_epochs=3,
        logging_steps=10,
        save_steps=100,
        save_total_limit=2,
        bf16=True,
        optim="paged_adamw_8bit",
        report_to="none",
    )
    SFTTrainer(model=model, train_dataset=ds, args=args,
               dataset_text_field="text").train()
    model.save_pretrained(OUT)
    print(f"Stage-1 adapter saved -> {OUT}")


if __name__ == "__main__":
    main()
