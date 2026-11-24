from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from _common import ROOT, estimate_tokens, read_jsonl

from kensei.protocol import TOOL_NAMES, parse_tool_calls

OUT = ROOT / "data" / "derived"
REPORTS = ROOT / "reports"
KNOWN_LICENSES = {
    "GFDL-1.3-or-later",
    "CC-BY-NC-4.0",
    "CC-BY-4.0",
    "GPL-3.0-only",
    "MIT",
    "Apache-2.0",
}
VALID_ROLES = {"system", "user", "assistant", "tool"}


def message_text(row: dict[str, Any]) -> str:
    return "\n".join(str(message.get("content", "")) for message in row.get("messages", []))


def example_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(message_text(row).encode("utf-8")).hexdigest()


def validate_row(index: int, row: dict[str, Any], max_tokens: int) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {"tokens": 0, "source": "unknown", "kind": "unknown"}

    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        errors.append("messages debe ser una lista con al menos system/user/assistant")
        return errors, warnings, info

    roles = [str(message.get("role", "")) for message in messages if isinstance(message, dict)]
    if len(roles) != len(messages):
        errors.append("todos los mensajes deben ser objetos")
        return errors, warnings, info
    if roles[0] != "system":
        errors.append("el primer mensaje debe ser system")
    if roles[1] != "user":
        errors.append("el segundo mensaje debe ser user")
    if roles[-1] != "assistant":
        errors.append("el último mensaje debe ser assistant")
    unknown_roles = sorted(set(roles) - VALID_ROLES)
    if unknown_roles:
        errors.append(f"roles inválidos: {unknown_roles}")

    for position, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append(f"mensaje {position} ({message.get('role')}) vacío")
            continue
        if message.get("role") == "assistant" and "<tool_call>" in content:
            calls = parse_tool_calls(content)
            if not calls:
                errors.append(f"mensaje {position}: <tool_call> sin bloque parseable")
            for call in calls:
                if call.error:
                    errors.append(f"mensaje {position}: tool-call inválido: {call.error}")
                elif call.name not in TOOL_NAMES:
                    errors.append(f"mensaje {position}: herramienta desconocida {call.name!r}")

    text = message_text(row)
    info["tokens"] = estimate_tokens(text)
    if info["tokens"] > max_tokens:
        errors.append(f"ejemplo demasiado largo: ~{info['tokens']} tokens > {max_tokens}")

    assistant_chars = sum(
        len(str(message.get("content", ""))) for message in messages if message.get("role") == "assistant"
    )
    if assistant_chars < 40:
        warnings.append("respuesta del assistant muy corta")

    meta = row.get("meta")
    if not isinstance(meta, dict):
        warnings.append("sin bloque meta")
        meta = {}
    info["source"] = str(meta.get("source", "unknown"))
    info["kind"] = str(meta.get("kind", "unknown"))
    license_name = meta.get("license")
    if license_name and license_name not in KNOWN_LICENSES:
        warnings.append(f"licencia no reconocida: {license_name}")
    if not license_name and not info["source"].startswith(("manual", "synthetic")):
        warnings.append("sin licencia declarada")

    return errors, warnings, info


def main() -> int:
    parser = argparse.ArgumentParser(description="Validar el dataset SFT de Kensei.")
    parser.add_argument("datasets", nargs="*", default=None, help="JSONL a validar (default: train + val)")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--min-examples", type=int, default=50)
    parser.add_argument("--max-source-share", type=float, default=0.7)
    parser.add_argument("--strict", action="store_true", help="los warnings también fallan")
    parser.add_argument("--report", default=str(REPORTS / "dataset-validation.json"))
    args = parser.parse_args()

    paths = [Path(p) for p in (args.datasets or [OUT / "sft.jsonl", OUT / "sft.val.jsonl"])]
    existing = [path for path in paths if path.exists()]
    if not existing:
        print("No hay datasets para validar. Corré build_sft.py primero.", file=sys.stderr)
        return 2

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    hashes: dict[str, int] = {}
    duplicates: list[str] = []
    sources: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    token_counts: list[int] = []
    total = 0

    for path in existing:
        per_file = 0
        for index, row in enumerate(read_jsonl(path)):
            total += 1
            per_file += 1
            row_errors, row_warnings, info = validate_row(index, row, args.max_tokens)
            token_counts.append(int(info["tokens"]))
            sources[str(info["source"])] += 1
            kinds[str(info["kind"])] += 1
            where = f"{path.name}:{index + 1}"
            for message in row_errors:
                errors.append({"where": where, "message": message})
            for message in row_warnings:
                warnings.append({"where": where, "message": message})

            digest = example_hash(row)
            if digest in hashes:
                duplicates.append(where)
            else:
                hashes[digest] = index
        print(f"[{path.name}] {per_file} ejemplos")

    if total < args.min_examples:
        errors.append(
            {
                "where": "dataset",
                "message": f"solo {total} ejemplos; mínimo {args.min_examples}",
            }
        )

    if duplicates:
        warnings.append(
            {
                "where": "dataset",
                "message": f"{len(duplicates)} duplicados exactos (el dedupe de build_sft debería eliminarlos)",
            }
        )

    if total:
        top_source, top_count = sources.most_common(1)[0]
        share = top_count / total
        if share > args.max_source_share:
            warnings.append(
                {
                    "where": "dataset",
                    "message": f"desbalance: {top_source} = {share:.0%} del dataset (máx {args.max_source_share:.0%})",
                }
            )
        if "manual:safety" not in sources:
            warnings.append({"where": "dataset", "message": "faltan ejemplos manuales de seguridad"})
        if "tool-trace" not in kinds:
            warnings.append({"where": "dataset", "message": "faltan tool-traces"})

    report = {
        "dataset": [str(path) for path in existing],
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "duplicate_locations": duplicates[:50],
        "sources": dict(sources.most_common()),
        "kinds": dict(kinds.most_common()),
        "tokens": {
            "avg": round(sum(token_counts) / len(token_counts), 1) if token_counts else 0,
            "max": max(token_counts) if token_counts else 0,
            "p95": sorted(token_counts)[int(len(token_counts) * 0.95)] if token_counts else 0,
        },
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in report.items() if k != "warnings"}, ensure_ascii=False, indent=2))
    if warnings:
        print(f"\n{len(warnings)} warnings:")
        for item in warnings[:30]:
            print(f"  WARN {item['where']}: {item['message']}")
    if errors:
        print(f"\n{len(errors)} errores:")
        for item in errors[:40]:
            print(f"  FAIL {item['where']}: {item['message']}")
        return 1
    if args.strict and warnings:
        print("\nModo strict: los warnings fallan.")
        return 1

    print(f"\nDataset válido: {total} ejemplos. Reporte: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
