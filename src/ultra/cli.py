from __future__ import annotations

from pathlib import Path

import click

from ultra.agent import Agent
from ultra.config import Config
from ultra.scheduler import TaskState, is_due, load_tasks


@click.group()
def main() -> None:
    """Ultra — AI-driven OS orchestrator."""


@main.command()
@click.option("--prod", is_flag=True, help="Use Pi paths (/etc/ultra/config.yaml).")
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Re-run even if setup was completed.")
def setup(prod: bool, output_path: Path | None, force: bool) -> None:
    """First-boot wizard: API key, model, Discord/Telegram alerts."""
    from ultra.setup import config_output_path, run_wizard

    output = config_output_path(prod=prod, override=output_path)
    run_wizard(prod=prod, output=output, force=force)


@main.command("setup-status")
@click.option("--prod", is_flag=True)
def setup_status(prod: bool) -> None:
    """Check whether first-boot setup has been completed."""
    from ultra.setup import config_output_path, is_setup_complete

    if is_setup_complete(prod=prod):
        click.echo("setup: complete")
        click.echo(f"config: {config_output_path(prod=prod, override=None)}")
        raise SystemExit(0)
    click.echo("setup: needed — run: python -m ultra setup")
    raise SystemExit(1)


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def chat(config_path: Path | None) -> None:
    """Interactive chat with the orchestrator agent."""
    config = Config.load(config_path)
    agent = Agent(config)

    click.echo("Ultra agent ready. Type 'exit' or Ctrl+C to quit.\n")
    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye.")
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            break

        click.echo("\nultra> ", nl=False)
        try:
            response = agent.run(user_input)
            click.echo(response + "\n")
        except Exception as exc:
            click.echo(f"\nError: {exc}\n", err=True)
            if "401" in str(exc) or "Unauthorized" in str(exc):
                click.echo(
                    "Ollama auth failed. Set api_key in config (or OLLAMA_API_KEY env). "
                    "For cloud models use ollama_base_url: https://ollama.com/v1\n",
                    err=True,
                )


@main.command("run")
@click.argument("task")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.option("--interactive", is_flag=True, help="Use interactive prompt instead of headless.")
def run_task(task: str, config_path: Path | None, interactive: bool) -> None:
    """Run a single headless task (for cron/systemd timers)."""
    config = Config.load(config_path)
    agent = Agent(config, headless=not interactive)
    response = agent.run(task)
    click.echo(response)


@main.group()
def tasks() -> None:
    """Manage scheduled background tasks."""


@tasks.command("list")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def tasks_list(config_path: Path | None) -> None:
    """List configured scheduled tasks."""
    config = Config.load(config_path)
    state = TaskState(config.workspace / ".task-state.json")
    found = load_tasks(config.tasks_dir)
    if not found:
        click.echo(f"No tasks in {config.tasks_dir}")
        return

    for task in found:
        status = "enabled" if task.enabled else "disabled"
        last = state.last_run(task.id)
        last_s = last.isoformat() if last else "never"
        sched = f"every {int(task.interval.total_seconds() // 60)}m" if task.interval else f"daily {task.daily_at}"
        click.echo(f"{task.id:20} {status:8} {sched:16} last={last_s}")


@tasks.command("run")
@click.argument("task_id")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Run even if not due.")
def tasks_run(task_id: str, config_path: Path | None, force: bool) -> None:
    """Run one scheduled task by id."""
    config = Config.load(config_path)
    _run_scheduled_task(config, task_id, force=force)


@tasks.command("run-due")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def tasks_run_due(config_path: Path | None) -> None:
    """Run all scheduled tasks that are due (called by systemd timer)."""
    config = Config.load(config_path)
    state = TaskState(config.workspace / ".task-state.json")
    due = [t for t in load_tasks(config.tasks_dir) if is_due(t, state)]
    if not due:
        click.echo("No tasks due.")
        return
    for task in due:
        click.echo(f"=== {task.id} ===")
        _run_scheduled_task(config, task.id, force=True)


