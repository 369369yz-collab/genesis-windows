"""train_dpo.py — Stage 2: QLoRA DPO (identity lock).

After Stage 1 (knowledge + tone), DPO teaches the model what it must NEVER
break: honesty, Persian-always, daughter-voice, the laws. Reference model
frozen in 4-bit. Dossier spec: r=32, alpha=64, beta=0.1.

Input: 369_dpo.jsonl — {"prompt": [...messages...], "chosen": "...",
"rejected": "..."}. Build it with dataset/build_369_dpo.py (pairs where the
'rejected' violates a law and 'chosen' honors it).

FREE path: same Kaggle setup as Stage 1. Output: ./genesis-qlora-dpo/.
"""
import os

BASE_MODEL = os.environ.get("BASE_369", "Qwen/Qwen3-8B")
ADAPTER_S1 = os.environ.get("S1_369", "./genesis-qlora-sft")
DATA = os.environ.get("DPO_369", "369_dpo.jsonl")
OUT = os.environ.get("OUT_369", "./genesis-qlora-dpo")


def main():
    import torch
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, PeftModel, prepare_model_for_kbit_training
    from trl import DPOTrainer, DPOConfig

    tok = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, trust_remote_code=True, load_in_4bit=True,
        bnb_4bit_quant_type="nf4", torch_dtype=torch.bfloat16,
        device_map="auto")
    model = prepare_model_for_kbit_training(model)
    model = PeftModel.from_pretrained(model, ADAPTER_S1, is_trainable=True)

    # fresh small adapter for the DPO stage (dossier: r=32, alpha=64)
    from peft import get_peft_model
    dpo_cfg = LoraConfig(r=32, lora_alpha=64,
                         target_modules=["q_proj", "v_proj"],
                         lora_dropout=0.05, bias="none",
                         task_type="CAUSAL_LM")
    model = get_peft_model(model, dpo_cfg)

    ds = load_dataset("json", data_files=DATA)["train"]

    args = DPOConfig(
        output_dir=OUT, beta=0.1,
        per_device_train_batch_size=2, gradient_accumulation_steps=8,
        learning_rate=5e-5, num_train_epochs=1,
        logging_steps=10, save_steps=100, save_total_limit=2,
        bf16=True, optim="paged_adamw_8bit", report_to="none",
    )
    DPOTrainer(model=model, ref_model=None, args=args,
               train_dataset=ds, tokenizer=tok).train()
    model.save_pretrained(OUT)
    print(f"Stage-2 adapter saved -> {OUT}")


if __name__ == "__main__":
    main()
