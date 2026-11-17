#!/usr/bin/env python3
"""
GBOC - Treino LoRA do modelo de diagnóstico (rodar numa máquina com GPU NVIDIA, NÃO no servidor de backup).

Entrada : dataset gerado pelo GBOC Agent (Tela "IA: Conhecimento, MCP e Treino" → Fine-tuning → Gerar dataset)
          arquivos gboc_diag_AAAAMMDD_HHMMSS.train.jsonl (e .val.jsonl, quando houver).
Saída   : pasta --out com
            • adapter/         adapter LoRA (safetensors)
            • gguf/*.gguf      modelo completo quantizado para o Ollama (--export-gguf)

Requisitos (máquina de treino):
    pip install "unsloth" "trl>=0.12" "datasets"
    GPU NVIDIA com 8 GB+ de VRAM para modelos de 3B em 4 bits (16 GB+ para 7B/8B).

Exemplos:
    python train_lora_gboc.py --train gboc_diag_20261110_150000.train.jsonl --out saida_gboc --export-gguf
    python train_lora_gboc.py --train X.train.jsonl --val X.val.jsonl --base unsloth/Qwen2.5-7B-Instruct-bnb-4bit --epochs 3

Depois, no GBOC Agent: Fine-tuning → Importar no Ollama → caminho do .gguf gerado (copie o arquivo para o servidor
do Agente ou para uma pasta acessível a ele).
"""

import argparse
import json
import sys
from pathlib import Path


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            msgs = obj.get("messages")
            if not isinstance(msgs, list) or len(msgs) < 2:
                raise ValueError(f"{path}:{i} sem 'messages' válido")
            rows.append(obj)
    return rows


def main():
    ap = argparse.ArgumentParser(description="Treino LoRA do diagnóstico GBOC (Unsloth)")
    ap.add_argument("--train", required=True)
    ap.add_argument("--val")
    ap.add_argument("--base", default="unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
                    help="Modelo base (Hugging Face). Use o mesmo da família que roda no seu Ollama.")
    ap.add_argument("--out", default="gboc_lora_out")
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--max-seq", type=int, default=2048)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--export-gguf", action="store_true", help="Exporta modelo completo .gguf para o Ollama")
    ap.add_argument("--quant", default="q4_k_m", help="Quantização do GGUF (q4_k_m, q5_k_m, q8_0, f16)")
    args = ap.parse_args()

    train_rows = load_jsonl(args.train)
    val_rows = load_jsonl(args.val) if args.val else []
    print(f"Exemplos: treino={len(train_rows)} validação={len(val_rows)}")
    if len(train_rows) < 30:
        print("⚠️  Menos de 30 exemplos: o modelo tende a decorar os casos. Valide mais diagnósticos antes, se possível.")

    try:
        from unsloth import FastLanguageModel
        from unsloth.chat_templates import train_on_responses_only
        from datasets import Dataset
        from trl import SFTConfig, SFTTrainer
    except ImportError as e:
        sys.exit(f"Dependências ausentes ({e}). Instale: pip install unsloth trl datasets")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base, max_seq_length=args.max_seq, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=42)

    def fmt(rows):
        return Dataset.from_list([{"text": tokenizer.apply_chat_template(r["messages"], tokenize=False)} for r in rows])

    train_ds = fmt(train_rows)
    val_ds = fmt(val_rows) if val_rows else None
    out = Path(args.out)
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=train_ds, eval_dataset=val_ds,
        args=SFTConfig(
            output_dir=str(out / "checkpoints"), dataset_text_field="text", max_seq_length=args.max_seq,
            per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs, learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.05,
            logging_steps=5, save_strategy="no", eval_strategy="epoch" if val_ds is not None else "no",
            seed=42, report_to="none"),
    )
    # treina só nas respostas do assistente (não no prompt)
    try:
        trainer = train_on_responses_only(trainer)
    except Exception as e:
        print(f"(aviso) train_on_responses_only indisponível para este template: {e}")
    trainer.train()

    adapter_dir = out / "adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"✅ Adapter LoRA salvo em {adapter_dir}")

    if args.export_gguf:
        gguf_dir = out / "gguf"
        model.save_pretrained_gguf(str(gguf_dir), tokenizer, quantization_method=args.quant)
        files = sorted(gguf_dir.glob("*.gguf"))
        print("✅ GGUF gerado:", *[f"  {f}" for f in files], sep="\n")
        print("Importe no GBOC Agent: IA → Fine-tuning → Importar no Ollama → tipo 'Modelo completo (.gguf)'.")


if __name__ == "__main__":
    main()