def _run_scheduled_task(config: Config, task_id: str, *, force: bool) -> None:
    matches = [t for t in load_tasks(config.tasks_dir) if t.id == task_id]
    if not matches:
        raise click.ClickException(f"Unknown task: {task_id}")

    task = matches[0]
    state = TaskState(config.workspace / ".task-state.json")
    if not force and not is_due(task, state):
        click.echo(f"Task {task_id} is not due yet.")
        return

    agent = Agent(config, headless=True)
    response = agent.run(task.prompt)
    state.mark_run(task.id)

    if response.strip() == "NO_ACTION":
        click.echo(f"{task_id}: no action needed")
    else:
        click.echo(response)


@tasks.command("install")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def tasks_install(config_path: Path | None) -> None:
    """Print systemd install instructions (Linux Ultra on Pi)."""
    config = Config.load(config_path)
    deploy = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
    click.echo("Linux Ultra — install scheduled tasks on the Pi:\n")
    click.echo(f"  sudo cp {deploy}/ultra-tasks.service /etc/systemd/system/")
    click.echo(f"  sudo cp {deploy}/ultra-tasks.timer /etc/systemd/system/")
    click.echo("  sudo systemctl daemon-reload")
    click.echo("  sudo systemctl enable --now ultra-tasks.timer")
    click.echo(f"\nTasks loaded from: {config.tasks_dir}")
    click.echo("Edit task YAML files, then: sudo systemctl start ultra-tasks.service")


@main.group()
def image() -> None:
    """Build Linux Ultra Pi image (requires Linux/WSL2)."""


@image.command("info")
def image_info() -> None:
    """Show how to build and flash the Pi 5 image."""
    repo = Path(__file__).resolve().parents[2]
    click.echo("Linux Ultra — Raspberry Pi 5 image build\n")
    click.echo("Build locally (Linux/WSL Ubuntu):")
    click.echo(f"  cd {repo}")
    click.echo("  sudo apt install debootstrap qemu-user-static binfmt-support \\")
    click.echo("       parted dosfstools rsync curl")
    click.echo("  sudo ./iso/build.sh")
    click.echo("")
    click.echo("Build in GitHub Actions (no Linux machine needed):")
    click.echo("  1. Push this repo to GitHub")
    click.echo("  2. Actions -> 'Build Linux Ultra Pi Image' -> Run workflow")
    click.echo("  3. Download artifact: linux-ultra-pi5-1.0.img.xz")
    click.echo("  4. Decompress: xz -dk linux-ultra-pi5-1.0.img.xz")
    click.echo("")
    click.echo("Tag a release (optional):")
    click.echo("  git tag v1.0.0 && git push origin v1.0.0")
    click.echo("  -> attaches .img.xz to GitHub Release automatically")
    click.echo("")
    click.echo("Output:")
    click.echo(f"  {repo / 'dist' / 'linux-ultra-pi5-1.0.img'}")
    click.echo("")
    click.echo("Flash to NVMe (Linux, replace device carefully):")
    click.echo("  xz -dk dist/linux-ultra-pi5-1.0.img.xz   # if downloaded from GitHub")
    click.echo("  sudo dd if=dist/linux-ultra-pi5-1.0.img of=/dev/nvme0n1 bs=4M status=progress conv=fsync")
    click.echo("")
    click.echo("First boot:")
    click.echo("  1. Pi 5 + ethernet, NVMe boot enabled in EEPROM")
    click.echo("  2. SSH: ssh ultra@ultra.local  (default password: ultra — change on first login)")
    click.echo("  3. Run: ultra setup --prod")
    click.echo("  4. Chat: ultra chat")


@main.group()
def channels() -> None:
    """Set up and test notification channels (Discord, Telegram)."""


