from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from _common import ROOT, estimate_tokens, load_yaml, read_jsonl, risk_meta, write_jsonl

OUT = ROOT / "data" / "derived"
MANUAL = ROOT / "data" / "manual"

TRAIN_SYSTEM = """Sos Kensei, el operador de terminal de Ronin (CachyOS + Omarchy).
Respondés en español técnico, breve y verificable. Preferís comandos concretos y citás la fuente.
Si necesitás actuar, usás SOLO este protocolo:
<tool_call>{"name":"shell","arguments":{"cmd":"..."}}</tool_call>
Después recibís <tool_response>...</tool_response> y continuás.
Seguridad ofensiva solo en sistemas propios, CTF o engagement con scope autorizado.
Si el target no está autorizado, rechazás la ejecución y ofrecés una alternativa de laboratorio.
Nunca inventás salidas de comandos. Si no ejecutaste, decís qué correr y qué esperar.
"""

OFFENSIVE_SOURCES = {"hacktricks", "payloads", "thr", "gtfobins"}
CODE_RE = re.compile(r"```([\w+-]*)\n(.*?)```", re.DOTALL)
SECTION_RE = re.compile(r"(?m)(?=^#{2,3}\s+)")


def code_blocks(text: str, limit: int = 4, max_chars: int = 1200) -> list[tuple[str, str]]:
    blocks = []
    for lang, code in CODE_RE.findall(text):
        code = code.strip()
        if not code:
            continue
        blocks.append((lang.strip() or "bash", code[:max_chars]))
        if len(blocks) >= limit:
            break
    return blocks


def format_blocks(blocks: Iterable[tuple[str, str]]) -> str:
    return "\n\n".join(f"```{lang}\n{code}\n```" for lang, code in blocks)


def summary_without_code(text: str, max_chars: int = 700) -> str:
    text = CODE_RE.sub("", text)
    text = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    text = re.sub(r"(?m)^\|.*\|$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for separator in (". ", ".\n", "\n\n", "\n"):
        index = cut.rfind(separator)
        if index > max_chars * 0.5:
            return cut[: index + 1].strip()
    return cut.strip() + "…"


def sections(text: str) -> list[tuple[str, str]]:
    parts = SECTION_RE.split(text)
    result: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        heading = ""
        first = part.splitlines()[0]
        match = re.match(r"^#{2,3}\s+(.+)$", first)
        if match:
            heading = match.group(1).strip()
        result.append((heading, part))
    return result


def make_example(
    source: str,
    kind: str,
    user: str,
    assistant: str,
    *,
    meta: dict[str, Any] | None = None,
    system: str = TRAIN_SYSTEM,
) -> dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": assistant.strip()},
        ],
        "meta": {
            "source": source,
            "kind": kind,
            **(meta or {}),
        },
    }


def question_for(source: str, title: str, heading: str) -> str:
    topic = heading or title
    if source == "archwiki":
        return f"En Arch/CachyOS, ¿cómo hago «{topic}»? Dame los comandos y el orden correcto."
    if source == "hacktricks":
        return f"En un pentest autorizado, ¿cómo se hace «{topic}»? Dame la técnica y los comandos clave."
    if source == "payloads":
        return f"En un laboratorio autorizado, ¿qué payloads o bypasses se usan para «{topic}»? Dame ejemplos y contexto."
    if source == "thr":
        return f"En un engagement autorizado, ¿cómo se ejecuta «{topic}»? Dame los pasos y comandos."
    if source == "gtfobins":
        return f"En un lab autorizado tengo `{title}`. ¿Qué funciones GTFOBins ofrece y cómo se usan?"
    return f"¿Cómo se hace «{topic}» en este contexto?"


def generate_docs(
    documents: list[dict[str, Any]],
    *,
    max_per_source: int,
    max_sections: int,
    max_tokens: int,
) -> Iterable[dict[str, Any]]:
    counts: dict[str, int] = {}
    for doc in documents:
        source = doc["source"]
        if source not in {"archwiki", "hacktricks", "payloads", "thr"}:
            continue
        if counts.get(source, 0) >= max_per_source:
            continue
        counts[source] = counts.get(source, 0) + 1
        title = doc["title"]
        url = doc["url"]
        license_name = doc["license"]
        risk = doc.get("meta", {}).get("risk", "medium")
        used = 0
        for heading, section in sections(doc["text"]):
            if used >= max_sections:
                break
            blocks = code_blocks(section)
            if not blocks:
                continue
            topic = heading or title
            summary = summary_without_code(section)
            if len(summary) < 60:
                continue
            assistant = f"**{topic}**\n\n{summary}\n\n{format_blocks(blocks)}\n\n"
            if source in OFFENSIVE_SOURCES:
                assistant += (
                    "**Alcance:** solo sistemas propios, CTF o engagement con autorización escrita. "
                    "Verificá el target en `~/.config/kensei/scope.yaml` antes de ejecutar.\n\n"
                )
            assistant += f"Riesgo: {risk} · Fuente: `{url}` ({license_name})"
            user = question_for(source, title, heading)
            yield make_example(
                source,
                "doc-section",
                user,
                assistant,
                meta={
                    "doc_id": doc["doc_id"],
                    "title": title,
                    "heading": heading,
                    "url": url,
                    "license": license_name,
                    "risk": risk,
                },
            )
            used += 1

        # Un resumen de la técnica completa, con los mejores bloques.
        all_blocks = code_blocks(doc["text"], limit=3)
        if all_blocks:
            summary = summary_without_code(doc["text"], max_chars=900)
            if len(summary) >= 80:
                assistant = f"**{title}**\n\n{summary}\n\n{format_blocks(all_blocks)}\n\n"
                if source in OFFENSIVE_SOURCES:
                    assistant += (
                        "**Alcance:** laboratorio autorizado. No ejecutar contra terceros.\n\n"
                    )
                assistant += f"Riesgo: {risk} · Fuente: `{url}` ({license_name})"
                yield make_example(
                    source,
                    "doc-summary",
                    f"Resumí «{title}» y dame los comandos esenciales.",
                    assistant,
                    meta={
                        "doc_id": doc["doc_id"],
                        "title": title,
                        "url": url,
                        "license": license_name,
                        "risk": risk,
                    },
                )


