from __future__ import annotations

from build_sft import generate_docs, generate_tldr, make_example
from build_tool_traces import fill_placeholders, generate_manual_traces
from normalize_corpus import chunk_document, excluded, parse_tldr, split_sections
from validate_dataset import validate_row


def test_parse_tldr():
    raw = """# nmap

> Network exploration tool and security scanner.
> More information: <https://nmap.org>.

- Scan a host:
`nmap {{host}}`

- Scan specific ports:
`nmap -p {{80,443}} {{host}}`
"""
    title, description, examples, text = parse_tldr(raw)
    assert title == "nmap"
    assert "Network exploration" in description[0]
    assert len(examples) == 2
    assert examples[0]["command"] == "nmap {{host}}"
    assert "# nmap" in text


def test_split_sections_and_chunk():
    doc = {
        "doc_id": "d1",
        "source": "archwiki",
        "title": "Btrfs",
        "url": "https://wiki.archlinux.org/title/Btrfs",
        "license": "GFDL-1.3-or-later",
        "text": "# Btrfs\n\nIntro.\n\n## Snapshots\n\n" + ("snapshot " * 400) + "\n\n## Subvolumes\n\n" + ("subvol " * 300),
    }
    sections = split_sections(doc["text"])
    assert len(sections) >= 2
    chunks = chunk_document(doc, max_chars=1000)
    assert len(chunks) >= 2
    assert all(chunk["doc_id"] == "d1" for chunk in chunks)
    assert all(len(chunk["text"]) <= 1200 for chunk in chunks)
    assert len({chunk["chunk_id"] for chunk in chunks}) == len(chunks)


def test_excluded_patterns():
    assert excluded("src/translations/es/page.md", ["src/translations/**"])
    assert not excluded("src/linux/hardening.md", ["src/translations/**"])


def test_generate_tldr_examples():
    commands = [
        {
            "name": "rg",
            "description": "Search files",
            "examples": [{"description": "Search for a pattern", "command": "rg '{{pattern}}'"}],
            "url": "https://github.com/tldr-pages/tldr",
            "license": "CC-BY-4.0",
        }
    ]
    rows = list(generate_tldr(commands, limit=5))
    assert len(rows) == 2
    assert rows[0]["messages"][0]["role"] == "system"
    assert "rg" in rows[0]["messages"][2]["content"]
    assert "Riesgo: low" in rows[0]["messages"][2]["content"]
    assert rows[0]["meta"]["source"] == "tldr"


def test_fill_placeholders_uses_source_and_destination():
    filled = fill_placeholders("cp {{path/to/source}} {{path/to/destination}}", "cp")
    assert filled == "cp /home/davosoler/notas.txt /tmp/kensei-demo"
    assert "VALOR" not in filled


def test_generate_manual_traces():
    traces = generate_manual_traces(variants=1)
    assert len(traces) >= 50
    assert all(trace["meta"]["kind"] == "tool-trace" for trace in traces)
    assert any("<tool_call>" in trace["messages"][2]["content"] for trace in traces)
    assert all("VALOR" not in trace["messages"][2]["content"] for trace in traces)


def test_generate_tldr_skips_aliases():
    commands = [
        {
            "name": "bye",
            "description": "This command is an alias of `exit`.",
            "examples": [{"description": "View docs", "command": "tldr exit"}],
            "url": "https://github.com/tldr-pages/tldr",
            "license": "CC-BY-4.0",
        }
    ]
    assert list(generate_tldr(commands, limit=5)) == []


def test_generate_docs_with_code():
    documents = [
        {
            "doc_id": "d1",
            "source": "archwiki",
            "title": "Snapper",
            "url": "https://wiki.archlinux.org/title/Snapper",
            "license": "GFDL-1.3-or-later",
            "text": (
                "# Snapper\n\n## Create\n\n"
                "Create a snapshot before changing the system. Use a clear description.\n\n"
                "```bash\nsudo snapper -c root create --description before-update\n```\n"
            ),
            "meta": {"risk": "low"},
        }
    ]
    rows = list(generate_docs(documents, max_per_source=10, max_sections=3, max_tokens=3000))
    assert rows
    assistant = rows[0]["messages"][2]["content"]
    assert "snapper -c root create" in assistant
    assert "Fuente:" in assistant


def test_make_example_shape():
    row = make_example("manual:test", "manual", "hola", "mundo")
    assert [message["role"] for message in row["messages"]] == ["system", "user", "assistant"]
    assert row["meta"]["kind"] == "manual"


def test_validate_good_row():
    row = {
        "messages": [
            {"role": "system", "content": "sos kensei"},
            {"role": "user", "content": "listá el disco"},
            {
                "role": "assistant",
                "content": 'Usá `df -hT`.\n<tool_call>{"name":"shell","arguments":{"cmd":"df -hT"}}</tool_call>',
            },
            {"role": "tool", "content": "/dev/nvme0n1p3 btrfs 427G 389G 36G 92% /"},
            {"role": "assistant", "content": "El disco está al 92 %; revisá Docker y logs antes de borrar."},
        ],
        "meta": {"source": "manual:ronin", "kind": "manual", "license": "MIT"},
    }
    errors, _warnings, info = validate_row(0, row, max_tokens=4096)
    assert not errors
    assert info["source"] == "manual:ronin"
    assert info["tokens"] > 0


def test_validate_bad_row():
    row = {
        "messages": [
            {"role": "assistant", "content": "sin system"},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "<tool_call>{roto}</tool_call>"},
        ],
        "meta": {},
    }
    errors, warnings, _ = validate_row(0, row, max_tokens=4096)
    assert errors
    assert any("system" in error for error in errors)
    assert any("vacío" in error for error in errors)
    assert any("tool-call" in error or "JSON" in error for error in errors)
    assert warnings
