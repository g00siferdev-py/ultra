# Linux Ultra

**Linux Ultra** is an AI-driven Linux distribution for the Raspberry Pi 5. Connect your LLM API key, and an orchestrator agent has full control of the OS — running shell commands, managing files, calling REST APIs, and sending you alerts. Built for always-on home automation and orchestration, not a traditional desktop experience.

```
You (chat / voice / alerts)  <->  ultra-agent  <->  OS (shell, apt, systemd, APIs)
```

## Features

- **Orchestrator agent** — LLM composes OS primitives instead of bespoke per-integration tools
- **Multi-provider LLM** — Ollama Cloud (default), OpenAI, Anthropic
- **Primitive tools** — shell, files, HTTP, notifications
- **Scheduled background tasks** — proactive disk checks, briefings, alerts via systemd
- **First-boot wizard** — `ultra setup` for API key and Discord/Telegram
- **Flashable Pi 5 image** — Debian Bookworm arm64, built locally or via GitHub Actions
- **Discord webhooks** — outbound alerts (one-way)

## Quick start (development)

Requires Python 3.11+.

```bash
git clone https://github.com/g00siferdev-py/ultra.git
cd ultra
pip install -e .

cp config.example.yaml config.local.yaml
# Edit: api_key, model, ollama_base_url (see docs/CONFIGURATION.md)

python -m ultra doctor
python -m ultra setup          # interactive wizard (optional)
python -m ultra chat
```

## CLI reference

| Command | Description |
|---------|-------------|
| `ultra chat` | Interactive agent session |
| `ultra run "task"` | Single headless task |
| `ultra setup` | First-boot wizard |
| `ultra setup --prod` | Wizard using Pi paths (`/etc/ultra/config.yaml`) |
| `ultra setup-status` | Check if setup is complete |
| `ultra doctor` | Verify config and Ollama connectivity |
| `ultra tasks list` | List scheduled background tasks |
| `ultra tasks run <id> --force` | Run a task now |
| `ultra tasks run-due` | Run all due tasks (systemd calls this) |
| `ultra channels test discord` | Send a test Discord message |
| `ultra channels telegram-id` | Look up your Telegram chat_id |
| `ultra image info` | How to build and flash the Pi image |

## Raspberry Pi 5 (Linux Ultra image)

No local Linux machine required — use **GitHub Actions** to build the image.

1. Push this repo to GitHub (or fork it).
2. **Actions** → **Build Linux Ultra Pi Image** → **Run workflow**.
3. Download artifact `linux-ultra-pi5-1.0.img.xz`.
4. Decompress: `xz -dk linux-ultra-pi5-1.0.img.xz`
5. Flash with [Raspberry Pi Imager](https://www.raspberrypi.com/software/) → **Use custom**.
6. Boot Pi 5 from NVMe, SSH: `ssh ultra@ultra.local` (default password `ultra`, change on first login).
7. Run `ultra setup --prod`, then `ultra chat`.

See [docs/BUILD.md](docs/BUILD.md) for local builds and flashing details.

Tag a release to attach the image automatically:

```bash
git tag v1.0.0 && git push origin v1.0.0
```

## Configuration

Copy `config.example.yaml` to `config.local.yaml` (dev) or use `ultra setup --prod` on the Pi.

| Section | Purpose |
|---------|---------|
| `provider`, `api_key`, `model` | LLM (Ollama Cloud uses `api_key` + `https://ollama.com/v1`) |
| `channels.discord` | Outbound webhook alerts |
| `channels.telegram` | Outbound Telegram alerts |
| `tasks/` | Scheduled background task definitions |

Full details: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

## Architecture

```
┌─────────────────────────────────────────┐
│  ultra chat / systemd timers / (voice)  │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  ultra-agent (tool loop + audit log)    │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  run_shell · files · http · notify      │
└──────────────────┬──────────────────────┘
                   │
┌──────────────────▼──────────────────────┐
│  Debian Bookworm arm64 (Pi 5)           │
└─────────────────────────────────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Roadmap

| Milestone | Status |
|-----------|--------|
| M1 — Agent + primitive tools | Done |
| M2 — Scheduled background tasks | Done |
| M3 — First-boot setup wizard | Done |
| M4 — Flashable Pi 5 image + GitHub Actions | Done |
| M5 — Smart home scaffolding (Home Assistant, lights, TV) | Planned |
| M6 — Voice (Bluetooth mic/speaker, Alexa-style) | Planned |

## Project layout

```
ultra/
├── src/ultra/          # Agent, CLI, LLM adapters, notifications
├── tasks/              # Scheduled task YAML definitions
├── deploy/             # systemd units, first-boot scripts
├── iso/                # Pi image build (debootstrap + overlay)
├── .github/workflows/  # CI image build
└── docs/               # Documentation
```

## Security

- The agent is designed with broad OS access. Run on a dedicated homelab Pi, not your primary PC.
- Never commit `config.local.yaml` — it contains API keys. Use `config.example.yaml` as a template.
- Discord webhooks are one-way; treat webhook URLs as secrets.

## License

[MIT](LICENSE)
