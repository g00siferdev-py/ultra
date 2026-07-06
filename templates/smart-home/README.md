# Smart home (Linux Ultra)

This folder holds device discovery results and integration configs for your home.

## Network discovery

Scan the LAN for hosts and smart-home services (Home Assistant, Chromecast, MQTT, etc.):

```bash
ultra discover network --save
```

Results are saved to **`discovered.json`** in this directory. The agent can also run
the `network_discover` tool during chat.

After discovery:

1. On Linux Ultra Pi, Home Assistant is bundled at **http://127.0.0.1:8123**
2. Save a long-lived token to `secrets/ha-token.txt`
3. Ask the agent to control devices via the `home_assistant` tool

## Layout

```
smart-home/
  discovered.json     # last network scan (auto-generated)
  secrets/            # tokens and passwords (keep private)
  scripts/            # helper scripts the agent maintains
```

## Example agent prompts

- "Scan the network and tell me if Home Assistant is running."
- "Save discovery results and summarize what you found."
- "Connect to Home Assistant at the IP from discovered.json" (after you add a token)
