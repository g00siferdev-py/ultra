from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-20250514",
    "ollama": "llama3.1",
}

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
OLLAMA_CLOUD_BASE_URL = "https://ollama.com/v1"

CONFIG_SEARCH_PATHS = [
    Path("config.local.yaml"),
    Path.home() / ".ultra" / "config.yaml",
    Path("/etc/ultra/config.yaml"),
]


@dataclass
class PersonalityConfig:
    enabled: bool = True
    path: Path | None = None
    persistent_sage_compat: bool = True


@dataclass
class MemoryConfig:
    enabled: bool = True
    database: Path | None = None
    persistent_sage_compat: bool = True
    personality_id: str = "ultra"
    semantic_enabled: bool = True
    embed_model: str = "nomic-embed-text"
    embed_backend: str = "fastembed"  # fastembed (baked in) | ollama
    embed_ollama_url: str = "http://127.0.0.1:11434"
    embed_cache_dir: Path | None = None
    auto_recall: bool = True
    auto_store: bool = True
    auto_embed: bool = True
    recall_limit: int = 8
    embed_batch_size: int = 8
    embed_startup_batches: int = 3
    embed_backlog_alert: int = 50

    def resolve_embed_cache_dir(self, workspace: Path) -> Path:
        if self.embed_cache_dir:
            return self.embed_cache_dir.resolve()
        if Path("/var/lib/ultra").is_dir():
            return Path("/var/lib/ultra/fastembed")
        return (workspace / "memory" / "fastembed").resolve()

    def resolve_db_path(self, workspace: Path) -> Path:
        if self.database:
            return self.database.resolve()
        if self.persistent_sage_compat:
            ps_dir = _persistent_sage_data_dir()
            if ps_dir and (ps_dir / "nova_memory.sqlite").is_file():
                return ps_dir / "nova_memory.sqlite"
        return (workspace / "memory" / "ultra_memory.sqlite").resolve()


def _persistent_sage_data_dir() -> Path | None:
    raw = os.environ.get("PERSISTENT_SAGE_DATA_DIR") or os.environ.get("NOVA_DATA_DIR")
    if raw:
        return Path(raw)
    return None


@dataclass
class HomeAssistantConfig:
    enabled: bool = True
    url: str = "http://127.0.0.1:8123"
    token: str = ""
    token_file: Path | None = None

    def resolve_token(self) -> str:
        env = os.environ.get("HA_TOKEN") or os.environ.get("HOME_ASSISTANT_TOKEN") or ""
        if env.strip():
            return env.strip()
        if self.token.strip():
            return self.token.strip()
        if self.token_file and self.token_file.is_file():
            return self.token_file.read_text(encoding="utf-8").strip()
        default = Path("/var/ultra/workspace/projects/smart-home/secrets/ha-token.txt")
        if default.is_file():
            return default.read_text(encoding="utf-8").strip()
        return ""


@dataclass
class SmartHomeConfig:
    home_assistant: HomeAssistantConfig = field(default_factory=HomeAssistantConfig)


