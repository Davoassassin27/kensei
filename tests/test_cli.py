from __future__ import annotations

from kensei.cli import build_parser, load_system_prompt, trim_history, user_payload
from kensei.guard import Scope


def test_parser_ask_defaults():
    parser = build_parser()
    args = parser.parse_args(["ask", "hola", "--execute", "--model", "kensei"])
    assert args.command == "ask"
    assert args.prompt == "hola"
    assert args.execute is True
    assert args.model == "kensei"
    assert args.no_rag is False
    assert args.rag_k == 5


def test_parser_chat_numeric_options():
    parser = build_parser()
    args = parser.parse_args(["chat", "--temperature", "0.1", "--rag-k", "3", "--max-tool-rounds", "4"])
    assert args.temperature == 0.1
    assert args.rag_k == 3
    assert args.max_tool_rounds == 4


def test_parser_index_and_recall():
    parser = build_parser()
    assert parser.parse_args(["index"]).command == "index"
    recall = parser.parse_args(["recall", "btrfs", "--k", "2"])
    assert recall.query == "btrfs"
    assert recall.k == 2


def test_parser_auto():
    parser = build_parser()
    args = parser.parse_args(["auto", "enumerá SMB", "--model", "kensei"])
    assert args.command == "auto"
    assert args.prompt == "enumerá SMB"
    assert args.model == "kensei"


def test_system_prompt_has_scope_and_tools():
    scope = Scope(engagement="test", authorized=True, cidrs=[])
    prompt = load_system_prompt(scope, rag_enabled=True)
    assert "Kensei" in prompt
    assert "Scope activo" in prompt
    assert "shell" in prompt
    assert "CONTEXTO RECUPERADO" in prompt


def test_user_payload_without_rag():
    assert user_payload("hola", None, k=5) == "hola"


def test_trim_history_keeps_system_and_user_tail():
    messages = [{"role": "system", "content": "sys"}]
    for index in range(30):
        messages.append({"role": "user", "content": f"u{index}"})
        messages.append({"role": "assistant", "content": f"a{index}"})
    trimmed = trim_history(messages, limit=10)
    assert trimmed[0]["role"] == "system"
    assert len(trimmed) <= 11
    assert trimmed[1]["role"] == "user"
