# Configuration

Linux Ultra reads config from (first match wins):

1. `ULTRA_CONFIG` environment variable
2. `config.local.yaml` (development)
3. `~/.ultra/config.yaml`
4. `/etc/ultra/config.yaml` (Pi production)

## LLM (Ollama Cloud — recommended)

```yaml
provider: ollama
api_key: "your-key-from-https://ollama.com/settings/keys"
model: kimi-k2.5:cloud
ollama_base_url: "https://ollama.com/v1"
```

Also reads `OLLAMA_API_KEY` from the environment.

For **local** Ollama (no API key):

```yaml
provider: ollama
api_key: ""
model: llama3.1
ollama_base_url: "http://localhost:11434/v1"
```

## OpenAI / Anthropic

```yaml
provider: openai   # or anthropic
api_key: "sk-..."
model: gpt-4o
```

## Notification channels

These are **outbound only** — Ultra sends alerts to you. They are not used to talk to the LLM.

### Discord (webhook — easiest)

1. Discord server → channel → **Settings** → **Integrations** → **Webhooks** → **New Webhook**
2. Copy the URL into config:

```yaml
channels:
  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
```

Test: `python -m ultra channels test discord`

### Telegram

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token.
2. Message your bot `hello` on Telegram.
3. Run `python -m ultra channels telegram-id` to find your `chat_id`.

```yaml
channels:
  telegram:
    bot_token: "123456:ABC..."
    chat_id: "987654321"
```

Test: `python -m ultra channels test telegram`

## Paths (production / Pi)

When using `ultra setup --prod`:

| Setting | Path |
|---------|------|
| Config | `/etc/ultra/config.yaml` |
| Workspace | `/var/ultra/workspace` |
| Tasks | `/etc/ultra/tasks` |
| Audit log | `/var/log/ultra/audit.log` |

## Scheduled tasks

Task files live in `tasks/` (dev) or `/etc/ultra/tasks` (Pi). Example:

```yaml
id: disk-monitor
enabled: true
schedule:
  type: interval
  minutes: 360
prompt: |
  Check disk usage. If any mount is above 85% full,
  send_notification via discord with a short alert.
  If fine, reply NO_ACTION.
```

Enable the systemd timer on Pi: `sudo systemctl enable --now ultra-tasks.timer`
