from __future__ import annotations

from pathlib import Path

import click

from ultra.agent import Agent
from ultra.config import Config
from ultra.scheduler import TaskState, is_due, load_tasks


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None, hidden=True)
def main(ctx: click.Context, config_path: Path | None) -> None:
    """Ultra — AI-driven OS orchestrator."""
    if ctx.invoked_subcommand is None:
        from ultra.menu import run_interactive_menu

        run_interactive_menu(config_path)


@main.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def menu(config_path: Path | None) -> None:
    """Interactive navigation menu (numbered options)."""
    from ultra.menu import run_interactive_menu

    run_interactive_menu(config_path)


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

    click.echo("Ultra agent ready. Type /help for commands, or exit to quit.\n")
    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nBye.")
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            break

        from ultra.menu import handle_chat_command

        help_text = handle_chat_command(user_input)
        if help_text:
            click.echo(help_text + "\n")
            continue

        click.echo("\nultra> ", nl=False)
        try:
            slow_tools = {
                "network_discover": "(scanning network — may take up to a minute...)\n",
                "home_assistant": "(querying Home Assistant...)\n",
            }

            def on_tool(name: str) -> None:
                hint = slow_tools.get(name)
                if hint:
                    click.echo(hint, nl=False)

            response = agent.run(user_input, on_tool_start=on_tool)
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
    else:
        for task in due:
            click.echo(f"=== {task.id} ===")
            _run_scheduled_task(config, task.id, force=True)
    _memory_embed_maintenance(config)


def _memory_embed_maintenance(config: Config) -> None:
    if not config.memory.enabled or not config.memory.auto_embed:
        return
    from ultra.memory.service import MemoryService

    svc = MemoryService(config)
    n = svc.embed_tick()
    if n:
        click.echo(f"memory embed tick: {n} anchor(s)")
    pending = svc.pending_count()
    if pending:
        click.echo(f"memory backlog: {pending} pending")
    svc.check_backlog_alert()


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
def personality() -> None:
    """Companion personality (Persistent Sage-compatible personality.json)."""


@personality.command("show")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.option("--prompt", is_flag=True, help="Print generated system prompt only.")
def personality_show(config_path: Path | None, prompt: bool) -> None:
    """Show active personality profile."""
    import json

    from ultra.personality import PersonalityManager, resolve_personality_path

    config = Config.load(config_path)
    mgr = PersonalityManager.load(config)
    if not mgr.enabled:
        click.echo("personality: disabled")
        return
    click.echo(f"path: {resolve_personality_path(config)}")
    if prompt:
        click.echo(mgr.generated_system_prompt())
        return
    click.echo(json.dumps(mgr.get_active_json(), indent=2))


@personality.command("path")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def personality_path(config_path: Path | None) -> None:
    """Print path to personality.json."""
    from ultra.personality import resolve_personality_path

    config = Config.load(config_path)
    click.echo(resolve_personality_path(config))


@personality.command("customize")
@click.option("--pick", "pick_one", is_flag=True, help="Edit a single section instead of full walkthrough.")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def personality_customize(pick_one: bool, config_path: Path | None) -> None:
    """Walk through personality sections (Enter=keep, e=editor, c=clear, 0=back)."""
    from ultra.personality_wizard import run_personality_customize

    config = Config.load(config_path)
    if pick_one:
        run_personality_customize(config, mode="pick")
    else:
        # Full menu if invoked without --pick from CLI? User said customize = walkthrough
        # Use walkthrough by default; --pick for single section
        run_personality_customize(config, mode="walkthrough")


@personality.command("menu")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def personality_menu_cmd(config_path: Path | None) -> None:
    """Interactive personality submenu (view, customize, reset)."""
    from ultra.personality_wizard import run_personality_menu

    config = Config.load(config_path)
    run_personality_menu(config, config_path=config_path)


@main.group()
def memory() -> None:
    """Memory Anchor (Persistent Sage-compatible long-term memory)."""


