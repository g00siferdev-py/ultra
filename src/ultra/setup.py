from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import click
import yaml

from ultra.config import OLLAMA_CLOUD_BASE_URL, OLLAMA_DEFAULT_BASE_URL
from ultra.notify import send_discord, send_telegram, telegram_recent_chats

SETUP_FLAG_PROD = Path("/var/lib/ultra/setup-complete")
SETUP_FLAG_DEV = Path(".ultra-setup-complete")
CONFIG_PROD = Path("/etc/ultra/config.yaml")
CONFIG_DEV = Path("config.local.yaml")

DEFAULT_CLOUD_MODEL = "kimi-k2.5:cloud"


def setup_flag_path(*, prod: bool) -> Path:
    return SETUP_FLAG_PROD if prod else SETUP_FLAG_DEV


def config_output_path(*, prod: bool, override: Path | None) -> Path:
    if override:
        return override
    return CONFIG_PROD if prod else CONFIG_DEV


def is_setup_complete(*, prod: bool = False) -> bool:
    flag = setup_flag_path(prod=prod)
    if flag.is_file():
        return True
    # Dev: existing config counts as set up unless --force
    if not prod and CONFIG_DEV.is_file():
        return True
    if prod and CONFIG_PROD.is_file():
        with CONFIG_PROD.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return bool(raw.get("api_key") or os.environ.get("OLLAMA_API_KEY"))
    return False


def mark_setup_complete(*, prod: bool) -> None:
    flag = setup_flag_path(prod=prod)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("ok\n", encoding="utf-8")


def build_config_dict(
    *,
    api_key: str,
    model: str,
    ollama_base_url: str,
    discord_webhook: str,
    telegram_token: str,
    telegram_chat_id: str,
    prod: bool,
) -> dict[str, Any]:
    if prod:
        workspace = "/var/ultra/workspace"
        tasks_dir = "/etc/ultra/tasks"
        audit_log = "/var/log/ultra/audit.log"
    else:
        workspace = "workspace"
        tasks_dir = "tasks"
        audit_log = "logs/audit.log"

    return {
        "provider": "ollama",
        "api_key": api_key,
        "model": model,
        "ollama_base_url": ollama_base_url,
        "workspace": workspace,
        "tasks_dir": tasks_dir,
        "audit_log": audit_log,
        "extra_instructions": "",
        "channels": {
            "telegram": {
                "bot_token": telegram_token,
                "chat_id": telegram_chat_id,
            },
            "discord": {
                "webhook_url": discord_webhook,
            },
            "email": {
                "smtp_host": "",
                "smtp_port": 587,
                "username": "",
                "password": "",
                "from": "ultra@local",
                "to": "",
            },
        },
    }


def write_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def _test_ollama(api_key: str, model: str, base_url: str) -> tuple[bool, str]:
    from ultra.config import ChannelsConfig, Config as ConfigCls
    from ultra.llm.factory import create_provider

    cfg = ConfigCls(
        provider="ollama",
        api_key=api_key,
        model=model,
        workspace=Path("workspace"),
        audit_log=Path("logs/audit.log"),
        extra_instructions="",
        channels=ChannelsConfig(),
        ollama_base_url=base_url,
        tasks_dir=Path("tasks"),
    )
    try:
        provider = create_provider(cfg)
        turn = provider.chat([{"role": "user", "content": "Reply with OK only."}], [])
        text = (turn.content or "").strip()[:60]
        return True, text or "(connected)"
    except Exception as exc:
        return False, str(exc)


def run_wizard(*, prod: bool, output: Path, force: bool) -> None:
    if is_setup_complete(prod=prod) and not force:
        click.echo("Setup already complete. Use --force to run again.")
        return

    click.echo("")
    click.echo("=" * 50)
    click.echo("  Linux Ultra - First Boot Setup")
    click.echo("=" * 50)
    click.echo("")
    click.echo("This wizard configures your Ollama API key and alert channels.")
    click.echo("Press Enter to accept defaults shown in [brackets].")
    click.echo("")

    # --- LLM ---
    click.echo("--- Ollama (AI brain) ---")
    click.echo("Get an API key at https://ollama.com/settings/keys")
    api_key = click.prompt("Ollama API key", hide_input=True)
    if not api_key.strip():
        raise click.ClickException("Ollama API key is required.")

    model = click.prompt("Model", default=DEFAULT_CLOUD_MODEL)
    base_url = OLLAMA_CLOUD_BASE_URL if ":cloud" in model else OLLAMA_DEFAULT_BASE_URL
    if api_key and ":cloud" in model:
        base_url = OLLAMA_CLOUD_BASE_URL

    click.echo("Testing connection to Ollama...")
    ok, msg = _test_ollama(api_key.strip(), model.strip(), base_url)
    if ok:
        click.echo(f"  Connected: {msg}")
    else:
        click.echo(f"  Warning: connection test failed: {msg}")
        if not click.confirm("Save config anyway?", default=False):
            raise click.ClickException("Setup cancelled.")

    click.echo("")

    # --- Discord ---
    click.echo("--- Discord alerts (optional) ---")
    click.echo("Create a webhook: Channel Settings -> Integrations -> Webhooks")
    discord_webhook = ""
    if click.confirm("Configure Discord webhook?", default=False):
        discord_webhook = click.prompt("Webhook URL").strip()

    click.echo("")

    # --- Telegram ---
    click.echo("--- Telegram alerts (optional) ---")
    click.echo("Create a bot: message @BotFather on Telegram, send /newbot")
    telegram_token = ""
    telegram_chat_id = ""
    if click.confirm("Configure Telegram?", default=False):
        telegram_token = click.prompt("Bot token", hide_input=True).strip()
        if telegram_token:
            click.echo("Open Telegram, find your bot, send it: hello")
            click.pause("Press Enter when done...")
            lookup = telegram_recent_chats(telegram_token)
            if lookup.success:
                click.echo(lookup.output)
                telegram_chat_id = click.prompt("Your chat_id").strip()
            else:
                click.echo(lookup.output)
                telegram_chat_id = click.prompt("Enter chat_id manually").strip()

    data = build_config_dict(
        api_key=api_key.strip(),
        model=model.strip(),
        ollama_base_url=base_url,
        discord_webhook=discord_webhook,
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        prod=prod,
    )

    write_config(output, data)
    click.echo("")
    click.echo(f"Config saved to {output}")

    # Test notifications
    if discord_webhook:
        result = send_discord(
            {"webhook_url": discord_webhook},
            "Linux Ultra setup complete. Alerts are working.",
            title="Ultra",
        )
        click.echo(f"Discord test: {result.output}")

    if telegram_token and telegram_chat_id:
        result = send_telegram(
            {"bot_token": telegram_token, "chat_id": telegram_chat_id},
            "Linux Ultra setup complete. Alerts are working.",
            title="Ultra",
        )
        click.echo(f"Telegram test: {result.output}")

    mark_setup_complete(prod=prod)
    click.echo("")
    click.echo("Setup complete. Start chatting with:")
    click.echo("  python -m ultra chat")
    click.echo("")
