from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
from pathlib import Path
from typing import Any

from _common import ROOT, read_jsonl

CONFIG = ROOT / "config" / "train_qlora.yaml"


def fail(message: str) -> None:
    print(f"[train] {message}", file=sys.stderr)
    raise SystemExit(2)


def import_training_stack() -> dict[str, Any]:
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        fail(
            "faltan dependencias de entrenamiento. En Linux:\n"
            "  uv pip install torch transformers datasets peft accelerate bitsandbytes trl\n"
            f"detalle: {exc}"
        )
    return {
        "torch": torch,
        "Dataset": Dataset,
        "LoraConfig": LoraConfig,
        "get_peft_model": get_peft_model,
        "prepare_model_for_kbit_training": prepare_model_for_kbit_training,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "BitsAndBytesConfig": BitsAndBytesConfig,
        "Trainer": Trainer,
        "TrainingArguments": TrainingArguments,
    }


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Uniformar el protocolo textual para cualquier tokenizer.

    Qwen2.5 envuelve los mensajes ``tool`` en ``<tool_response>``; si el
    tokenizer no soporta ese rol, lo convertimos a un user con el mismo texto.
    """
    result: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if role == "tool":
            result.append({"role": "user", "content": f"<tool_response>\n{content}\n</tool_response>"})
        elif role in {"system", "user", "assistant"}:
            result.append({"role": role, "content": content})
        else:
            raise ValueError(f"rol inválido en el dataset: {role!r}")
    return result


def encode_example(
    tokenizer: Any,
    messages: list[dict[str, Any]],
    max_seq_length: int,
) -> dict[str, list[int]] | None:
    messages = normalize_messages(messages)
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    input_ids = tokenizer(text, add_special_tokens=False).input_ids
    labels = [-100] * len(input_ids)

    # Marcar solo los turnos del assistant. El template de Qwen es estable
    # respecto del prefijo, así que los offsets de tokens coinciden.
    for index, message in enumerate(messages):
        if message["role"] != "assistant":
            continue
        prefix = tokenizer.apply_chat_template(
            messages[:index], tokenize=False, add_generation_prompt=False
        ) if index else ""
        upto = tokenizer.apply_chat_template(
            messages[: index + 1], tokenize=False, add_generation_prompt=False
        )
        start = len(tokenizer(prefix, add_special_tokens=False).input_ids) if prefix else 0
        end = len(tokenizer(upto, add_special_tokens=False).input_ids)
        for position in range(start, min(end, len(input_ids))):
            labels[position] = input_ids[position]

    if len(input_ids) > max_seq_length:
        input_ids = input_ids[:max_seq_length]
        labels = labels[:max_seq_length]
    if not input_ids:
        return None
    if all(label == -100 for label in labels):
        # Fallback: no pudimos aislar el assistant; entrenar la secuencia completa.
        labels = list(input_ids)
    return {"input_ids": input_ids, "labels": labels}


class TokenizedDataset:
    def __init__(self, rows: list[dict[str, list[int]]]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.rows[index]


class CausalCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
        import torch

        max_len = max(len(feature["input_ids"]) for feature in features)
        max_len = int(math.ceil(max_len / 8) * 8)
        input_ids = []
        labels = []
        attention_mask = []
        for feature in features:
            ids = list(feature["input_ids"])
            labs = list(feature["labels"])
            pad = max_len - len(ids)
            input_ids.append(ids + [self.pad_token_id] * pad)
            labels.append(labs + [-100] * pad)
            attention_mask.append([1] * len(ids) + [0] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
        }


def training_argument_kwargs(TrainingArguments: Any, base: dict[str, Any]) -> dict[str, Any]:
    params = inspect.signature(TrainingArguments.__init__).parameters
    if "eval_strategy" in params:
        base["eval_strategy"] = base.pop("evaluation_strategy", "no")
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="Entrenar el LoRA de Kensei con QLoRA.")
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--val-dataset", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--base-model", default=None)
    parser.add_argument("--max-seq-length", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=-1, help="para smoke tests")
    parser.add_argument("--check-only", action="store_true", help="tokenizar y validar sin cargar el modelo")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="limitar ejemplos (debug)")
    args = parser.parse_args()

    import yaml

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        fail(f"{args.config}: configuración inválida")

    base_model = args.base_model or config["base_model"]
    dataset_path = Path(args.dataset or config["dataset"])
    if not dataset_path.is_absolute():
        dataset_path = ROOT / dataset_path
    val_raw = args.val_dataset or config.get("val_dataset")
    val_path = Path(val_raw) if val_raw else None
    if val_path is not None and not val_path.is_absolute():
        val_path = ROOT / val_path
    output_dir = Path(args.output_dir or config.get("output_dir", "models/kensei-lora"))
    max_seq_length = int(args.max_seq_length or config.get("max_seq_length", 4096))
    lora_cfg = config.get("lora", {})
    train_cfg = config.get("training", {})

    if not dataset_path.exists():
        fail(f"no existe el dataset {dataset_path}; corré build_sft.py")
    rows = list(read_jsonl(dataset_path))
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        fail(f"{dataset_path} está vacío")
    val_rows = list(read_jsonl(val_path)) if val_path and val_path.exists() else []
    if args.limit:
        val_rows = val_rows[: max(1, args.limit // 10)]

    print(f"[train] base={base_model}")
    print(f"[train] train={len(rows)} val={len(val_rows)} max_seq={max_seq_length}")
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir

    if args.check_only:
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            fail(
                "para --check-only alcanza con transformers:\n"
                "  uv pip install transformers\n"
                f"detalle: {exc}"
            )
    else:
        stack = import_training_stack()
        torch = stack["torch"]
        AutoTokenizer = stack["AutoTokenizer"]

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    if args.check_only:
        lengths: list[int] = []
        assistant_tokens = 0
        total_tokens = 0
        for row in rows:
            encoded = encode_example(tokenizer, row["messages"], max_seq_length)
            if encoded is None:
                continue
            lengths.append(len(encoded["input_ids"]))
            assistant_tokens += sum(1 for label in encoded["labels"] if label != -100)
            total_tokens += len(encoded["input_ids"])
        if not lengths:
            fail("ningún ejemplo se pudo tokenizar")
        lengths.sort()
        print(
            json.dumps(
                {
                    "examples": len(lengths),
                    "tokens": {
                        "avg": round(sum(lengths) / len(lengths), 1),
                        "max": lengths[-1],
                        "p95": lengths[int(len(lengths) * 0.95)],
                    },
                    "assistant_token_ratio": round(assistant_tokens / max(1, total_tokens), 3),
                    "truncated_at": max_seq_length,
                },
                indent=2,
            )
        )
        return 0

    if not torch.cuda.is_available():
        fail(
            "no hay GPU CUDA/ROCm visible. Un 7B en QLoRA no se entrena en CPU.\n"
            "Opciones: usar una GPU >= 16 GB, alquilar una cloud, o probar el 1.5B."
        )
    print(f"[train] GPU: {torch.cuda.get_device_name(0)}")

    encoded_rows = []
    skipped = 0
    for row in rows:
        encoded = encode_example(tokenizer, row["messages"], max_seq_length)
        if encoded is None:
            skipped += 1
            continue
        encoded_rows.append(encoded)
    encoded_val = []
    for row in val_rows:
        encoded = encode_example(tokenizer, row["messages"], max_seq_length)
        if encoded is not None:
            encoded_val.append(encoded)
    if skipped:
        print(f"[train] {skipped} ejemplos descartados por tokenización")
    if not encoded_rows:
        fail("no quedaron ejemplos tokenizados")

    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    bnb_config = stack["BitsAndBytesConfig"](
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )
    model = stack["AutoModelForCausalLM"].from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        torch_dtype=compute_dtype,
        trust_remote_code=False,
    )
    model.config.use_cache = False
    model = stack["prepare_model_for_kbit_training"](model, use_gradient_checkpointing=True)

    peft_config = stack["LoraConfig"](
        r=int(lora_cfg.get("r", 32)),
        lora_alpha=int(lora_cfg.get("alpha", 64)),
        lora_dropout=float(lora_cfg.get("dropout", 0.05)),
        bias=str(lora_cfg.get("bias", "none")),
        task_type="CAUSAL_LM",
        target_modules=list(lora_cfg.get("target_modules", [])),
        use_rslora=bool(lora_cfg.get("use_rslora", True)),
        use_dora=bool(lora_cfg.get("use_dora", False)),
        init_lora_weights=lora_cfg.get("init_lora_weights", True),
    )
    model = stack["get_peft_model"](model, peft_config)
    model.print_trainable_parameters()

    optim = str(train_cfg.get("optim", "adamw_8bit"))
    try:
        import bitsandbytes  # noqa: F401
    except ImportError:
        if optim == "adamw_8bit":
            print("[train] bitsandbytes no disponible; uso adamw_torch")
            optim = "adamw_torch"

    evaluation = "steps" if encoded_val else "no"
    base_args = {
        "output_dir": str(output_dir),
        "num_train_epochs": float(train_cfg.get("epochs", 2)),
        "per_device_train_batch_size": int(train_cfg.get("batch_size", 2)),
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": int(train_cfg.get("gradient_accumulation_steps", 8)),
        "learning_rate": float(train_cfg.get("learning_rate", 1e-4)),
        "warmup_ratio": float(train_cfg.get("warmup_ratio", 0.03)),
        "weight_decay": float(train_cfg.get("weight_decay", 0.01)),
        "lr_scheduler_type": str(train_cfg.get("lr_scheduler_type", "cosine")),
        "logging_steps": int(train_cfg.get("logging_steps", 10)),
        "save_steps": int(train_cfg.get("save_steps", 200)),
        "save_total_limit": int(train_cfg.get("save_total_limit", 2)),
        "evaluation_strategy": evaluation,
        "eval_steps": int(train_cfg.get("save_steps", 200)),
        "optim": optim,
        "bf16": compute_dtype == torch.bfloat16,
        "fp16": compute_dtype == torch.float16,
        "gradient_checkpointing": True,
        "gradient_checkpointing_kwargs": {"use_reentrant": False},
        "report_to": [],
        "remove_unused_columns": False,
        "seed": int(train_cfg.get("seed", 3407)),
        "data_seed": int(train_cfg.get("seed", 3407)),
        "dataloader_pin_memory": True,
        "save_safetensors": True,
    }
    if args.max_steps and args.max_steps > 0:
        base_args["max_steps"] = args.max_steps
        base_args["num_train_epochs"] = 1
    training_args = stack["TrainingArguments"](
        **training_argument_kwargs(stack["TrainingArguments"], base_args)
    )

    trainer = stack["Trainer"](
        model=model,
        args=training_args,
        train_dataset=TokenizedDataset(encoded_rows),
        eval_dataset=TokenizedDataset(encoded_val) if encoded_val else None,
        data_collator=CausalCollator(int(tokenizer.pad_token_id)),
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[train] salida: {output_dir}")
    trainer.train(resume_from_checkpoint=args.resume or None)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    metadata = {
        "base_model": base_model,
        "dataset": str(dataset_path),
        "examples": len(encoded_rows),
        "val_examples": len(encoded_val),
        "max_seq_length": max_seq_length,
        "lora": lora_cfg,
        "training": train_cfg,
        "gpu": torch.cuda.get_device_name(0),
    }
    (output_dir / "kensei_train_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[train] listo. Próximo paso: scripts/export_gguf.py --adapter", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
