from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

TOOL_NAMES = {"shell", "read_file", "write_file", "http_get", "recall"}
CODE_BLOCK_RE = re.compile(
    r"```(?:bash|sh|shell|zsh|console)?[ \t]*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    error: str | None = None


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _call_from_object(obj: Any, raw: str) -> ToolCall:
    if not isinstance(obj, dict):
        return ToolCall(name="", raw=raw, error="el tool-call debe ser un objeto JSON")
    name = obj.get("name") or obj.get("tool") or ""
    arguments = obj.get("arguments", obj.get("args", {}))
    if not isinstance(name, str) or not name:
        return ToolCall(name="", raw=raw, error="falta el campo name")
    if not isinstance(arguments, dict):
        return ToolCall(name=name, raw=raw, error="arguments debe ser un objeto")
    if name not in TOOL_NAMES:
        return ToolCall(
            name=name,
            arguments=arguments,
            raw=raw,
            error=f"herramienta desconocida: {name}",
        )
    return ToolCall(name=name, arguments=arguments, raw=raw)


def _fallback_json_call(text: str) -> list[ToolCall]:
    """Aceptar JSON puro cuando un modelo base no emite las etiquetas XML.

    Solo se acepta un objeto/array JSON que ocupe toda la respuesta y cuya
    herramienta sea conocida. Así no convertimos prosa con JSON embebido en una
    ejecución accidental.
    """
    candidate = _strip_fence(text.strip())
    if not candidate.startswith(("{", "[")):
        return []
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    objects = payload if isinstance(payload, list) else [payload]
    calls: list[ToolCall] = []
    for obj in objects:
        call = _call_from_object(obj, candidate)
        if call.error is None:
            calls.append(call)
    return calls


def parse_tool_calls(
    text: str,
    *,
    allow_code_block: bool = False,
    allow_json_fallback: bool = True,
) -> list[ToolCall]:
    """Parse the textual <tool_call> protocol used by Kensei.

    The model may emit one or more JSON objects. Malformed calls are returned
    with ``error`` set so the harness can tell the model what went wrong instead
    of silently executing something else. If there are no XML tags, a pure JSON
    object/array with a known tool is accepted as a compatibility fallback for
    base models. With ``allow_code_block=True``, a single fenced bash/sh block
    is also accepted as a shell call; this is opt-in because a model may show an
    example command that it did not intend to execute.
    """
    calls: list[ToolCall] = []
    if not text:
        return calls

    cursor = 0
    open_tag = "<tool_call>"
    close_tag = "</tool_call>"
    while True:
        start = text.find(open_tag, cursor)
        if start < 0:
            break
        end = text.find(close_tag, start)
        if end < 0:
            calls.append(ToolCall(name="", raw=text[start:], error="falta </tool_call>"))
            break
        raw = text[start + len(open_tag) : end].strip()
        cursor = end + len(close_tag)
        payload = _strip_fence(raw)
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as exc:
            calls.append(ToolCall(name="", raw=raw, error=f"JSON inválido: {exc}"))
            continue
        calls.append(_call_from_object(obj, raw))

    if calls:
        return calls

    json_calls = _fallback_json_call(text) if allow_json_fallback else []
    if json_calls:
        return json_calls

    if allow_code_block:
        blocks = CODE_BLOCK_RE.findall(text)
        if len(blocks) == 1:
            block = blocks[0].strip()
            nested = _fallback_json_call(block)
            if nested:
                return nested
            if block:
                return [ToolCall(name="shell", arguments={"cmd": block}, raw=block)]

    return []


def render_tool_call(name: str, arguments: dict[str, Any]) -> str:
    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments}, ensure_ascii=False)}</tool_call>"


def render_tool_response(content: str) -> str:
    return f"<tool_response>\n{content}\n</tool_response>"


def tool_specs() -> str:
    return """\
- shell: {"cmd": "comando", "cwd": "opcional", "timeout": 120}
- read_file: {"path": "ruta"}
- write_file: {"path": "ruta", "content": "texto"}
- http_get: {"url": "https://..."}
- recall: {"query": "tema", "k": 6}
"""
