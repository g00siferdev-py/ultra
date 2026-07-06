# Smart home on Linux Ultra

Linux Ultra ships with **Home Assistant** in Docker, managed by systemd.

## Architecture

```
Ultra agent  →  home_assistant tool  →  HA REST API (:8123)  →  your devices
```

Ultra orchestrates; Home Assistant integrates devices (Zigbee, Wi‑Fi, Matter, etc.).

## First boot (Pi image)

1. Flash the Linux Ultra image and boot the Pi
2. Wait for Home Assistant to download (10–20 min on first boot, needs network)
3. Open **http://ultra.local:8123** and complete HA onboarding
4. Run **`ultra setup --prod`** for the LLM API key
5. Create a **long-lived access token** in HA → Profile → Security
6. Save the token:

```bash
mkdir -p /var/ultra/workspace/projects/smart-home/secrets
nano /var/ultra/workspace/projects/smart-home/secrets/ha-token.txt
```

7. Verify: **`ultra ha status`**

## CLI

```bash
ultra ha status    # container + API check
ultra ha url       # print web UI URL
ultra discover network --save
```

## Agent tools

| Tool | Use |
|------|-----|
| `home_assistant` | `status`, `states`, `state`, `call_service` |
| `network_discover` | Find HA and other devices on LAN |

Example chat: *"Turn off all lights"* → agent calls `home_assistant` with `light.turn_off`.

## Config (`/etc/ultra/config.yaml`)

```yaml
smart_home:
  home_assistant:
    enabled: true
    url: "http://127.0.0.1:8123"
    token_file: "/var/ultra/workspace/projects/smart-home/secrets/ha-token.txt"
```

Or set `HA_TOKEN` env var.

## systemd services

| Unit | Role |
|------|------|
| `ultra-homeassistant-pull.service` | One-shot Docker image pull |
| `ultra-homeassistant.service` | Runs HA container (host network) |

Manual control:

```bash
sudo systemctl status ultra-homeassistant
sudo ultra-homeassistant status
```

## Data

- HA config: `/var/lib/homeassistant`
- Ultra workspace: `/var/ultra/workspace/projects/smart-home/`

## Dev machines (Windows)

Home Assistant is **not** installed locally — only on the Pi image. Dev agents can point `smart_home.home_assistant.url` at a remote HA instance if you have one.
