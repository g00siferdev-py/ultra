#!/usr/bin/env python3
"""Pre-download fastembed ONNX model into the image (no Ollama required)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    cache = Path(os.environ.get("FASTEMBED_CACHE_PATH", "/var/lib/ultra/fastembed"))
    model = os.environ.get("ULTRA_EMBED_MODEL", "nomic-embed-text")
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["FASTEMBED_CACHE_PATH"] = str(cache)

    from ultra.memory.embed import preload_fastembed_model

    print(f"Preloading embed model {model} -> {cache}")
    preload_fastembed_model(model=model, cache_dir=cache)
    print("Embed model ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"preload failed: {exc}", file=sys.stderr)
        sys.exit(1)
