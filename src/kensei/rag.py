from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from kensei.paths import derived_dir

TOKEN_RE = re.compile(r"[\w./+-]{2,}", re.UNICODE)


class RagIndex:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else derived_dir("kensei.db")

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def build(self, chunks_path: str | Path | None = None, reset: bool = True) -> int:
        source = Path(chunks_path) if chunks_path else derived_dir("chunks.jsonl")
        if not source.exists():
            raise FileNotFoundError(f"no existe {source}; corré normalize_corpus.py primero")
        conn = self._connect()
        try:
            if reset:
                conn.execute("DROP TABLE IF EXISTS chunks")
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    chunk_id UNINDEXED,
                    doc_id UNINDEXED,
                    source UNINDEXED,
                    title,
                    url UNINDEXED,
                    license UNINDEXED,
                    text,
                    tokenize = 'unicode61 remove_diacritics 2'
                )
                """
            )
            rows = []
            with source.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    rows.append(
                        (
                            item.get("chunk_id") or item.get("id", ""),
                            item.get("doc_id", ""),
                            item.get("source", ""),
                            item.get("title", ""),
                            item.get("url", ""),
                            item.get("license", ""),
                            item.get("text", ""),
                        )
                    )
            conn.executemany(
                "INSERT INTO chunks (chunk_id, doc_id, source, title, url, license, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            conn.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def count(self) -> int:
        if not self.db_path.exists():
            return 0
        conn = self._connect()
        try:
            return int(conn.execute("SELECT count(*) FROM chunks").fetchone()[0])
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()

    def search(self, query: str, k: int = 6) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        tokens = TOKEN_RE.findall(query)
        if not tokens:
            return []
        # FTS5 query: OR de tokens citados. Evita sintaxis arbitraria del usuario.
        fts_query = " OR ".join(f'"{token}"' for token in tokens[:12])
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT chunk_id, doc_id, source, title, url, license, text,
                       bm25(chunks) AS score
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, max(1, min(k, 20))),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT chunk_id, doc_id, source, title, url, license, text, 0.0 AS score
                FROM chunks
                WHERE text LIKE ? OR title LIKE ?
                LIMIT ?
                """,
                (like, like, max(1, min(k, 20))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def context(self, query: str, k: int = 5, max_chars: int = 6000) -> str:
        hits = self.search(query, k=k)
        if not hits:
            return ""
        blocks = []
        used = 0
        for hit in hits:
            header = f"[{hit['source']}] {hit['title']} — {hit['url']}"
            text = str(hit["text"]).strip()
            remaining = max_chars - used
            if remaining <= 200:
                break
            text = text[:remaining]
            block = f"{header}\n{text}"
            blocks.append(block)
            used += len(block)
        return "\n\n---\n\n".join(blocks)
