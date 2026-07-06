# Memory Anchor (Persistent Sage integration)

Linux Ultra includes **Memory Anchor** — hybrid FTS + semantic RAG, compatible with [Persistent Sage](https://github.com/g00siferdev-py/persistent-sage).

## Baked-in embeddings (no Ollama required)

On the **Linux Ultra Pi image**, memory embeddings are **pre-installed**:

| Component | Detail |
|-----------|--------|
| Engine | `fastembed` (ONNX, runs on CPU) |
| Model | `nomic-embed-text-v1.5` (~130 MB) |
| Cache | `/var/lib/ultra/fastembed` (preloaded at image build) |
| Fallback | `ultra-embed-preload.service` on first boot if build preload missed |

Users do **not** need to install Ollama or run `ollama pull` for memory.

Chat/reasoning still uses your cloud LLM (Ollama Cloud API key, etc.).

## Split brain

| Role | Provider |
|------|----------|
| **Chat / reasoning** | Ollama Cloud, OpenAI, or Anthropic |
| **Memory embeddings** | **fastembed** (baked in) or optional `ollama` backend |

## Configuration

```yaml
memory:
  enabled: true
  embed_backend: fastembed   # default on Linux Ultra
  embed_model: nomic-embed-text
  embed_cache_dir: /var/lib/ultra/fastembed
```

### Optional: Ollama for embeddings (dev)

```yaml
memory:
  embed_backend: ollama
  embed_ollama_url: "http://127.0.0.1:11434"
  embed_model: nomic-embed-text
```

## Dev machine setup

First run downloads the ONNX model to `workspace/memory/fastembed/`:

```bash
pip install -e .
python -m ultra memory preload
python -m ultra memory status
```

## Share memory with Persistent Sage desktop

Set `PERSISTENT_SAGE_DATA_DIR` or point `memory.database` at `nova_memory.sqlite`.
Use `personality_id: default` to match your PS companion.

Do not run Persistent Sage and Ultra writers on the same DB simultaneously.

## Automatic embedding (backlog prevention)

On light hardware (Pi 5), embed backlogs can take **hours** to clear if anchors pile up.
Ultra embeds **little and often** instead of large rare batches.

| Trigger | Behavior |
|---------|----------|
| **Every 2 minutes** | `ultra-memory-embed.timer` — one batch of 8 anchors |
| **After each chat turn** | Up to 2 embed batches immediately |
| **New `memory_remember`** | One embed batch right away |
| **Agent startup** | Up to 3 batches (won't block chat for hours) |
| **Backlog > 50** | Discord/Telegram alert (hourly max) |

Default embed model is **quantized** (`nomic-embed-text-v1.5-Q`) for faster CPU inference on Pi.

```yaml
memory:
  embed_model: nomic-embed-text-q
  embed_batch_size: 8
  embed_backlog_alert: 50
```

### Manual catch-up

```bash
ultra memory status
ultra memory embed-tick      # one batch (same as timer)
ultra memory embed-pending   # loop until backlog cleared
ultra memory reindex         # full clear + re-embed
```

Disable background embed: `memory.auto_embed: false`

## CLI

```bash
ultra memory status
ultra memory preload      # dev only
ultra memory search "thermostat preference"
```

See also [CONFIGURATION.md](CONFIGURATION.md).
