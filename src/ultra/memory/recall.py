from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass

from ultra.memory.embed import cosine_similarity, deserialize_embedding
from ultra.memory.store import SHARED_PERSONALITY_ID, MemoryStore, StoredAnchor

STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have he her his i if in into is it its me my "
    "of on or our she that the their them they this to was we were what when which who will with you your".split()
)

SEMANTIC_MIN_SIM = 0.28


@dataclass
class RecallBundle:
    anchors: list[StoredAnchor]


def _tokenize(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[a-z0-9]{2,}", text.lower())
    out: list[str] = []
    for w in words:
        if w in STOPWORDS:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def _escape_like(s: str) -> str:
    return s.replace("%", "\\%").replace("_", "\\_")


def hybrid_recall(
    store: MemoryStore,
    query: str,
    *,
    anchor_limit: int = 8,
    query_embedding: list[float] | None = None,
) -> RecallBundle:
    q = query.strip()
    if not q:
        return RecallBundle(anchors=[])

    terms = _tokenize(q)
    personality = store.personality_id
    scores: dict[str, float] = {}

    with store._connect() as conn:
        if store._table_exists(conn, "anchors_fts") and terms:
            match_expr = " OR ".join(f'"{t}"' for t in terms[:12])
            try:
                rows = conn.execute(
                    f"""SELECT anchor_id, bm25(anchors_fts) AS rank
                        FROM anchors_fts
                        WHERE anchors_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?""",
                    (match_expr, anchor_limit * 3),
                ).fetchall()
                for row in rows:
                    aid = row["anchor_id"]
                    bm = float(row["rank"])
                    scores[aid] = scores.get(aid, 0.0) + (-bm) + 2.0
            except sqlite3.Error:
                pass

        for term in [q] + terms:
            tpat = f"%{_escape_like(term)}%"
            rows = conn.execute(
                """SELECT id, content, anchor_type, importance, created_at, conversation_id
                   FROM anchors
                   WHERE content LIKE ? ESCAPE '\\'
                     AND personality_id IN (?, ?)
                   LIMIT ?""",
                (tpat, personality, SHARED_PERSONALITY_ID, anchor_limit * 3),
            ).fetchall()
            for row in rows:
                bump = 1.2 + math.log1p(int(row["importance"])) * 0.35
                scores[row["id"]] = scores.get(row["id"], 0.0) + bump

        if query_embedding:
            rows = conn.execute(
                """SELECT id, content, anchor_type, importance, created_at, conversation_id, embedding
                   FROM anchors
                   WHERE embedding IS NOT NULL
                     AND personality_id IN (?, ?)
                   LIMIT ?""",
                (personality, SHARED_PERSONALITY_ID, anchor_limit * 8),
            ).fetchall()
            for row in rows:
                vec = deserialize_embedding(row["embedding"])
                if not vec:
                    continue
                sim = cosine_similarity(query_embedding, vec)
                if sim < SEMANTIC_MIN_SIM:
                    continue
                bump = sim * 10.0 + 1.5
                scores[row["id"]] = scores.get(row["id"], 0.0) + bump

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:anchor_limit]
        anchors: list[StoredAnchor] = []
        for aid, _ in ranked:
            row = conn.execute(
                """SELECT id, content, anchor_type, importance, created_at, conversation_id
                   FROM anchors WHERE id = ?""",
                (aid,),
            ).fetchone()
            if row:
                anchors.append(
                    StoredAnchor(
                        id=row["id"],
                        content=row["content"],
                        anchor_type=row["anchor_type"],
                        importance=int(row["importance"]),
                        created_at=row["created_at"],
                        conversation_id=row["conversation_id"],
                    )
                )

    return RecallBundle(anchors=anchors)


def format_recall_for_prompt(bundle: RecallBundle, max_chars: int = 4000) -> str:
    if not bundle.anchors:
        return ""
    lines = ["## Long-term memory (Memory Anchor)", ""]
    for a in bundle.anchors:
        lines.append(f"- [{a.anchor_type}] {a.content}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n... (truncated)"
    return text