@memory.command("status")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def memory_status(config_path: Path | None) -> None:
    """Show memory database and embed model status."""
    config = Config.load(config_path)
    from ultra.memory.service import MemoryService
    from ultra.personality import PersonalityManager

    personality = PersonalityManager.load(config)
    memory_pid = (
        personality.active_profile_id()
        if personality.enabled
        else config.memory.personality_id
    )
    svc = MemoryService(config, personality_id=memory_pid)
    if not svc.enabled:
        click.echo("memory: disabled")
        return
    click.echo(f"database:  {svc.db_path}")
    click.echo(f"personality: {memory_pid}")
    click.echo(f"backend:   {config.memory.embed_backend}")
    click.echo(f"model:     {config.memory.embed_model}")
    pending = svc.pending_count()
    click.echo(f"pending:   {pending} anchor(s) without embeddings")
    if config.memory.semantic_enabled:
        try:
            svc.recall("warmup test", limit=1)
            if config.memory.embed_backend == "fastembed":
                cache = config.memory.resolve_embed_cache_dir(config.workspace)
                click.echo(f"cache:     {cache}")
            click.echo("embed test: ok")
        except Exception as exc:
            click.echo(f"embed test: FAILED ({exc})")
            if config.memory.embed_backend == "ollama":
                click.echo("           Run: ollama pull nomic-embed-text")
            else:
                click.echo("           Run: python -m ultra memory preload")


@memory.command("search")
@click.argument("query")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def memory_search_cmd(query: str, config_path: Path | None) -> None:
    """Search long-term memory."""
    from ultra.memory.service import MemoryService

    config = Config.load(config_path)
    svc = MemoryService(config)
    ctx = svc.recall_context(query)
    click.echo(ctx or "(no matches)")


@memory.command("embed-tick")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def memory_embed_tick(config_path: Path | None) -> None:
    """Embed one batch (Pi timer — runs every 2 min)."""
    from ultra.memory.service import MemoryService

    config = Config.load(config_path)
    svc = MemoryService(config)
    n = svc.embed_tick()
    pending = svc.pending_count()
    if n:
        click.echo(f"embedded {n}, pending {pending}")
    svc.check_backlog_alert()


@memory.command("embed-pending")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def memory_embed_pending(config_path: Path | None) -> None:
    """Embed all anchors missing vectors (manual catch-up — may take a while)."""
    from ultra.memory.service import MemoryService

    config = Config.load(config_path)
    svc = MemoryService(config)
    before = svc.pending_count()
    embedded = svc.embed_pending()
    after = svc.pending_count()
    click.echo(f"embedded: {embedded}, pending remaining: {after} (was {before})")


@memory.command("reindex")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.confirmation_option(prompt="Clear all embeddings and re-embed every anchor?")
def memory_reindex(config_path: Path | None) -> None:
    """Full re-embed of all memory anchors (like Persistent Sage reindex)."""
    from ultra.memory.service import MemoryService

    config = Config.load(config_path)
    svc = MemoryService(config)
    embedded, total = svc.reindex_all()
    click.echo(f"Reindexed {total} anchors ({embedded} embedded this run).")


@memory.command("preload")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def memory_preload(config_path: Path | None) -> None:
    """Download/cache the embed model (dev machines; baked into Pi image)."""
    from ultra.memory.embed import preload_fastembed_model

    config = Config.load(config_path)
    cache = config.memory.resolve_embed_cache_dir(config.workspace)
    click.echo(f"Preloading {config.memory.embed_model} -> {cache}")
    preload_fastembed_model(config.memory.embed_model, cache_dir=cache)
    click.echo("Done.")


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
def discover() -> None:
    """Scan the local network for smart-home devices and services."""


@discover.command("network")
@click.option("--save", is_flag=True, help="Save JSON to workspace/projects/smart-home/discovered.json")
@click.option("--subnet", default=None, help="Subnet CIDR (default: auto-detect /24)")
@click.option("--timeout", default=5.0, show_default=True, help="mDNS browse seconds")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON only")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def discover_network(
    save: bool,
    subnet: str | None,
    timeout: float,
    as_json: bool,
    config_path: Path | None,
) -> None:
    """Scan LAN hosts, mDNS services (HA, Chromecast, MQTT), and common ports."""
    import json

    from ultra.discover import (
        default_discover_path,
        format_discovery_summary,
        run_discovery,
        save_discovery,
    )

    config = Config.load(config_path)
    click.echo("Scanning local network (may take ~10–30 seconds)...")
    result = run_discovery(subnet=subnet, mdns_timeout=timeout)
    if save:
        path = save_discovery(result, default_discover_path(config.workspace))
        click.echo(f"Saved: {path}\n")
    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
        return
    click.echo(format_discovery_summary(result))


