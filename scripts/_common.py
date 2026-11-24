from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Windows usa cp1252 por defecto y rompe con flechas/emoji en la salida.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def load_yaml(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def read_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(*parts: str) -> str:
    return hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()[:20]


def slugify(text: str, max_len: int = 90) -> str:
    text = re.sub(r"[^\w.-]+", "-", text, flags=re.UNICODE).strip("-._")
    return (text[:max_len] or "page").lower()


def estimate_tokens(text: str) -> int:
    # Aproximación conservadora para planificar, no para contar exacto.
    return max(1, len(text) // 4)


def strip_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, min(len(lines), 120)):
        if lines[index].strip() in {"---", "..."}:
            end = index
            break
    if end is None:
        return {}, text
    raw = "\n".join(lines[1:end])
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, "\n".join(lines[end + 1 :])


def first_heading(text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return ""


def clean_markdown(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\{\{#include[^}]*\}\}", "", text)
    text = re.sub(r"\{%[^%]*%\}", "", text)
    # Imágenes Markdown -> alt text
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Badges [![alt](img)](link) -> alt
    text = re.sub(r"\[!\[([^\]]*)\]\([^)]+\)\]\([^)]+\)", r"\1", text)
    # Tags HTML comunes -> markdown o texto plano
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)
    text = html.unescape(text)
    # Tags HTML restantes (no tocar placeholders de comandos)
    text = re.sub(
        r"</?(?:figure|figcaption|img|a|div|span|br|p|details|summary|table|tr|td|th|ul|ol|li|pre)\b[^>]*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace("\u200b", "").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def risk_meta(text: str) -> dict[str, Any]:
    from kensei.guard import risk_of_text

    risk, reasons = risk_of_text(text)
    return {"risk": risk, "risk_reasons": reasons}
