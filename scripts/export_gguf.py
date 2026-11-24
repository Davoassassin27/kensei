from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _common import ROOT

MODELFILE = ROOT / "modelfiles" / "Kensei.Modelfile"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(str(part) for part in command))
    result = subprocess.run([str(part) for part in command], check=False, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        raise SystemExit(f"falló: {' '.join(str(part) for part in command)}")


def find_convert(llama_cpp: Path) -> Path:
    candidates = [
        llama_cpp / "convert_hf_to_gguf.py",
        llama_cpp / "gguf-py" / "scripts" / "convert_hf_to_gguf.py",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit(
        f"No encontré convert_hf_to_gguf.py en {llama_cpp}.\n"
        "Cloná llama.cpp: git clone https://github.com/ggml-org/llama.cpp ~/src/llama.cpp"
    )


def find_quantize(llama_cpp: Path) -> Path:
    candidates = [
        llama_cpp / "build" / "bin" / "llama-quantize",
        llama_cpp / "build" / "bin" / "llama-quantize.exe",
        llama_cpp / "build" / "bin" / "quantize",
        llama_cpp / "build" / "bin" / "quantize.exe",
        llama_cpp / "llama-quantize",
    ]
    for path in candidates:
        if path.exists():
            return path
    which = shutil.which("llama-quantize")
    if which:
        return Path(which)
    raise SystemExit(
        "No encontré llama-quantize. Compilá llama.cpp:\n"
        "  cmake -B build -DGGML_NATIVE=ON && cmake --build build -j\n"
        "o pasá --llama-cpp /ruta/a/llama.cpp"
    )


def merge_adapter(adapter: Path, base_model: str, merged: Path) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(
            "faltan dependencias para mergear el adapter: uv pip install torch transformers peft accelerate\n"
            f"detalle: {exc}"
        )

    if not adapter.exists():
        raise SystemExit(f"no existe el adapter: {adapter}")
    merged.mkdir(parents=True, exist_ok=True)

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    print(f"[merge] base={base_model} adapter={adapter} dtype={dtype}")
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=dtype,
        device_map="cpu",
        trust_remote_code=False,
    )
    model = PeftModel.from_pretrained(base, str(adapter))
    model = model.merge_and_unload()
    model.save_pretrained(str(merged), safe_serialization=True, max_shard_size="5GB")

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False)
    tokenizer.save_pretrained(str(merged))
    print(f"[merge] modelo mergeado en {merged}")


def write_modelfile(gguf: Path, system_prompt: Path) -> Path:
    relative = os.path.relpath(gguf, MODELFILE.parent).replace("\\", "/")
    system = system_prompt.read_text(encoding="utf-8").strip() if system_prompt.exists() else ""
    content = f"""# Kensei — modelo local de Ronin
FROM ./{relative}

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 8192
PARAMETER repeat_penalty 1.05
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"
"""
    if system:
        content += f'\nSYSTEM """\n{system}\n"""\n'
    MODELFILE.parent.mkdir(parents=True, exist_ok=True)
    MODELFILE.write_text(content, encoding="utf-8")
    print(f"[modelfile] {MODELFILE}")
    return MODELFILE


def main() -> int:
    parser = argparse.ArgumentParser(description="Mergear el LoRA de Kensei y exportar GGUF para Ollama.")
    parser.add_argument("--adapter", default=str(ROOT / "models" / "kensei-qwen2.5-coder-7b-lora"))
    parser.add_argument("--base-model", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    parser.add_argument("--merged", default=str(ROOT / "models" / "kensei-merged"))
    parser.add_argument("--gguf", default=str(ROOT / "models" / "kensei-f16.gguf"))
    parser.add_argument("--quant", default="Q4_K_M", help="Q4_K_M, Q5_K_M, Q8_0, … (vacío = no cuantizar)")
    parser.add_argument("--skip-merge", action="store_true", help="usar --merged ya existente")
    parser.add_argument("--llama-cpp", default=os.environ.get("LLAMA_CPP_DIR", str(Path.home() / "src" / "llama.cpp")))
    parser.add_argument("--no-modelfile", action="store_true")
    args = parser.parse_args()

    merged = Path(args.merged).expanduser().resolve()
    gguf = Path(args.gguf).expanduser().resolve()
    llama_cpp = Path(args.llama_cpp).expanduser().resolve()

    if not args.skip_merge:
        merge_adapter(Path(args.adapter).expanduser().resolve(), args.base_model, merged)
    elif not merged.exists():
        raise SystemExit(f"--skip-merge pero no existe {merged}")

    gguf.parent.mkdir(parents=True, exist_ok=True)
    convert = find_convert(llama_cpp)
    run([sys.executable, str(convert), str(merged), "--outfile", str(gguf), "--outtype", "f16"])

    final = gguf
    if args.quant:
        quantize = find_quantize(llama_cpp)
        final = gguf.with_name(f"kensei-{args.quant}.gguf")
        run([str(quantize), str(gguf), str(final), args.quant])
        print(f"[quant] {final} ({final.stat().st_size / 1e9:.2f} GB)")

    if not args.no_modelfile:
        write_modelfile(final, ROOT / "prompts" / "kensei_system.md")

    print(
        "\nListo. Para servir en Ollama:\n"
        f"  cd {ROOT}\n"
        "  ollama create kensei -f modelfiles/Kensei.Modelfile\n"
        "  ollama run kensei\n"
        "  uv run kensei doctor --model kensei\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
