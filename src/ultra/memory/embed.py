from __future__ import annotations

import math
import os
import struct
from pathlib import Path
from typing import Protocol, Sequence

import httpx

# fastembed model ids (ONNX, baked into Linux Ultra image)
FASTEMBED_MODEL_MAP = {
    "nomic-embed-text": "nomic-ai/nomic-embed-text-v1.5-Q",
    "nomic-embed-text-q": "nomic-ai/nomic-embed-text-v1.5-Q",
    "nomic-embed-text-v1.5": "nomic-ai/nomic-embed-text-v1.5",
    "nomic-embed-text-v1.5-q": "nomic-ai/nomic-embed-text-v1.5-Q",
    "nomic-ai/nomic-embed-text-v1.5": "nomic-ai/nomic-embed-text-v1.5",
    "nomic-ai/nomic-embed-text-v1.5-Q": "nomic-ai/nomic-embed-text-v1.5-Q",
}


def serialize_embedding(vec: Sequence[float]) -> bytes:
    dim = len(vec)
    out = struct.pack("<I", dim)
    for v in vec:
        out += struct.pack("<f", float(v))
    return out


def deserialize_embedding(blob: bytes | None) -> list[float] | None:
    if not blob or len(blob) < 4:
        return None
    dim = struct.unpack("<I", blob[:4])[0]
    if dim == 0 or dim > 4096:
        return None
    need = 4 + dim * 4
    if len(blob) < need:
        return None
    vec: list[float] = []
    for i in range(dim):
        off = 4 + i * 4
        vec.append(struct.unpack("<f", blob[off : off + 4])[0])
    return vec


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_one(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/api/embed"
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json={"model": self.model, "input": texts})
            resp.raise_for_status()
            data = resp.json()
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise ValueError("Ollama embed response missing embeddings")
        return embeddings

    def embed_one(self, text: str) -> list[float]:
        result = self.embed([text])
        if not result:
            raise ValueError("empty embedding")
        return result[0]


class FastEmbedder:
    """Built-in ONNX embeddings — no Ollama install required."""

    def __init__(self, model: str, cache_dir: Path | None = None) -> None:
        from fastembed import TextEmbedding

        resolved = FASTEMBED_MODEL_MAP.get(model, model)
        if cache_dir:
            os.environ["FASTEMBED_CACHE_PATH"] = str(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = TextEmbedding(model_name=resolved)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return [list(vec) for vec in self._model.embed(texts)]

    def embed_one(self, text: str) -> list[float]:
        vectors = self.embed([text])
        if not vectors:
            raise ValueError("empty embedding")
        return vectors[0]


def create_embedder(
    *,
    backend: str,
    model: str,
    ollama_url: str,
    cache_dir: Path | None = None,
) -> Embedder:
    if backend == "ollama":
        return OllamaEmbedder(ollama_url, model)
    if backend == "fastembed":
        return FastEmbedder(model, cache_dir=cache_dir)
    raise ValueError(f"Unknown embed backend: {backend}")


def preload_fastembed_model(model: str = "nomic-embed-text", cache_dir: Path | None = None) -> None:
    """Download/cache ONNX weights (image build + first-boot)."""
    embedder = create_embedder(
        backend="fastembed",
        model=model,
        ollama_url="",
        cache_dir=cache_dir,
    )
    embedder.embed_one("Linux Ultra memory anchor warmup")
