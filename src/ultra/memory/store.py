"""Persistent Sage-compatible Memory Anchor storage (SQLite + FTS5)."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ultra.memory.embed import Embedder, deserialize_embedding, serialize_embedding

SHARED_PERSONALITY_ID = "__shared__"

FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS anchors_fts USING fts5(
    content,
    anchor_id UNINDEXED,
    conversation_id UNINDEXED,
    anchor_type UNINDEXED,
    importance UNINDEXED,
    created_at UNINDEXED,
    personality_id UNINDEXED,
    tokenize = 'porter unicode61'
);

DROP TRIGGER IF EXISTS anchors_ai_fts;
DROP TRIGGER IF EXISTS anchors_au_fts;
DROP TRIGGER IF EXISTS anchors_ad_fts;

CREATE TRIGGER anchors_ai_fts AFTER INSERT ON anchors BEGIN
    INSERT INTO anchors_fts(content, anchor_id, conversation_id, anchor_type, importance, created_at, personality_id)
    VALUES (new.content, new.id, new.conversation_id, new.anchor_type, new.importance, new.created_at, new.personality_id);
END;

CREATE TRIGGER anchors_au_fts AFTER UPDATE ON anchors BEGIN
    DELETE FROM anchors_fts WHERE anchor_id = old.id;
    INSERT INTO anchors_fts(content, anchor_id, conversation_id, anchor_type, importance, created_at, personality_id)
    VALUES (new.content, new.id, new.conversation_id, new.anchor_type, new.importance, new.created_at, new.personality_id);
END;

CREATE TRIGGER anchors_ad_fts AFTER DELETE ON anchors BEGIN
    DELETE FROM anchors_fts WHERE anchor_id = old.id;
END;
"""

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    personality_id TEXT DEFAULT 'ultra'
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    personality_id TEXT DEFAULT 'ultra',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    anchor_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 1,
    embedding BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    personality_id TEXT DEFAULT 'ultra',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_anchors_personality ON anchors(personality_id);
CREATE INDEX IF NOT EXISTS idx_anchors_conversation ON anchors(conversation_id);
"""


@dataclass
class StoredAnchor:
    id: str
    content: str
    anchor_type: str
    importance: int
    created_at: str
    conversation_id: str | None = None


class MemoryStore:
    def __init__(
        self,
        db_path: Path,
        personality_id: str,
        embedder: Embedder | None,
        semantic_enabled: bool,
    ) -> None:
        self.db_path = db_path
        self.personality_id = personality_id
        self.embedder = embedder
        self.semantic_enabled = semantic_enabled
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_DDL)
            if not self._table_exists(conn, "anchors_fts"):
                conn.executescript(FTS_DDL)
                conn.execute(
                    """INSERT INTO anchors_fts(content, anchor_id, conversation_id, anchor_type, importance, created_at, personality_id)
                       SELECT content, id, conversation_id, anchor_type, importance, created_at, personality_id FROM anchors"""
                )
            conn.execute("PRAGMA user_version = 8")

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def remember(
        self,
        content: str,
        *,
        anchor_type: str = "fact",
        importance: int = 3,
        conversation_id: str | None = None,
        embed: bool = True,
    ) -> str:
        content = content.strip()
        if not content:
            raise ValueError("content is required")

        anchor_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        personality = self._resolve_personality(content)

        embedding_blob: bytes | None = None
        if embed and self.semantic_enabled and self.embedder:
            try:
                vec = self.embedder.embed_one(content)
                embedding_blob = serialize_embedding(vec)
            except Exception:
                embedding_blob = None

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO anchors (id, conversation_id, anchor_type, content, importance, embedding, created_at, personality_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    anchor_id,
                    conversation_id,
                    anchor_type,
                    content,
                    max(1, min(5, importance)),
                    embedding_blob,
                    now,
                    personality,
                ),
            )
        return anchor_id

    def embed_pending(self, limit: int = 24) -> int:
        if not self.semantic_enabled or not self.embedder:
            return 0
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, content FROM anchors
                   WHERE embedding IS NULL AND personality_id IN (?, ?)
                   LIMIT ?""",
                (self.personality_id, SHARED_PERSONALITY_ID, limit),
            ).fetchall()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        texts = [r["content"] for r in rows]
        try:
            vectors = self.embedder.embed(texts)
        except Exception:
            return 0
        count = 0
        with self._connect() as conn:
            for aid, vec in zip(ids, vectors):
                conn.execute(
                    "UPDATE anchors SET embedding = ? WHERE id = ?",
                    (serialize_embedding(vec), aid),
                )
                count += 1
        return count

    def count_pending_embeddings(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM anchors
                   WHERE embedding IS NULL AND personality_id IN (?, ?)""",
                (self.personality_id, SHARED_PERSONALITY_ID),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_embedded(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM anchors
                   WHERE embedding IS NOT NULL AND personality_id IN (?, ?)""",
                (self.personality_id, SHARED_PERSONALITY_ID),
            ).fetchone()
        return int(row[0]) if row else 0

    def clear_all_embeddings(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE anchors SET embedding = NULL
                   WHERE personality_id IN (?, ?)""",
                (self.personality_id, SHARED_PERSONALITY_ID),
            )

    def embed_pending_until_done(self, *, batch_size: int = 24) -> int:
        """Embed all anchors missing vectors (manual catch-up / reindex)."""
        total = 0
        while True:
            n = self.embed_pending(limit=batch_size)
            if n == 0:
                break
            total += n
        return total

    def _resolve_personality(self, content: str) -> str:
        if content.startswith("[shared]") or content.startswith("[project:"):
            return SHARED_PERSONALITY_ID
        return self.personality_id

    def store_message(
        self,
        role: str,
        content: str,
        conversation_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO messages (conversation_id, role, content, personality_id)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, role, content, self.personality_id),
            )
