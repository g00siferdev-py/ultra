# Architecture

## Design philosophy

Linux Ultra is **agent-native**: the LLM orchestrates the OS through a small set of **primitives** (shell, files, HTTP, notifications), not hundreds of domain-specific tools.

```
User intent
    → LLM (plan + tool calls)
    → OS primitives
    → Composed outcome (smart home, scripts, alerts, packages)
```

Reusable work persists under `workspace/` (dev) or `/var/ultra/workspace` (Pi) as scripts and project configs the agent maintains over time.

## Agent loop

`ultra-agent` runs a standard tool-calling loop:

1. User message (or scheduled task prompt) enters the conversation.
2. LLM returns text and/or tool calls.
3. Tools execute; results append to the conversation.
4. Repeat until the LLM responds without tools or max turns reached.
5. Every tool call is logged to `audit.log`.

### Modes

| Mode | Entry point | System prompt |
|------|-------------|---------------|
| Interactive | `ultra chat` | Full assistant — plans, explains, acts |
| Headless | `ultra run`, `ultra tasks run` | Autonomous — no clarifying questions, `NO_ACTION` when idle |

## Tools

| Tool | Role |
|------|------|
| `run_shell` | Primary control surface — apt, systemctl, curl, scripts |
| `read_file` / `write_file` / `list_directory` | Filesystem and persistence |
| `http_request` | REST APIs (Home Assistant, weather, webhooks) |
| `send_notification` | Discord webhook, Telegram, email |

## LLM providers

Implemented via a thin adapter layer (`src/ultra/llm/`):

- **Ollama** — OpenAI-compatible `/v1` API; cloud uses `Authorization: Bearer` + `https://ollama.com/v1`
- **OpenAI** — native SDK
- **Anthropic** — native SDK with tool-use message format

## Scheduler

YAML task files in `tasks/` define `id`, `schedule`, and `prompt`. `ultra tasks run-due` checks intervals/daily schedules against `.task-state.json` and runs due tasks in headless mode.

On Pi, `ultra-tasks.timer` invokes `run-due` every 5 minutes.

## Image build pipeline

```
debootstrap (bookworm arm64)
    → chroot: Pi kernel, packages, pip install ultra
    → overlay: branding, systemd units
    → partition image (FAT boot + ext4 root)
    → dist/linux-ultra-pi5-1.0.img
```

We do **not** fork Debian's git tree — packages are pulled at build time from Debian and Raspberry Pi apt repositories.

## Planned: voice (M6)

```
Bluetooth mic → STT → ultra-agent → TTS → Bluetooth speaker
```

Same agent core; voice becomes another input/output channel alongside chat and notifications.
