# Roadmap

## Completed

### M1 — Agent core
- Python orchestrator with tool-calling loop
- Primitive tools: shell, files, HTTP, notify
- Ollama Cloud, OpenAI, Anthropic providers
- Audit logging

### M2 — Background tasks
- YAML task definitions in `tasks/`
- `ultra tasks run-due` + systemd timer
- Headless system prompt for autonomous operation

### M3 — First-boot wizard
- `ultra setup` / `ultra setup --prod`
- Ollama API key, model, Discord/Telegram setup
- Connection and notification tests

### M4 — Linux Ultra image
- Debian Bookworm arm64 + Pi 5 kernel
- debootstrap build pipeline (`iso/build.sh`)
- GitHub Actions CI build + artifact upload
- Auto-expand root partition on first boot
- Branding (`/etc/os-release`, hostname `ultra`)

### M4.5 — Memory Anchor (Persistent Sage RAG)
- Hybrid FTS + semantic recall (fastembed ONNX on Pi)
- `memory_search` / `memory_remember` tools
- Frequent embed timer (anti-backlog on Pi)
- Personality JSON + self-edit tools
- CLI navigation menu

### M5 — Smart home (mostly done)
- Bundled Home Assistant (Docker) on Pi image
- Network discovery (`ultra discover`, `network_discover` tool)
- `home_assistant` agent tool + config-driven integration prompts
- Example tasks: `morning-briefing`, `evening-lights`
- HA token step in `ultra setup`

## Planned

### M5 polish (remaining)
- Pi image rebuild + on-device validation
- Enable tasks after user has HA entities configured

### M6 — Voice interface
- Bluetooth speaker + mic (PipeWire, BlueZ)
- Speech-to-text and text-to-speech
- Wake word or push-to-talk
- Alexa-style: "Turn on the lights and TV", spoken weather replies

### Future enhancements
- Two-way Discord/Telegram bot listeners
- Web UI for chat
- Local Ollama on LAN as fallback
- Confirm mode for destructive commands (optional safety layer)
