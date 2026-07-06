from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from ultra.audit import AuditLog
from ultra.config import Config
from ultra.memory.service import MemoryService
from ultra.notify import send_discord, send_telegram
from ultra.personality import PersonalityManager


@dataclass
class ToolResult:
    success: bool
    output: str


ToolHandler = Callable[[dict[str, Any]], ToolResult]


class ToolRegistry:
    def __init__(
        self,
        config: Config,
        audit: AuditLog,
        memory: MemoryService | None = None,
        personality: PersonalityManager | None = None,
    ) -> None:
        self.config = config
        self.audit = audit
        self.memory = memory
        self.personality = personality
        self.workspace = config.workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._handlers: dict[str, ToolHandler] = {
            "run_shell": self._run_shell,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_directory": self._list_directory,
            "http_request": self._http_request,
            "send_notification": self._send_notification,
            "network_discover": self._network_discover,
        }
        if memory and memory.enabled:
            self._handlers["memory_search"] = self._memory_search
            self._handlers["memory_remember"] = self._memory_remember
        if personality and personality.enabled:
            self._handlers["personality_get"] = self._personality_get
            self._handlers["personality_update"] = self._personality_update
        if config.smart_home.home_assistant.enabled:
            self._handlers["home_assistant"] = self._home_assistant

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_shell",
                    "description": (
                        "Execute a shell command. Primary tool for OS control — "
                        "install packages, manage services, call CLIs, run scripts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "cwd": {
                                "type": "string",
                                "description": "Working directory (defaults to workspace)",
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "default": 120,
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a text file from disk.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": (
                        "Write text to a file. Use workspace for scripts and project state."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files and directories at a path.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "http_request",
                    "description": "Make an HTTP request (REST APIs, webhooks, Home Assistant, etc.).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                            "url": {"type": "string"},
                            "headers": {"type": "object"},
                            "body": {"type": "string"},
                        },
                        "required": ["method", "url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_notification",
                    "description": (
                        "Notify the user via telegram, discord, or email. "
                        "Use when autonomous outreach is needed."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "channel": {
                                "type": "string",
                                "enum": ["telegram", "discord", "email"],
                            },
                            "message": {"type": "string"},
                            "title": {"type": "string"},
                        },
                        "required": ["channel", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "network_discover",
                    "description": (
                        "Scan the local network for devices and smart-home services. "
                        "Finds LAN hosts (arp/ping), mDNS (Home Assistant, Chromecast, MQTT, HomeKit), "
                        "and probes common ports. Use before connecting to Home Assistant or IoT hubs."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subnet": {
                                "type": "string",
                                "description": "Optional CIDR e.g. 192.168.1.0/24 (auto-detect if omitted)",
                            },
                            "save": {
                                "type": "boolean",
                                "default": True,
                                "description": "Save results to workspace/projects/smart-home/discovered.json",
                            },
                            "timeout_seconds": {
                                "type": "number",
                                "default": 5,
                                "description": "mDNS browse duration",
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
        ]
        if self.config.smart_home.home_assistant.enabled:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": "home_assistant",
                        "description": (
                            "Control the bundled Home Assistant instance (lights, climate, media, etc.). "
                            "Prefer this over direct device APIs. Requires a long-lived access token in config."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["status", "states", "state", "call_service"],
                                },
                                "entity_id": {
                                    "type": "string",
                                    "description": "Entity id e.g. light.living_room",
                                },
                                "domain": {"type": "string"},
                                "service": {"type": "string"},
                                "service_data": {"type": "object"},
                            },
                            "required": ["action"],
                        },
                    },
                }
            )
        if self.memory and self.memory.enabled:
            schemas.extend(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "memory_search",
                            "description": (
                                "Search long-term Memory Anchor storage (Persistent Sage compatible). "
                                "Hybrid FTS + semantic recall for user preferences, facts, and past context."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "limit": {"type": "integer", "default": 8},
                                },
                                "required": ["query"],
                            },
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "memory_remember",
                            "description": (
                                "Store a durable memory anchor (fact, preference, insight). "
                                "Embedded locally via Ollama for semantic recall later."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "anchor_type": {
                                        "type": "string",
                                        "enum": ["fact", "insight", "curated", "raw"],
                                        "default": "fact",
                                    },
                                    "importance": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "maximum": 5,
                                        "default": 3,
                                    },
                                },
                                "required": ["content"],
                            },
                        },
                    },
                ]
            )
        if self.personality and self.personality.enabled:
            schemas.extend(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "personality_get",
                            "description": (
                                "Read the active companion personality profile (personality.json). "
                                "Returns JSON with all persona fields and a preview of the system prompt."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                        },
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "personality_update",
                            "description": (
                                "Update fields on the active companion personality profile and save to "
                                "personality.json. Only include fields you intend to change. Use when the "
                                "user asks you to adjust your personality, tone, values, or instructions."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "profileName": {
                                        "type": "string",
                                        "description": "Preset label",
                                    },
                                    "companionName": {
                                        "type": "string",
                                        "description": "Name shown in chat",
                                    },
                                    "corePersonality": {"type": "string"},
                                    "toneOfVoice": {"type": "string"},
                                    "backgroundStory": {"type": "string"},
                                    "coreValues": {"type": "string"},
                                    "relationshipStyle": {"type": "string"},
                                    "specialInstructions": {"type": "string"},
                                    "avatarDescription": {
                                        "type": ["string", "null"],
                                        "description": "Visual note, or null to clear",
                                    },
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                ]
            )
        return schemas

    def anthropic_tools(self) -> list[dict[str, Any]]:
        tools = []
        for schema in self.schemas():
            fn = schema["function"]
            tools.append(
                {
                    "name": fn["name"],
                    "description": fn["description"],
                    "input_schema": fn["parameters"],
                }
            )
        return tools

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(success=False, output=f"Unknown tool: {name}")
        try:
            result = handler(arguments)
            self.audit.record("tool_call", tool=name, arguments=arguments, success=result.success)
            return result
        except Exception as exc:
            self.audit.record(
                "tool_call",
                tool=name,
                arguments=arguments,
                success=False,
                error=str(exc),
            )
            return ToolResult(success=False, output=f"Tool error: {exc}")

    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def _run_shell(self, args: dict[str, Any]) -> ToolResult:
        command = args["command"]
        cwd = Path(args.get("cwd") or self.workspace).expanduser().resolve()
        timeout = int(args.get("timeout_seconds") or 120)
        cwd.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = _format_proc(proc)
        return ToolResult(success=proc.returncode == 0, output=output)

    def _read_file(self, args: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(args["path"])
        if not path.is_file():
            return ToolResult(success=False, output=f"File not found: {path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        return ToolResult(success=True, output=content)

    def _write_file(self, args: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult(success=True, output=f"Wrote {len(args['content'])} bytes to {path}")

    def _list_directory(self, args: dict[str, Any]) -> ToolResult:
        path = self._resolve_path(args["path"])
        if not path.is_dir():
            return ToolResult(success=False, output=f"Not a directory: {path}")
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = [f"{'[dir]' if e.is_dir() else '[file]'} {e.name}" for e in entries]
        return ToolResult(success=True, output="\n".join(lines) or "(empty)")

    def _http_request(self, args: dict[str, Any]) -> ToolResult:
        method = args["method"].upper()
        url = args["url"]
        headers = args.get("headers") or {}
        body = args.get("body")

        with httpx.Client(timeout=60.0) as client:
            response = client.request(method, url, headers=headers, content=body)

        preview = response.text[:8000]
        if len(response.text) > 8000:
            preview += "\n... (truncated)"
        output = f"HTTP {response.status_code}\n{preview}"
        success = 200 <= response.status_code < 300
        return ToolResult(success=success, output=output)

    def _send_notification(self, args: dict[str, Any]) -> ToolResult:
        channel = args["channel"]
        message = args["message"]
        title = args.get("title")

        if channel == "discord":
            r = send_discord(self.config.channels.discord, message, title)
            return ToolResult(success=r.success, output=r.output)
        if channel == "telegram":
            r = send_telegram(self.config.channels.telegram, message, title)
            return ToolResult(success=r.success, output=r.output)
        if channel == "email":
            return _notify_email(self.config.channels.email, message, title)
        return ToolResult(success=False, output=f"Unknown channel: {channel}")

    def _network_discover(self, args: dict[str, Any]) -> ToolResult:
        from ultra.discover import default_discover_path, run_discovery, save_discovery

        subnet = args.get("subnet")
        save = bool(args.get("save", True))
        timeout = float(args.get("timeout_seconds") or 5)
        try:
            result = run_discovery(subnet=subnet, mdns_timeout=timeout)
        except Exception as exc:
            return ToolResult(success=False, output=f"Discovery failed: {exc}")

        payload = result.to_dict()
        if save:
            path = save_discovery(result, default_discover_path(self.config.workspace))
            payload["saved_to"] = str(path)

        summary_lines = [
            f"Found {len(result.hosts)} host(s), {len(result.services)} mDNS service(s).",
        ]
        for hint in result.hints[:12]:
            summary_lines.append(f"- [{hint.category}] {hint.message}")
        if len(result.hints) > 12:
            summary_lines.append(f"- ... and {len(result.hints) - 12} more hints")
        if result.errors:
            summary_lines.append("Notes: " + "; ".join(result.errors))

        output = "\n".join(summary_lines) + "\n\n" + json.dumps(payload, indent=2)
        return ToolResult(success=True, output=output)

    def _home_assistant(self, args: dict[str, Any]) -> ToolResult:
        from ultra.homeassistant import HomeAssistantClient

        action = str(args.get("action") or "status")
        client = HomeAssistantClient(self.config)

        try:
            if action == "status":
                result = client.check_api()
            elif action == "states":
                result = client.get_states()
            elif action == "state":
                entity_id = args.get("entity_id")
                if not entity_id:
                    return ToolResult(success=False, output="entity_id is required for state")
                result = client.get_state(str(entity_id))
            elif action == "call_service":
                domain = args.get("domain")
                service = args.get("service")
                if not domain or not service:
                    return ToolResult(
                        success=False,
                        output="domain and service are required for call_service",
                    )
                result = client.call_service(
                    str(domain),
                    str(service),
                    entity_id=str(args["entity_id"]) if args.get("entity_id") else None,
                    data=args.get("service_data"),
                )
            else:
                return ToolResult(success=False, output=f"Unknown action: {action}")
        except RuntimeError as exc:
            return ToolResult(success=False, output=str(exc))

        if action == "states" and result.ok:
            text = client.summarize_states()
            return ToolResult(success=True, output=text)

        body = json.dumps(
            {
                "ok": result.ok,
                "status_code": result.status_code,
                "data": result.data,
                "error": result.error,
            },
            indent=2,
        )
        return ToolResult(success=result.ok, output=body)

    def _memory_search(self, args: dict[str, Any]) -> ToolResult:
        if not self.memory or not self.memory.enabled:
            return ToolResult(success=False, output="Memory is disabled")
        from ultra.memory.recall import format_recall_for_prompt

        bundle = self.memory.recall(args["query"], limit=int(args.get("limit") or 8))
        text = format_recall_for_prompt(bundle)
        if not text:
            return ToolResult(success=True, output="No matching memories found.")
        return ToolResult(success=True, output=text)

    def _memory_remember(self, args: dict[str, Any]) -> ToolResult:
        if not self.memory or not self.memory.enabled:
            return ToolResult(success=False, output="Memory is disabled")
        anchor_id = self.memory.remember(
            args["content"],
            anchor_type=str(args.get("anchor_type") or "fact"),
            importance=int(args.get("importance") or 3),
        )
        return ToolResult(success=True, output=f"Stored memory anchor {anchor_id}")

    def _personality_get(self, args: dict[str, Any]) -> ToolResult:
        if not self.personality or not self.personality.enabled:
            return ToolResult(success=False, output="Personality is disabled")
        body = json.dumps(self.personality.get_active_json(), indent=2)
        return ToolResult(success=True, output=body)

    def _personality_update(self, args: dict[str, Any]) -> ToolResult:
        if not self.personality or not self.personality.enabled:
            return ToolResult(success=False, output="Personality is disabled")
        try:
            body = self.personality.patch_active_profile_from_args(args)
        except (ValueError, RuntimeError) as exc:
            return ToolResult(success=False, output=str(exc))
        return ToolResult(success=True, output=json.dumps(body, indent=2))


def _format_proc(proc: subprocess.CompletedProcess[str]) -> str:
    parts = [f"exit_code={proc.returncode}"]
    if proc.stdout:
        parts.append(f"stdout:\n{proc.stdout}")
    if proc.stderr:
        parts.append(f"stderr:\n{proc.stderr}")
    return "\n".join(parts)


def _notify_email(cfg: dict[str, str], message: str, title: str | None) -> ToolResult:
    required = ["smtp_host", "username", "password", "from", "to"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        return ToolResult(success=False, output=f"Email config missing: {', '.join(missing)}")

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = cfg["to"]
    msg["Subject"] = title or "Ultra notification"
    msg.set_content(message)

    port = int(cfg.get("smtp_port") or 587)
    with smtplib.SMTP(cfg["smtp_host"], port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg["username"], cfg["password"])
        smtp.send_message(msg)

    return ToolResult(success=True, output="Email sent")