@discover.command("show")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON")
def discover_show(config_path: Path | None, as_json: bool) -> None:
    """Show last saved discovery results."""
    import json

    from ultra.discover import default_discover_path, format_discovery_summary, load_discovery
    from ultra.discover import DiscoveryResult, DiscoveredHost, DiscoveredService, DiscoveryHint

    config = Config.load(config_path)
    path = default_discover_path(config.workspace)
    data = load_discovery(path)
    if not data:
        raise click.ClickException(f"No saved scan at {path} — run: ultra discover network --save")
    if as_json:
        click.echo(json.dumps(data, indent=2))
        return
    # Rehydrate minimal result for summary formatter
    result = DiscoveryResult(
        scanned_at=data.get("scanned_at", ""),
        subnet=data.get("subnet"),
        platform=data.get("platform", ""),
        methods=data.get("methods") or [],
        hosts=[
            DiscoveredHost(
                ip=h["ip"],
                hostname=h.get("hostname"),
                mac=h.get("mac"),
                sources=h.get("sources") or [],
            )
            for h in data.get("hosts") or []
        ],
        services=[
            DiscoveredService(
                service_type=s["service_type"],
                name=s["name"],
                host=s["host"],
                port=int(s["port"]),
                properties=s.get("properties") or {},
            )
            for s in data.get("services") or []
        ],
        open_ports=data.get("open_ports") or [],
        hints=[
            DiscoveryHint(
                category=h["category"],
                message=h["message"],
                host=h.get("host"),
                port=h.get("port"),
                url=h.get("url"),
            )
            for h in data.get("hints") or []
        ],
        errors=data.get("errors") or [],
    )
    click.echo(f"File: {path}\n")
    click.echo(format_discovery_summary(result))


@discover.command("path")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def discover_path(config_path: Path | None) -> None:
    """Print path to discovered.json."""
    from ultra.discover import default_discover_path

    config = Config.load(config_path)
    click.echo(default_discover_path(config.workspace))


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


@main.group("ha")
def homeassistant_cli() -> None:
    """Home Assistant (bundled on Linux Ultra Pi image)."""


@homeassistant_cli.command("status")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def ha_status(config_path: Path | None) -> None:
    """Check Home Assistant container and API."""
    import shutil
    import subprocess

    from ultra.homeassistant import HomeAssistantClient

    config = Config.load(config_path)
    ha = config.smart_home.home_assistant
    click.echo(f"url:     {ha.url}")
    click.echo(f"enabled: {ha.enabled}")
    token_set = bool(ha.resolve_token())
    click.echo(f"token:   {'configured' if token_set else 'not set'}")

    if shutil.which("ultra-homeassistant"):
        proc = subprocess.run(
            ["ultra-homeassistant", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        line = (proc.stdout or proc.stderr).strip()
        if line:
            click.echo(f"container: {line}")

    client = HomeAssistantClient(config)
    result = client.check_api()
    if result.ok:
        click.echo("api:     ok")
        if isinstance(result.data, dict) and result.data.get("message"):
            click.echo(f"         {result.data['message']}")
    else:
        click.echo(f"api:     FAILED ({result.error or result.data})")
        if not token_set:
            click.echo("         Open the HA web UI, finish onboarding, then save a long-lived token.")


@homeassistant_cli.command("url")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
def ha_url(config_path: Path | None) -> None:
    """Print Home Assistant web UI URL."""
    config = Config.load(config_path)
    click.echo(config.smart_home.home_assistant.url)


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

    if config.memory.enabled:
        from ultra.memory.service import MemoryService

        mem = MemoryService(config)
        click.echo(f"memory:    enabled ({mem.db_path})")
        click.echo(
            f"           embed {config.memory.embed_model} via {config.memory.embed_backend}"
        )
        if config.memory.embed_backend == "fastembed":
            click.echo(f"           cache {config.memory.resolve_embed_cache_dir(config.workspace)}")
        else:
            click.echo(f"           ollama {config.memory.embed_ollama_url}")
    else:
        click.echo("memory:    disabled")

    if config.smart_home.home_assistant.enabled:
        from ultra.homeassistant import HomeAssistantClient

        ha = config.smart_home.home_assistant
        click.echo(f"home assistant: {ha.url}")
        token_set = bool(ha.resolve_token())
        click.echo(f"           token {'set' if token_set else 'not set'}")
        result = HomeAssistantClient(config).check_api()
        click.echo(f"           api {'ok' if result.ok else 'unreachable'}")
    else:
        click.echo("home assistant: disabled")

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
