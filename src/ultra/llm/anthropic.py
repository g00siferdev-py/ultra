from __future__ import annotations

from typing import Any

import anthropic

from ultra.llm.base import AssistantTurn, ToolCall


class AnthropicProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        system, api_messages = _split_messages(messages)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=api_messages,
            tools=tools,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        content = "\n".join(text_parts).strip() or None
        return AssistantTurn(content=content, tool_calls=tool_calls)


def _split_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg["role"]
        if role == "system":
            system_parts.append(msg["content"])
            continue
        api_messages.append(msg)

    return "\n\n".join(system_parts), api_messages
