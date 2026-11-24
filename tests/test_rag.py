from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kensei.rag import RagIndex


def chunks(path: Path) -> Path:
    rows = [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "source": "archwiki",
            "title": "Btrfs",
            "url": "https://wiki.archlinux.org/title/Btrfs",
            "license": "GFDL-1.3-or-later",
            "text": "Los snapshots de Btrfs se crean con btrfs subvolume snapshot.",
        },
        {
            "chunk_id": "c2",
            "doc_id": "d2",
            "source": "archwiki",
            "title": "Snapper",
            "url": "https://wiki.archlinux.org/title/Snapper",
            "license": "GFDL-1.3-or-later",
            "text": "snapper -c root create --description crea un snapshot del sistema.",
        },
        {
            "chunk_id": "c3",
            "doc_id": "d3",
            "source": "tldr",
            "title": "nmap",
            "url": "https://github.com/tldr-pages/tldr",
            "license": "CC-BY-4.0",
            "text": "nmap escanea puertos y servicios de un host autorizado.",
        },
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def require_fts5():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
    except sqlite3.OperationalError:
        pytest.skip("sqlite sin FTS5")
    finally:
        conn.close()


def test_build_and_count(tmp_path: Path):
    index = RagIndex(tmp_path / "kensei.db")
    assert index.count() == 0
    assert index.build(chunks(tmp_path / "chunks.jsonl")) == 3
    assert index.count() == 3


def test_search_returns_relevant_first(tmp_path: Path):
    index = RagIndex(tmp_path / "kensei.db")
    index.build(chunks(tmp_path / "chunks.jsonl"))
    hits = index.search("btrfs snapshot", k=2)
    assert hits
    assert any(hit["title"] == "Btrfs" for hit in hits)
    assert all("score" in hit for hit in hits)


def test_context_has_source_and_url(tmp_path: Path):
    index = RagIndex(tmp_path / "kensei.db")
    index.build(chunks(tmp_path / "chunks.jsonl"))
    context = index.context("snapper", k=2, max_chars=1000)
    assert "[archwiki]" in context
    assert "https://" in context


def test_search_without_index(tmp_path: Path):
    index = RagIndex(tmp_path / "missing.db")
    assert index.search("btrfs") == []
    assert index.context("btrfs") == ""


def test_search_handles_fts_syntax(tmp_path: Path):
    index = RagIndex(tmp_path / "kensei.db")
    index.build(chunks(tmp_path / "chunks.jsonl"))
    assert isinstance(index.search('" OR * AND (', k=3), list)


def test_rebuild_resets(tmp_path: Path):
    index = RagIndex(tmp_path / "kensei.db")
    index.build(chunks(tmp_path / "chunks.jsonl"))
    index.build(chunks(tmp_path / "chunks.jsonl"))
    assert index.count() == 3
