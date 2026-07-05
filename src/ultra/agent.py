from __future__ import annotations

from typing import Any

from ultra.audit import AuditLog
from ultra.config import Config
from ultra.llm.base import LLMProvider
from ultra.llm.factory import create_provider
from ultra.prompts import HEADLESS_PROMPT, INTERACTIVE_PROMPT
from ultra.tools import ToolRegistry


class Agent:
    def __init__(self, config: Config, *, headless: bool = False) -> None:
        self.config = config
        self.headless = headless
        self.audit = AuditLog(config.audit_log)
        self.tools = ToolRegistry(config, self.audit)
        self.provider: LLMProvider = create_provider(config)
        base_prompt = HEADLESS_PROMPT if headless else INTERACTIVE_PROMPT
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": base_prompt.format(workspace=config.workspace)
                + (f"\n\n{config.extra_instructions}" if config.extra_instructions else ""),
            }
        ]

    def run(self, user_input: str, max_turns: int = 25) -> str:
        self.audit.record("user_message", content=user_input, headless=self.headless)
        self.messages.append({"role": "user", "content": user_input})

        tool_schemas = self._tool_definitions()

        for _ in range(max_turns):
            turn = self.provider.chat(self.messages, tool_schemas)

            if turn.tool_calls:
                self._append_assistant_tool_turn(turn)
                for call in turn.tool_calls:
                    result = self.tools.execute(call.name, call.arguments)
                    self._append_tool_result(call, result.output)
                continue

            if turn.content:
                self.messages.append({"role": "assistant", "content": turn.content})
                self.audit.record("assistant_message", content=turn.content)
                return turn.content

            return "(no response)"

        return "Stopped: reached maximum tool turns."

    def _tool_definitions(self) -> list[dict[str, Any]]:
        if self.config.provider == "anthropic":
            return self.tools.anthropic_tools()
        return self.tools.schemas()

    def _append_assistant_tool_turn(self, turn) -> None:
        if self.config.provider == "anthropic":
            content: list[dict[str, Any]] = []
            if turn.content:
                content.append({"type": "text", "text": turn.content})
            for call in turn.tool_calls:
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            self.messages.append({"role": "assistant", "content": content})
            return

        import json

        self.messages.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in turn.tool_calls
                ],
            }
        )

    def _append_tool_result(self, call, output: str) -> None:
        if self.config.provider == "anthropic":
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": output,
                        }
                    ],
                }
            )
            return

        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": output,
            }
        )