@channels.command("test")
@click.argument("name", type=click.Choice(["discord", "telegram"]))
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def channels_test(name: str, config_path: Path | None) -> None:
    """Send a test message on a configured channel."""
    from ultra.notify import send_discord, send_telegram

    config = Config.load(config_path)
    if name == "discord":
        result = send_discord(
            config.channels.discord,
            "Linux Ultra test message - notifications are working.",
            title="Ultra",
        )
    else:
        result = send_telegram(
            config.channels.telegram,
            "Linux Ultra test message - notifications are working.",
            title="Ultra",
        )

    if result.success:
        click.echo(result.output)
    else:
        raise click.ClickException(result.output)


@channels.command("telegram-id")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def channels_telegram_id(config_path: Path | None) -> None:
    """Show your Telegram chat_id (message your bot 'hello' first)."""
    from ultra.notify import telegram_recent_chats

    config = Config.load(config_path)
    token = config.channels.telegram.get("bot_token", "")
    if not token:
        raise click.ClickException("Add channels.telegram.bot_token to config.local.yaml first")

    result = telegram_recent_chats(token)
    if result.success:
        click.echo("Use one of these in config.local.yaml under channels.telegram.chat_id:\n")
        click.echo(result.output)
    else:
        raise click.ClickException(result.output)


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def doctor(config_path: Path | None) -> None:
    """Verify config and environment."""
    config = Config.load(config_path)
    click.echo(f"provider:  {config.provider}")
    click.echo(f"model:     {config.model}")
    if config.provider == "ollama":
        click.echo(f"ollama:    {config.ollama_base_url}")
        _check_ollama(config)
    click.echo(f"workspace: {config.workspace}")
    click.echo(f"audit log: {config.audit_log}")

    channels = []
    if config.channels.discord.get("webhook_url"):
        channels.append("discord")
    if config.channels.telegram.get("bot_token"):
        channels.append("telegram")
    if config.channels.email.get("smtp_host"):
        channels.append("email")
    click.echo(f"channels:  {', '.join(channels) or '(none configured)'}")

    from ultra.setup import is_setup_complete

    if is_setup_complete(prod=False):
        click.echo("setup:     complete")
    else:
        click.echo("setup:     needed — run: python -m ultra setup")


def _check_ollama(config: Config) -> None:
    import httpx

    base = config.ollama_base_url.rstrip("/").removesuffix("/v1")
    headers: dict[str, str] = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
        click.echo(f"api key:   set ({len(config.api_key)} chars, from config or OLLAMA_API_KEY)")
    else:
        click.echo("api key:   not set (fine for local models on localhost)")

    if config.api_key and "localhost" in config.ollama_base_url and ":cloud" in config.model:
        click.echo(
            "note:      cloud models + API key -> use ollama_base_url: https://ollama.com/v1"
        )
    elif ":cloud" in config.model and not config.api_key:
        click.echo("note:      :cloud via localhost alternatively works with `ollama signin`")

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{base}/api/tags", headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        click.echo(f"reachability: FAILED ({exc})")
        if "ollama.com" in base and not config.api_key:
            click.echo("           Set api_key or OLLAMA_API_KEY for ollama.com")
        elif "localhost" in base:
            click.echo("           Start Ollama locally, or point at https://ollama.com/v1")
        return

    click.echo("reachability: ok")

    try:
        from ultra.llm.factory import create_provider

        provider = create_provider(config)
        turn = provider.chat([{"role": "user", "content": "Reply with OK only."}], [])
        preview = (turn.content or "").strip()[:40] or "(empty response)"
        click.echo(f"model test: {preview}")
    except Exception as exc:
        err = str(exc)
        click.echo(f"model test: FAILED — {err}")
        if "401" in err or "Unauthorized" in err:
            click.echo("           Add api_key to config.local.yaml or set OLLAMA_API_KEY")
            click.echo("           For cloud: ollama_base_url: https://ollama.com/v1")
