"""Interactive CLI navigation menu for Linux Ultra."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import click

from ultra.config import Config


def _pause() -> None:
    click.echo("")
    try:
        click.prompt("Press Enter to continue", default="", show_default=False)
    except (EOFError, KeyboardInterrupt):
        pass


def _pick(title: str, options: list[tuple[str, str]], *, allow_zero: bool = True) -> str | None:
    click.echo("")
    click.echo(title)
    click.echo("-" * len(title))
    for key, label in options:
        click.echo(f"  {key}) {label}")
    if allow_zero:
        click.echo("  0) Back")
    click.echo("  ?) Help for this screen")

    while True:
        try:
            raw = click.prompt("Choice", default="0" if allow_zero else "1").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw in {"?", "help", "h"}:
            click.echo(_screen_help(title, options))
            continue
        if allow_zero and raw in {"0", "back", "b", "q", "quit", "exit"}:
            return None
        for key, _ in options:
            if raw == key:
                return key
        click.echo("Invalid choice — enter a number from the menu or ? for help.")


def _screen_help(title: str, options: list[tuple[str, str]]) -> str:
    lines = [f"Screen: {title}", ""]
    for key, label in options:
        lines.append(f"  {key} — {label}")
    lines.extend(["", "  0 — return to previous menu", "  ? — show this help"])
    return "\n".join(lines)


def print_command_reference() -> None:
    click.echo(
        """
Linux Ultra — command reference
===============================

Interactive
  ultra                    Open navigation menu (same as: ultra menu)
  ultra chat               Chat with the agent
  ultra menu               Numbered navigation menu

Setup & health
  ultra setup [--prod]     First-boot wizard
  ultra setup-status       Check if setup completed
  ultra doctor             Verify config, LLM, memory

Personality (personality.json)
  ultra personality show [--prompt]
  ultra personality path
  ultra personality customize
  ultra personality customize --pick

Memory Anchor
  ultra memory status
  ultra memory search QUERY
  ultra memory embed-tick | embed-pending | reindex | preload

Scheduled tasks
  ultra tasks list | run ID | run-due | install

Notifications
  ultra channels test discord|telegram
  ultra channels telegram-id

Network discovery
  ultra discover network [--save] [--subnet CIDR]
  ultra discover show | path

Home Assistant (Pi image)
  ultra ha status | url

Pi image
  ultra image info

Chat slash commands (inside ultra chat)
  /help  /?                Show chat commands
  exit  quit               Leave chat

Tip: All commands accept --config PATH for a non-default config file.
"""
    )


CHAT_HELP = """Chat commands:
  /help, /?     Show this help
  exit, quit    Leave chat

