from __future__ import annotations

import argparse
import fnmatch
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from _common import (
    ROOT,
    clean_markdown,
    first_heading,
    load_yaml,
    read_jsonl,
    risk_meta,
    sha256,
    stable_id,
    strip_front_matter,
    write_jsonl,
)

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "derived"
SOURCES_FILE = ROOT / "config" / "sources.yaml"


def rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def excluded(rel_path: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if pattern.endswith("/**") and rel_path.startswith(pattern[:-3] + "/"):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(rel_path, pattern[3:]):
            return True
    return False


def markdown_url(source: str, rel_path: str) -> str:
    if source == "hacktricks":
        return f"https://github.com/HackTricks-wiki/hacktricks/blob/master/{rel_path}"
    if source == "payloads":
        return f"https://github.com/swisskyrepo/PayloadsAllTheThings/blob/master/{rel_path}"
    if source == "thr":
        site = rel_path.removeprefix("docs/src/").removesuffix(".md")
        site = site.removesuffix("/index")
        return f"https://www.thehacker.recipes/{site}"
    return rel_path


def iter_markdown(source: str, cfg: dict[str, Any], limit: int | None) -> Iterable[dict[str, Any]]:
    base = RAW / source
    if not base.exists():
        return
    files: list[Path] = []
    for pattern in cfg.get("include", ["**/*.md"]):
        files.extend(base.glob(pattern))
    files = sorted({p for p in files if p.is_file() and p.suffix.lower() == ".md"})
    count = 0
    for path in files:
        rel_path = rel(path, base)
        if excluded(rel_path, cfg.get("exclude", [])):
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = strip_front_matter(raw)
        text = clean_markdown(body)
        if len(text) < 200:
            continue
        title = str(meta.get("title") or meta.get("description") or "").strip()
        if not title:
            title = first_heading(text) or path.stem.replace("-", " ").replace("_", " ")
        if text.startswith("# "):
            doc_text = text
        else:
            doc_text = f"# {title}\n\n{text}"
        doc_id = f"{source}:{rel_path}"
        yield {
            "doc_id": stable_id(doc_id),
            "source": source,
            "title": title[:300],
            "url": markdown_url(source, rel_path),
            "license": cfg.get("license", "unknown"),
            "text": doc_text,
            "meta": {
                "path": rel_path,
                "front_matter": {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list))},
                **risk_meta(doc_text),
            },
        }
        count += 1
        if limit and count >= limit:
            return


def iter_archwiki(cfg: dict[str, Any], limit: int | None) -> Iterable[dict[str, Any]]:
    base = RAW / "archwiki"
    index_path = base / "index.jsonl"
    if not index_path.exists():
        return
    count = 0
    for entry in read_jsonl(index_path):
        path = ROOT / entry["path"]
        if not path.exists():
            continue
        text = clean_markdown(path.read_text(encoding="utf-8", errors="replace"))
        if len(text) < 300:
            continue
        title = str(entry.get("title") or path.stem.replace("_", " "))
        doc_text = f"# {title}\n\n{text}"
        yield {
            "doc_id": stable_id(f"archwiki:{title}"),
            "source": "archwiki",
            "title": title[:300],
            "url": entry.get("url", f"https://wiki.archlinux.org/title/{title.replace(' ', '_')}"),
            "license": cfg.get("license", "GFDL-1.3-or-later"),
            "text": doc_text,
            "meta": {"path": entry["path"], **risk_meta(doc_text)},
        }
        count += 1
        if limit and count >= limit:
            return


TLDR_EXAMPLE_RE = re.compile(r"^`(.+)`\.?$")


def parse_tldr(text: str) -> tuple[str, list[str], list[dict[str, str]], str]:
    lines = text.replace("\r\n", "\n").splitlines()
    title = ""
    description: list[str] = []
    examples: list[dict[str, str]] = []
    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("> "):
            value = line[2:].strip()
            if value.lower().startswith("more info"):
                continue
            description.append(value)

    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("- ") and line.rstrip().endswith(":"):
            label = line[2:].rstrip(":").strip()
            cursor = index + 1
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if cursor < len(lines):
                match = TLDR_EXAMPLE_RE.match(lines[cursor].strip())
                if match:
                    examples.append({"description": label, "command": match.group(1).strip()})
                    index = cursor
        index += 1

    body = [f"# {title or 'comando'}", ""]
    if description:
        body.append("> " + " ".join(description))
        body.append("")
    for example in examples:
        body.append(f"- {example['description']}:")
        body.append(f"`{example['command']}`")
        body.append("")
    return title, description, examples, "\n".join(body).strip()