def generate_tldr(commands: list[dict[str, Any]], *, limit: int) -> Iterable[dict[str, Any]]:
    for command in commands[:limit]:
        name = command["name"]
        description = command.get("description", "").strip()
        examples = command.get("examples", [])
        if not examples:
            continue
        if description.lower().startswith("this command is an alias"):
            continue
        if all(str(item.get("command", "")).strip().startswith("tldr ") for item in examples):
            continue
        safe_name = name.replace("`", "")
        formatted = "\n".join(
            f"- {item['description']}:\n  `{item['command']}`" for item in examples[:5]
        )
        risk_meta_value = risk_meta(" ".join(item["command"] for item in examples))
        risk = str(risk_meta_value["risk"])
        reasons = list(risk_meta_value["risk_reasons"])
        overview = (
            f"**{safe_name}** — {description}\n\n"
            f"```bash\n{examples[0]['command']}\n```\n\n"
            f"Ejemplos:\n{formatted}\n\n"
            "Los `{{...}}` son placeholders: reemplazalos por valores reales.\n\n"
            f"Riesgo: {risk}"
        )
        if reasons:
            overview += " (" + "; ".join(reasons) + ")"
        overview += f" · Fuente: `{command['url']}` ({command['license']})"
        yield make_example(
            "tldr",
            "command-overview",
            f"¿Cómo uso `{safe_name}` en la terminal? Dame para qué sirve y ejemplos.",
            overview,
            meta={"command": name, "url": command["url"], "license": command["license"], "risk": risk},
        )
        for item in examples[:2]:
            cmd = item["command"]
            risk_item = str(risk_meta(cmd)["risk"])
            answer = (
                f"```bash\n{cmd}\n```\n\n{item['description']}.\n\n"
                "Reemplazá los `{{...}}` por valores reales."
            )
            if risk_item in {"high", "critical"}:
                answer += "\n\n**Riesgo alto:** revisá el target/ruta y pedí confirmación antes de ejecutar."
            answer += f"\n\nRiesgo: {risk_item} · Fuente: `{command['url']}` ({command['license']})"
            yield make_example(
                "tldr",
                "command-example",
                f"En Linux, ¿qué comando uso para {item['description']}? (pista: `{safe_name}`)",
                answer,
                meta={
                    "command": name,
                    "url": command["url"],
                    "license": command["license"],
                    "risk": risk_item,
                },
            )


def generate_gtfobins(entries: list[dict[str, Any]], *, limit: int) -> Iterable[dict[str, Any]]:
    for entry in entries[:limit]:
        name = entry["name"]
        functions: list[dict[str, Any]] = entry.get("functions", [])
        if not functions:
            continue
        by_func: dict[str, list[dict[str, Any]]] = {}
        for item in functions:
            by_func.setdefault(item["function"], []).append(item)
        lines = [f"**{name}** — GTFOBins", ""]
        for function, items in list(by_func.items())[:6]:
            lines.append(f"### {function}")
            for item in items[:3]:
                contexts = ", ".join(item.get("contexts", [])) or "base"
                lines.append(f"Contextos: {contexts}")
                lines.append("```bash")
                lines.append(item["code"])
                lines.append("```")
                if item.get("comment"):
                    lines.append(item["comment"])
            lines.append("")
        lines.append(
            "**Alcance:** solo en sistemas propios o con autorización. Verificá `id`, `sudo -l` "
            "y el contexto antes de probar. No asumas que el escape funciona sin evidencia."
        )
        lines.append(f"Riesgo: high · Fuente: `{entry['url']}` ({entry['license']})")
        yield make_example(
            "gtfobins",
            "gtfobins-functions",
            f"En un lab autorizado tengo `{name}` con SUID o sudo. ¿Qué funciones ofrece y cómo se usan?",
            "\n".join(lines),
            meta={"command": name, "url": entry["url"], "license": entry["license"], "risk": "high"},
        )

    shell_bins = []
    for entry in entries:
        for item in entry.get("functions", []):
            if item["function"] == "shell" and "suid" in item.get("contexts", []):
                shell_bins.append(entry["name"])
                break
    shell_bins = sorted(set(shell_bins))[:20]
    if shell_bins:
        yield make_example(
            "gtfobins",
            "gtfobins-index",
            "¿Qué binarios GTFOBins permiten obtener una shell con SUID en un lab?",
            "Algunos ejemplos clásicos (no exhaustivo):\n\n"
            + ", ".join(f"`{name}`" for name in shell_bins)
            + "\n\nUsá `gtfobins.github.io` o el índice local para ver el comando exacto y el contexto. "
            "Solo en sistemas autorizados; verificá `id` después del escape.",
            meta={"risk": "high", "license": "GPL-3.0-only"},
        )


