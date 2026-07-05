from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from ultra.llm.base import AssistantTurn, ToolCall


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key or "unused"}
        if base_url:
            kwargs["base_url"] = base_url
        if default_headers:
            kwargs["default_headers"] = default_headers
        self.client = OpenAI(**kwargs)
        self.model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AssistantTurn:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
        )
        choice = response.choices[0].message
        tool_calls: list[ToolCall] = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                tool_calls.append(
                    ToolCall(id=tc.id, name=tc.function.name, arguments=args)
                )
        return AssistantTurn(content=choice.content, tool_calls=tool_calls)