def iter_tldr(cfg: dict[str, Any], limit: int | None) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    base = RAW / "tldr"
    if not base.exists():
        return
    files: list[Path] = []
    for pattern in cfg.get("include", ["pages/common/*.md", "pages/linux/*.md"]):
        files.extend(base.glob(pattern))
    files = sorted({p for p in files if p.is_file()})
    count = 0
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        _title, description, examples, text = parse_tldr(raw)
        if not examples or len(text) < 80:
            continue
        rel_path = rel(path, base)
        name = path.stem
        url = f"https://github.com/tldr-pages/tldr/blob/main/{rel_path}"
        doc = {
            "doc_id": stable_id(f"tldr:{rel_path}"),
            "source": "tldr",
            "title": name,
            "url": url,
            "license": cfg.get("license", "CC-BY-4.0"),
            "text": text,
            "meta": {
                "path": rel_path,
                "description": " ".join(description),
                "examples": len(examples),
                **risk_meta(text),
            },
        }
        command = {
            "name": name,
            "description": " ".join(description),
            "examples": examples,
            "url": url,
            "license": cfg.get("license", "CC-BY-4.0"),
        }
        yield doc, command
        count += 1
        if limit and count >= limit:
            return


def normalize_contexts(entry: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = entry.get("contexts") or {}
    result: list[dict[str, Any]] = []
    context_names: list[str] = []
    if isinstance(contexts, dict):
        for name, value in contexts.items():
            context_names.append(str(name))
            if isinstance(value, dict) and value.get("code"):
                result.append(
                    {
                        "context": str(name),
                        "code": str(value["code"]).strip(),
                        "comment": str(value.get("comment", "")).strip(),
                    }
                )
    base_code = str(entry.get("code", "")).strip()
    if base_code:
        result.insert(
            0,
            {
                "context": "base",
                "code": base_code,
                "comment": str(entry.get("comment", "")).strip(),
            },
        )
    for item in result:
        item["contexts"] = context_names
    return result


def iter_manual(cfg: dict[str, Any], limit: int | None) -> Iterable[dict[str, Any]]:
    base = ROOT / str(cfg.get("path", "data/manual"))
    if not base.exists():
        return
    count = 0
    for path in sorted(base.glob("*.yaml")):
        data = load_yaml(path)
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            user = str(item.get("user", "")).strip()
            assistant = str(item.get("assistant", "")).strip()
            if not user or not assistant:
                continue
            title = user[:300]
            text = f"# {title}\n\n{assistant}"
            doc_id = stable_id(f"manual:{path.stem}:{item.get('id', title)}")
            yield {
                "doc_id": doc_id,
                "source": f"manual:{path.stem}",
                "title": title,
                "url": f"data/manual/{path.name}#{item.get('id', '')}",
                "license": str(cfg.get("license", "MIT")),
                "text": text,
                "meta": {
                    "path": path.name,
                    "tags": item.get("tags", []),
                    **risk_meta(text),
                },
            }
            count += 1
            if limit and count >= limit:
                return


def iter_gtfobins(cfg: dict[str, Any], limit: int | None) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    base = RAW / "gtfobins"
    if not base.exists():
        return
    files = sorted(p for p in (base / "_gtfobins").glob("*") if p.is_file())
    count = 0
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # Windows Defender puede bloquear archivos de GTFOBins (ej. "node").
            print(f"[gtfobins] omitido {path.name}: {exc}")
            continue
        meta, _body = strip_front_matter(raw)
        functions = meta.get("functions")
        if not isinstance(functions, dict):
            continue
        name = path.name
        flattened: list[dict[str, Any]] = []
        for function, entries in functions.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for item in normalize_contexts(entry):
                    flattened.append({"function": str(function), **item})
        if not flattened:
            continue

        lines = [f"# {name}", ""]
        for item in flattened:
            lines.append(f"## {item['function']} ({item['context']})")
            if item.get("comment"):
                lines.append(item["comment"])
            lines.append("```bash")
            lines.append(item["code"])
            lines.append("```")
            if item.get("contexts"):
                lines.append("Contextos: " + ", ".join(item["contexts"]))
            lines.append("")
        text = "\n".join(lines).strip()
        url = f"https://gtfobins.github.io/gtfobins/{name}/"
        doc = {
            "doc_id": stable_id(f"gtfobins:{name}"),
            "source": "gtfobins",
            "title": name,
            "url": url,
            "license": cfg.get("license", "GPL-3.0-only"),
            "text": text,
            "meta": {"path": f"_gtfobins/{name}", "functions": len(flattened), "risk": "high"},
        }
        entry = {
            "name": name,
            "functions": flattened,
            "url": url,
            "license": cfg.get("license", "GPL-3.0-only"),
        }
        yield doc, entry
        count += 1
        if limit and count >= limit:
            return


def split_sections(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)(?=^#{2,4}\s+)", text)
    sections: list[tuple[str, str]] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        heading = ""
        first = part.splitlines()[0]
        match = re.match(r"^#{2,4}\s+(.+)$", first)
        if match:
            heading = match.group(1).strip()
        sections.append((heading, part))
    return sections or [("", text)]


def chunk_section(heading: str, text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                size = 0
            words = paragraph.split()
            piece: list[str] = []
            piece_size = 0
            for word in words:
                if piece_size + len(word) + 1 > max_chars:
                    chunks.append(" ".join(piece))
                    piece = [word]
                    piece_size = len(word)
                else:
                    piece.append(word)
                    piece_size += len(word) + 1
            if piece:
                chunks.append(" ".join(piece))
            continue
        if size + len(paragraph) + 2 > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            size = len(paragraph)
        else:
            current.append(paragraph)
            size += len(paragraph) + 2
    if current:
        chunks.append("\n\n".join(current))
    if heading:
        prefix = f"## {heading} (cont.)\n\n"
        return [chunks[0]] + [prefix + chunk for chunk in chunks[1:]]
    return chunks


def chunk_document(doc: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    ordinal = 0
    for heading, section in split_sections(doc["text"]):
        for piece in chunk_section(heading, section, max_chars):
            if len(piece.strip()) < 80:
                continue
            chunks.append(
                {
                    "chunk_id": stable_id(doc["doc_id"], str(ordinal)),
                    "doc_id": doc["doc_id"],
                    "source": doc["source"],
                    "title": doc["title"],
                    "url": doc["url"],
                    "license": doc["license"],
                    "ordinal": ordinal,
                    "section": heading,
                    "text": piece,
                }
            )
            ordinal += 1
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalizar fuentes de Kensei a documentos/chunks.")
    parser.add_argument("--sources-file", default=str(SOURCES_FILE))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--limit", type=int, default=None, help="máximo de documentos por fuente")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    cfg = load_yaml(args.sources_file).get("sources", {})
    selected = args.only or list(cfg.keys())
    unknown = [name for name in selected if name not in cfg]
    if unknown:
        raise SystemExit(f"fuentes desconocidas: {unknown}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    gtfobins: list[dict[str, Any]] = []
    seen: set[str] = set()
    stats: dict[str, Any] = {"per_source": {}, "duplicates": 0}

    def add(doc: dict[str, Any], chunks_list: list[dict[str, Any]] | None = None) -> bool:
        digest = sha256(doc["text"])
        if digest in seen:
            stats["duplicates"] += 1
            return False
        seen.add(digest)
        doc["sha256"] = digest
        documents.append(doc)
        if chunks_list is None:
            chunks_list = chunk_document(doc, args.max_chars)
        chunks.extend(chunks_list)
        bucket = stats["per_source"].setdefault(
            doc["source"], {"documents": 0, "chunks": 0, "chars": 0}
        )
        bucket["documents"] += 1
        bucket["chunks"] += len(chunks_list)
        bucket["chars"] += len(doc["text"])
        return True

    if "archwiki" in selected:
        for doc in iter_archwiki(cfg["archwiki"], args.limit):
            add(doc)
        print(f"[archwiki] {stats['per_source'].get('archwiki', {})}")

    if "manual" in selected:
        manual_cfg = cfg.get("manual") or {"path": "data/manual", "license": "MIT"}
        for doc in iter_manual(manual_cfg, args.limit):
            add(doc)
        print(
            f"[manual] ronin={stats['per_source'].get('manual:ronin', {})} "
            f"safety={stats['per_source'].get('manual:safety', {})}"
        )

    for source in ("hacktricks", "payloads", "thr"):
        if source in selected:
            for doc in iter_markdown(source, cfg[source], args.limit):
                add(doc)
            print(f"[{source}] {stats['per_source'].get(source, {})}")

    if "tldr" in selected:
        for doc, command in iter_tldr(cfg["tldr"], args.limit):
            if add(doc):
                commands.append(command)
        print(f"[tldr] {stats['per_source'].get('tldr', {})}")

    if "gtfobins" in selected:
        for doc, entry in iter_gtfobins(cfg["gtfobins"], args.limit):
            if add(doc):
                gtfobins.append(entry)
        print(f"[gtfobins] {stats['per_source'].get('gtfobins', {})}")

    stats["documents"] = len(documents)
    stats["chunks"] = len(chunks)
    stats["commands"] = len(commands)
    stats["gtfobins"] = len(gtfobins)
    stats["total_chars"] = sum(len(doc["text"]) for doc in documents)

    write_jsonl(out / "documents.jsonl", documents)
    write_jsonl(out / "chunks.jsonl", chunks)
    write_jsonl(out / "commands.jsonl", commands)
    write_jsonl(out / "gtfobins.jsonl", gtfobins)
    (out / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
