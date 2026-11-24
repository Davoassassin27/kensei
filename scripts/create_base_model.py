from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from _common import ROOT

PROMPT = ROOT / "prompts" / "kensei_system.md"
DEFAULT_MODEL_DIR = ROOT / "models"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crear el modelo Ollama 'kensei' a partir del base + system prompt (sin fine-tune)."
    )
    parser.add_argument("--base", default="qwen2.5-coder:7b", help="modelo Ollama base")
    parser.add_argument("--gguf", default=None, help="ruta a un GGUF local; reemplaza --base")
    parser.add_argument("--name", default="kensei")
    parser.add_argument("--prompt", default=str(PROMPT))
    parser.add_argument("--out-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--num-ctx", type=int, default=8192)
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out = out_dir / "Kensei.Base.Modelfile"
    source = args.base
    if args.gguf:
        gguf = Path(args.gguf).expanduser().resolve()
        if not gguf.exists():
            raise SystemExit(f"No existe el GGUF: {gguf}")
        # Ollama resuelve rutas relativas al directorio del Modelfile.
        if gguf.parent == out_dir:
            source = f"./{gguf.name}"
        else:
            source = gguf.as_posix()
        print(f"[gguf] {gguf} ({gguf.stat().st_size / 1e9:.2f} GB)")

    ollama = shutil.which("ollama")
    if not ollama:
        raise SystemExit("No encontré `ollama` en PATH. Instalalo o abrí Ollama Desktop.")
    prompt_path = Path(args.prompt)
    if not prompt_path.exists():
        raise SystemExit(f"No existe el prompt: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if '"""' in prompt:
        raise SystemExit("El prompt contiene triple comilla; no se puede embeber en el Modelfile.")

    out.parent.mkdir(parents=True, exist_ok=True)
    template_block = (
        'TEMPLATE """{{ if .System }}<|im_start|>system\n'
        "{{ .System }}<|im_end|>\n"
        "{{ end }}{{ if .Prompt }}<|im_start|>user\n"
        "{{ .Prompt }}<|im_end|>\n"
        "{{ end }}<|im_start|>assistant\n"
        '"""\n'
    )
    out.write_text(
        f"""# Kensei base (prompt-only, sin LoRA)
# Generado por scripts/create_base_model.py. No editar a mano.
FROM {source}

PARAMETER temperature {args.temperature}
PARAMETER top_p 0.9
PARAMETER num_ctx {args.num_ctx}
PARAMETER repeat_penalty 1.05
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|endoftext|>"

{template_block}
SYSTEM \"\"\"
{prompt}
\"\"\"
""",
        encoding="utf-8",
    )
    print(f"[modelfile] {out}")

    result = subprocess.run(
        [ollama, "create", args.name, "-f", str(out)],
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"`ollama create {args.name}` falló con código {result.returncode}")

    print(
        f"\nListo: `{args.name}` = {source} + prompt de Kensei (sin fine-tune).\n"
        f"  ollama run {args.name}\n"
        f"  uv run kensei doctor --model {args.name}\n"
        f"  uv run kensei ask \"¿Cómo listo los subvolúmenes Btrfs?\" --model {args.name}\n"
        "\nCuando tengas el adapter, `scripts/export_gguf.py` genera el Modelfile con el GGUF\n"
        "y `ollama create kensei -f modelfiles/Kensei.Modelfile` reemplaza este modelo.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