@dataclass
class ChannelsConfig:
    telegram: dict[str, str] = field(default_factory=dict)
    discord: dict[str, str] = field(default_factory=dict)
    email: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    provider: str
    api_key: str
    model: str
    workspace: Path
    audit_log: Path
    extra_instructions: str
    channels: ChannelsConfig
    ollama_base_url: str = OLLAMA_DEFAULT_BASE_URL
    tasks_dir: Path = field(default_factory=lambda: Path("tasks"))
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    smart_home: SmartHomeConfig = field(default_factory=SmartHomeConfig)
    config_path: Path | None = None

    def integration_prompt_section(self) -> str:
        """System prompt block: where integrations are configured (avoid asking user for IPs)."""
        cfg_file = str(self.config_path) if self.config_path else "config.local.yaml or /etc/ultra/config.yaml"
        smart_home = self.workspace / "projects" / "smart-home"
        lines = [
            "## Integration config (read before asking the user)",
            "",
            f"Ultra config file: {cfg_file}",
            "For Home Assistant URLs, tokens, Discord/Telegram, LLM settings, and smart_home — "
            "read this file with read_file first. Do not ask the user for IP addresses, ports, "
            "or API keys when they are already in config or workspace secrets.",
            "",
            f"Smart-home workspace: {smart_home}",
            f"Discovery results (if any): {smart_home / 'discovered.json'}",
            f"HA token file (typical): {smart_home / 'secrets' / 'ha-token.txt'}",
            "",
            "Configured now:",
        ]
        ha = self.smart_home.home_assistant
        if ha.enabled:
            token_note = "token configured" if ha.resolve_token() else "token not set yet"
            lines.append(f"- Home Assistant: {ha.url} ({token_note}) — use home_assistant tool")
        else:
            lines.append("- Home Assistant: disabled in config")
        if self.channels.discord.get("webhook_url"):
            lines.append("- Discord alerts: configured")
        if self.channels.telegram.get("bot_token"):
            lines.append("- Telegram alerts: configured")
        if self.provider == "ollama":
            lines.append(f"- LLM: ollama / {self.model} @ {self.ollama_base_url}")
        else:
            lines.append(f"- LLM: {self.provider} / {self.model}")
        lines.append("")
        lines.append(
            "If something is missing from config, use network_discover or ultra ha status via run_shell, "
            "then guide the user to update the config file — not to paste secrets in chat."
        )
        return "\n".join(lines)

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        path = config_path or _find_config()
        if path is None:
            raise FileNotFoundError(
                "No config found. Copy config.example.yaml to config.local.yaml "
                "or set ULTRA_CONFIG to a config file path."
            )

        with path.open(encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        provider = (raw.get("provider") or "openai").lower()
        if provider == "ollama":
            api_key = (
                raw.get("api_key")
                or os.environ.get("OLLAMA_API_KEY", "")
                or os.environ.get("ULTRA_API_KEY", "")
            )
        else:
            api_key = raw.get("api_key") or os.environ.get("ULTRA_API_KEY", "")
            if not api_key:
                raise ValueError("api_key is required in config or ULTRA_API_KEY env var")

        model = raw.get("model") or DEFAULT_MODELS.get(provider, "")
        ollama_base_url = raw.get("ollama_base_url") or OLLAMA_DEFAULT_BASE_URL
        if (
            provider == "ollama"
            and api_key
            and ":cloud" in model
            and "localhost" in ollama_base_url
        ):
            ollama_base_url = OLLAMA_CLOUD_BASE_URL
        workspace = Path(raw.get("workspace") or "workspace").resolve()
        audit_log = Path(raw.get("audit_log") or "logs/audit.log").resolve()
        tasks_dir = Path(raw.get("tasks_dir") or "tasks").resolve()

        channels_raw = raw.get("channels") or {}
        channels = ChannelsConfig(
            telegram=channels_raw.get("telegram") or {},
            discord=channels_raw.get("discord") or {},
            email=channels_raw.get("email") or {},
        )

        memory_raw = raw.get("memory") or {}
        memory_db = memory_raw.get("database")
        memory = MemoryConfig(
            enabled=bool(memory_raw.get("enabled", True)),
            database=Path(memory_db).expanduser() if memory_db else None,
            persistent_sage_compat=bool(memory_raw.get("persistent_sage_compat", True)),
            personality_id=str(memory_raw.get("personality_id") or "ultra"),
            semantic_enabled=bool(memory_raw.get("semantic_enabled", True)),
            embed_model=str(memory_raw.get("embed_model") or "nomic-embed-text"),
            embed_backend=str(memory_raw.get("embed_backend") or "fastembed"),
            embed_ollama_url=str(memory_raw.get("embed_ollama_url") or "http://127.0.0.1:11434"),
            embed_cache_dir=Path(memory_raw["embed_cache_dir"]).expanduser()
            if memory_raw.get("embed_cache_dir")
            else None,
            auto_recall=bool(memory_raw.get("auto_recall", True)),
            auto_store=bool(memory_raw.get("auto_store", True)),
            auto_embed=bool(memory_raw.get("auto_embed", True)),
            recall_limit=int(memory_raw.get("recall_limit") or 8),
            embed_batch_size=int(memory_raw.get("embed_batch_size") or 8),
            embed_startup_batches=int(memory_raw.get("embed_startup_batches") or 3),
            embed_backlog_alert=int(memory_raw.get("embed_backlog_alert") or 50),
        )

        personality_raw = raw.get("personality") or {}
        personality_path = personality_raw.get("path")
        personality = PersonalityConfig(
            enabled=bool(personality_raw.get("enabled", True)),
            path=Path(personality_path).expanduser() if personality_path else None,
            persistent_sage_compat=bool(personality_raw.get("persistent_sage_compat", True)),
        )

        smart_home_raw = raw.get("smart_home") or {}
        ha_raw = smart_home_raw.get("home_assistant") or {}
        token_file = ha_raw.get("token_file")
        smart_home = SmartHomeConfig(
            home_assistant=HomeAssistantConfig(
                enabled=bool(ha_raw.get("enabled", True)),
                url=str(ha_raw.get("url") or "http://127.0.0.1:8123"),
                token=str(ha_raw.get("token") or ""),
                token_file=Path(token_file).expanduser() if token_file else None,
            )
        )

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            workspace=workspace,
            audit_log=audit_log,
            extra_instructions=raw.get("extra_instructions") or "",
            channels=channels,
            ollama_base_url=ollama_base_url,
            tasks_dir=tasks_dir,
            memory=memory,
            personality=personality,
            smart_home=smart_home,
            config_path=path.resolve(),
        )


def _find_config() -> Path | None:
    env_path = os.environ.get("ULTRA_CONFIG")
    if env_path:
        path = Path(env_path)
        return path if path.is_file() else None

    for candidate in CONFIG_SEARCH_PATHS:
        if candidate.is_file():
            return candidate
    return None
