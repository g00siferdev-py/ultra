from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from ultra.audit import AuditLog
from ultra.config import Config
from ultra.notify import send_discord, send_telegram


@dataclass
class ToolResult:
    success: bool
    output: str


ToolHandler = Callable[[dict[str, Any]], ToolResult]


class ToolRegistry:
    def __init__(self, config: Config, audit: AuditLog) -> None:
        self.config = config
        self.audit = audit
        self.workspace = config.workspace
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._handlers: dict[str, ToolHandler] = {
            "run_shell": self._run_shell,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "list_directory": self._list_directory,
            "http_request": self._http_request,
            "send_notification": self._send_notification,
        }

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
        ]

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