Everything else is sent to the agent (including personality and memory requests).
"""


def handle_chat_command(text: str) -> str | None:
    """Return help text if input is a chat slash command, else None."""
    cmd = text.strip().lower()
    if cmd in {"/help", "/?", "/help commands", "/commands"}:
        return CHAT_HELP
    return None


def run_interactive_menu(config_path: Path | None = None) -> None:
    try:
        config = Config.load(config_path)
    except FileNotFoundError as exc:
        click.echo(str(exc))
        click.echo("\nRun setup first:  ultra setup")
        return
    except Exception as exc:
        click.echo(f"Config error: {exc}")
        return

    from ultra import cli as cli_module

    cfg_opt = {"config_path": config_path}

    def go_chat() -> None:
        cli_module.chat.callback(**cfg_opt)

    def go_doctor() -> None:
        cli_module.doctor.callback(**cfg_opt)

    def go_setup() -> None:
        cli_module.setup.callback(prod=False, output_path=None, force=False)

    def go_setup_status() -> None:
        cli_module.setup_status.callback(prod=False)

    def go_personality_menu() -> None:
        from ultra.personality_wizard import run_personality_menu

        run_personality_menu(config, config_path=config_path)

    def go_memory_status() -> None:
        cli_module.memory_status.callback(**cfg_opt)

    def go_memory_search() -> None:
        try:
            query = click.prompt("Search query")
        except (EOFError, KeyboardInterrupt):
            return
        if query.strip():
            cli_module.memory_search_cmd.callback(query=query.strip(), **cfg_opt)

    def go_memory_embed_pending() -> None:
        cli_module.memory_embed_pending.callback(**cfg_opt)

    def go_memory_reindex() -> None:
        if click.confirm("Clear all embeddings and re-embed every anchor?", default=False):
            cli_module.memory_reindex.callback(**cfg_opt)

    def go_memory_preload() -> None:
        cli_module.memory_preload.callback(**cfg_opt)

    def go_tasks_list() -> None:
        cli_module.tasks_list.callback(**cfg_opt)

    def go_tasks_run() -> None:
        try:
            task_id = click.prompt("Task id")
        except (EOFError, KeyboardInterrupt):
            return
        if task_id.strip():
            cli_module.tasks_run.callback(task_id=task_id.strip(), force=True, **cfg_opt)

    def go_tasks_run_due() -> None:
        cli_module.tasks_run_due.callback(**cfg_opt)

    def go_tasks_install() -> None:
        cli_module.tasks_install.callback(**cfg_opt)

    def go_channels_test() -> None:
        name = _pick(
            "Test channel",
            [("1", "Discord"), ("2", "Telegram")],
            allow_zero=True,
        )
        if name == "1":
            cli_module.channels_test.callback(name="discord", **cfg_opt)
        elif name == "2":
            cli_module.channels_test.callback(name="telegram", **cfg_opt)

    def go_telegram_id() -> None:
        cli_module.channels_telegram_id.callback(**cfg_opt)

    def go_image_info() -> None:
        cli_module.image_info.callback()

    def go_discover_network() -> None:
        cli_module.discover_network.callback(
            save=True, subnet=None, timeout=5.0, as_json=False, **cfg_opt
        )

    def go_discover_show() -> None:
        cli_module.discover_show.callback(as_json=False, **cfg_opt)

    def go_discover_path() -> None:
        cli_module.discover_path.callback(**cfg_opt)

    submenus: dict[str, tuple[str, list[tuple[str, str, Callable[[], None]]]]] = {
        "2": (
            "Setup & health",
            [
                ("1", "Run first-boot setup wizard", go_setup),
                ("2", "Setup status", go_setup_status),
                ("3", "Doctor — verify config & LLM", go_doctor),
            ],
        ),
        "4": (
            "Memory Anchor",
            [
                ("1", "Status", go_memory_status),
                ("2", "Search memories", go_memory_search),
                ("3", "Embed pending anchors", go_memory_embed_pending),
                ("4", "Full reindex", go_memory_reindex),
                ("5", "Preload embed model (dev)", go_memory_preload),
            ],
        ),
        "5": (
            "Scheduled tasks",
            [
                ("1", "List tasks", go_tasks_list),
                ("2", "Run one task now", go_tasks_run),
                ("3", "Run all due tasks", go_tasks_run_due),
                ("4", "Pi systemd install instructions", go_tasks_install),
            ],
        ),
        "6": (
            "Notifications",
            [
                ("1", "Send test message", go_channels_test),
                ("2", "Look up Telegram chat_id", go_telegram_id),
            ],
        ),
        "9": (
            "Discover devices",
            [
                ("1", "Scan network now (save results)", go_discover_network),
                ("2", "Show last saved scan", go_discover_show),
                ("3", "Show discovered.json path", go_discover_path),
            ],
        ),
    }

    click.echo("")
    click.echo("Linux Ultra")
    click.echo(f"  model:     {config.model}")
    click.echo(f"  workspace: {config.workspace}")

    while True:
        choice = _pick(
            "Main menu",
            [
                ("1", "Chat with Ultra"),
                ("2", "Setup & health"),
                ("3", "Personality"),
                ("4", "Memory Anchor"),
                ("5", "Scheduled tasks"),
                ("6", "Notifications"),
                ("7", "Pi image build info"),
                ("8", "Command reference (all CLI commands)"),
                ("9", "Discover devices"),
            ],
        )
        if choice is None:
            click.echo("Bye.")
            break

        if choice == "1":
            go_chat()
            continue

        if choice == "3":
            go_personality_menu()
            continue

        if choice == "7":
            go_image_info()
            _pause()
            continue

        if choice == "8":
            print_command_reference()
            _pause()
            continue

        sub = submenus.get(choice)
        if not sub:
            continue

        title, actions = sub
        while True:
            sub_choice = _pick(title, [(k, lbl) for k, lbl, _ in actions])
            if sub_choice is None:
                break
            for key, _, fn in actions:
                if key == sub_choice:
                    click.echo("")
                    fn()
                    _pause()
                    break