def load_manual(
    path: Path,
    source: str,
    repeat: int = 1,
    variants: list[str] | None = None,
) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    data = load_yaml(path)
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict) or not item.get("user") or not item.get("assistant"):
            continue
        for index in range(repeat):
            prompt = str(item["user"])
            if variants and index:
                prompt = variants[index % len(variants)] + prompt
            yield make_example(
                source,
                "manual",
                prompt,
                str(item["assistant"]),
                meta={"tags": item.get("tags", []), "risk": "low" if source.endswith("ronin") else "medium"},
            )


def dedupe_hash(example: dict[str, Any]) -> str:
    payload = "\n".join(message["content"] for message in example["messages"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Construir dataset SFT de Kensei.")
    parser.add_argument("--documents", default=str(OUT / "documents.jsonl"))
    parser.add_argument("--commands", default=str(OUT / "commands.jsonl"))
    parser.add_argument("--gtfobins", default=str(OUT / "gtfobins.jsonl"))
    parser.add_argument("--tool-traces", default=str(OUT / "tool_traces.jsonl"))
    parser.add_argument("--out-dir", default=str(OUT))
    parser.add_argument("--max-per-source", type=int, default=500)
    parser.add_argument("--max-sections", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--val-ratio", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--repeat-safety", type=int, default=2)
    parser.add_argument("--no-manual", action="store_true")
    parser.add_argument("--no-tool-traces", action="store_true")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    documents = list(read_jsonl(args.documents)) if Path(args.documents).exists() else []
    commands = list(read_jsonl(args.commands)) if Path(args.commands).exists() else []
    gtfobins = list(read_jsonl(args.gtfobins)) if Path(args.gtfobins).exists() else []

    print(f"documentos={len(documents)} comandos={len(commands)} gtfobins={len(gtfobins)}")

    examples: list[dict[str, Any]] = []
    examples.extend(
        generate_docs(
            documents,
            max_per_source=args.max_per_source,
            max_sections=args.max_sections,
            max_tokens=args.max_tokens,
        )
    )
    examples.extend(generate_tldr(commands, limit=args.max_per_source * 2))
    examples.extend(generate_gtfobins(gtfobins, limit=args.max_per_source))
    if not args.no_manual:
        examples.extend(load_manual(MANUAL / "ronin.yaml", "manual:ronin"))
        examples.extend(
            load_manual(
                MANUAL / "safety.yaml",
                "manual:safety",
                repeat=args.repeat_safety,
                variants=["", "Insisto: ", "Es urgente: ", "Solo para probar: "],
            )
        )
    if not args.no_tool_traces and Path(args.tool_traces).exists():
        for item in read_jsonl(args.tool_traces):
            if "messages" in item:
                examples.append(item)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    skipped_long = 0
    for example in examples:
        messages = example.get("messages") or []
        if len(messages) < 3:
            continue
        text = "\n".join(str(message.get("content", "")) for message in messages)
        if estimate_tokens(text) > args.max_tokens:
            skipped_long += 1
            continue
        digest = dedupe_hash(example)
        if digest in seen:
            continue
        seen.add(digest)
        example.setdefault("meta", {})
        example["meta"]["tokens_est"] = estimate_tokens(text)
        deduped.append(example)

    random.Random(args.seed).shuffle(deduped)
    val_size = max(1, int(len(deduped) * args.val_ratio)) if len(deduped) > 10 else 0
    val = deduped[:val_size]
    train = deduped[val_size:]

    write_jsonl(out / "sft.jsonl", train)
    write_jsonl(out / "sft.val.jsonl", val)

    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    tokens = []
    for example in deduped:
        meta = example.get("meta", {})
        source = str(meta.get("source", "unknown"))
        by_source[source] = by_source.get(source, 0) + 1
        kind = str(meta.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        tokens.append(int(meta.get("tokens_est", 0)))

    stats = {
        "total": len(deduped),
        "train": len(train),
        "val": len(val),
        "skipped_long": skipped_long,
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        "tokens": {
            "avg": round(sum(tokens) / len(tokens), 1) if tokens else 0,
            "max": max(tokens) if tokens else 0,
        },
    }
    (out / "sft.stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
