from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ultra.config import Config
from ultra.memory.embed import Embedder, create_embedder
from ultra.memory.recall import RecallBundle, format_recall_for_prompt, hybrid_recall
from ultra.memory.store import MemoryStore
from ultra.notify import send_discord, send_telegram

# Reuse loaded ONNX model across timer ticks (avoid reload every 2 min on Pi)
_EMBEDDER_CACHE: dict[str, Embedder] = {}


def _embedder_cache_key(config: Config) -> str:
    m = config.memory
    cache = m.resolve_embed_cache_dir(config.workspace)
    return f"{m.embed_backend}:{m.embed_model}:{cache}"


def get_cached_embedder(config: Config) -> Embedder | None:
    if not config.memory.semantic_enabled:
        return None
    key = _embedder_cache_key(config)
    if key not in _EMBEDDER_CACHE:
        m = config.memory
        _EMBEDDER_CACHE[key] = create_embedder(
            backend=m.embed_backend,
            model=m.embed_model,
            ollama_url=m.embed_ollama_url,
            cache_dir=m.resolve_embed_cache_dir(config.workspace),
        )
    return _EMBEDDER_CACHE[key]


class MemoryService:
    def __init__(
        self,
        config: Config,
        *,
        startup_embed: bool = False,
        personality_id: str | None = None,
    ) -> None:
        self.config = config
        self.cfg = config.memory
        self._store: MemoryStore | None = None
        pid = personality_id or config.memory.personality_id
        if self.cfg.enabled:
            embedder = get_cached_embedder(config) if self.cfg.semantic_enabled else None
            self._store = MemoryStore(
                self.cfg.resolve_db_path(config.workspace),
                personality_id=pid,
                embedder=embedder,
                semantic_enabled=self.cfg.semantic_enabled,
            )
            if startup_embed and self.cfg.auto_embed and embedder:
                if self._store.count_pending_embeddings():
                    self.embed_catchup()

    def embed_tick(self) -> int:
        """Embed one batch — fast, for frequent Pi timer (every 2 min)."""
        if not self._store or not self.cfg.auto_embed:
            return 0
        return self._store.embed_pending(limit=self.cfg.embed_batch_size)

    def embed_catchup(self) -> int:
        """Embed several batches on startup without blocking for hours."""
        if not self._store or not self.cfg.auto_embed:
            return 0
        total = 0
        for _ in range(self.cfg.embed_startup_batches):
            n = self.embed_tick()
            if n == 0:
                break
            total += n
        return total

    def embed_pending(self) -> int:
        """Embed all pending anchors (manual catch-up / reindex helper)."""
        if not self._store or not self.cfg.auto_embed:
            return 0
        return self._store.embed_pending_until_done(batch_size=self.cfg.embed_batch_size)

    def reindex_all(self) -> tuple[int, int]:
        if not self._store:
            raise RuntimeError("memory is disabled")
        self._store.clear_all_embeddings()
        embedded = self._store.embed_pending_until_done(batch_size=self.cfg.embed_batch_size)
        total = self._store.count_embedded()
        return embedded, total

    def pending_count(self) -> int:
        if not self._store:
            return 0
        return self._store.count_pending_embeddings()

    def check_backlog_alert(self) -> None:
        """Notify user if embed backlog is growing (once per hour max)."""
        if not self._store or self.cfg.embed_backlog_alert <= 0:
            return
        pending = self.pending_count()
        if pending < self.cfg.embed_backlog_alert:
            return

        marker = self.cfg.resolve_embed_cache_dir(self.config.workspace).parent / "last-backlog-alert.json"
        now = time.time()
        if marker.is_file():
            try:
                last = json.loads(marker.read_text(encoding="utf-8")).get("ts", 0)
                if now - float(last) < 3600:
                    return
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        msg = (
            f"Memory embed backlog: {pending} anchors waiting. "
            f"Run: ultra memory embed-pending (or wait for the 2-min embed timer)."
        )
        ch = self.config.channels
        if ch.discord.get("webhook_url"):
            send_discord(ch.discord, msg, title="Ultra memory backlog")
        elif ch.telegram.get("bot_token"):
            send_telegram(ch.telegram, msg, title="Ultra memory backlog")

        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"ts": now, "pending": pending, "at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )

    @property
    def enabled(self) -> bool:
        return self._store is not None

    @property
    def db_path(self) -> Path | None:
        return self._store.db_path if self._store else None

    def recall(self, query: str, *, limit: int | None = None) -> RecallBundle:
        if not self._store:
            return RecallBundle(anchors=[])
        limit = limit or self.cfg.recall_limit
        query_emb = None
        if self.cfg.semantic_enabled and self._store.embedder:
            try:
                query_emb = self._store.embedder.embed_one(query)
            except Exception:
                query_emb = None
        return hybrid_recall(self._store, query, anchor_limit=limit, query_embedding=query_emb)

    def recall_context(self, query: str) -> str:
        return format_recall_for_prompt(self.recall(query))

    def remember(
        self,
        content: str,
        *,
        anchor_type: str = "fact",
        importance: int = 3,
    ) -> str:
        if not self._store:
            raise RuntimeError("memory is disabled")
        anchor_id = self._store.remember(content, anchor_type=anchor_type, importance=importance)
        if self.cfg.auto_embed:
            self.embed_tick()
        return anchor_id

    def after_turn(self, user: str, assistant: str) -> None:
        if not self._store or not self.cfg.auto_store:
            return
        self._store.store_message("user", user)
        self._store.store_message("assistant", assistant)
        if len(user.strip()) > 20:
            self._store.remember(
                f"User said: {user.strip()[:500]}",
                anchor_type="raw",
                importance=2,
                embed=False,
            )
        if len(assistant.strip()) > 40:
            self._store.remember(
                f"Assistant noted: {assistant.strip()[:500]}",
                anchor_type="curated",
                importance=2,
                embed=False,
            )
        if self.cfg.auto_embed:
            for _ in range(2):
                if self.embed_tick() == 0:
                    break
