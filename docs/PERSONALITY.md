# Companion personality

Linux Ultra uses the same **`personality.json`** format as [Persistent Sage](https://github.com/g00siferdev-py/persistent-sage).

## What it does

| Piece | Role |
|-------|------|
| `personality.json` | Saved persona fields (tone, values, name, etc.) |
| System prompt | Generated from the active profile and prepended before orchestrator instructions |
| `personality_get` / `personality_update` | Agent tools to read and edit the file |
| Memory `personality_id` | Aligned with the active profile id (separate memory namespaces per profile) |

The chat LLM does **not** fine-tune from conversation. Personality changes update the **instructions** it sees on each turn (immediately after `personality_update` in the same chat).

## Default location

| Environment | Path |
|-------------|------|
| Dev | `workspace/personality.json` |
| Pi | `/var/ultra/workspace/personality.json` |
| Shared with PS | `$PERSISTENT_SAGE_DATA_DIR/personality.json` if present |

Override with `personality.path` in config.

## JSON shape (Persistent Sage compatible)

```json
{
  "version": 1,
  "activeProfileId": "ultra",
  "profiles": [
    {
      "id": "ultra",
      "profileName": "Ultra",
      "companionName": "Ultra",
      "corePersonality": "...",
      "toneOfVoice": "...",
      "backgroundStory": "...",
      "coreValues": "...",
      "relationshipStyle": "...",
      "specialInstructions": "...",
      "avatarDescription": null
    }
  ]
}
```

## Customize

**Interactive wizard** (recommended):

```bash
python -m ultra menu                    # Main menu → 3) Personality
python -m ultra personality menu
python -m ultra personality customize     # walk through all sections
python -m ultra personality customize --pick   # edit one section
```

During customize:

| Input | Action |
|-------|--------|
| **Enter** | Keep current value |
| **e** | Open text editor (best for long sections) |
| **c** | Clear / leave blank (optional fields only) |
| **0** or **Ctrl+C** | Back to previous section or menu |

`ultra setup` can optionally launch the wizard after first-boot config.

**In chat** (like Persistent Sage):

> "Be more playful and call yourself Nova. Update your personality."

The agent should call `personality_update` with only the fields that change.

**CLI (view):**

```bash
ultra personality show
ultra personality show --prompt   # generated system prompt
ultra personality path
```

## Config

```yaml
personality:
  enabled: true
  path: ""
  persistent_sage_compat: true
```

Set `enabled: false` to skip persona injection and hide personality tools (orchestrator-only mode).

## Sharing with Persistent Sage desktop

Point both apps at the same data directory (`PERSISTENT_SAGE_DATA_DIR`) or copy `personality.json`. Use matching `activeProfileId` and memory `personality_id` / profile id so memory anchors stay in the same namespace.

Do not run both apps as writers on the same DB at the same time.
