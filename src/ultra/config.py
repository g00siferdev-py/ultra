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
