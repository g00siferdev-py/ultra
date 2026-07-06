from __future__ import annotations



from typing import Any, Callable



from ultra.audit import AuditLog

from ultra.config import Config

from ultra.llm.base import LLMProvider

from ultra.llm.factory import create_provider

from ultra.memory.service import MemoryService

from ultra.personality import PersonalityManager, personality_system_hint

from ultra.prompts import HEADLESS_PROMPT, INTERACTIVE_PROMPT

from ultra.tools import ToolRegistry





class Agent:

    def __init__(self, config: Config, *, headless: bool = False) -> None:

        self.config = config

        self.headless = headless

        self.audit = AuditLog(config.audit_log)

        self.personality = PersonalityManager.load(config)

        memory_personality_id = (

            self.personality.active_profile_id()

            if self.personality.enabled

            else config.memory.personality_id

        )

        self.memory = MemoryService(

            config,

            startup_embed=True,

            personality_id=memory_personality_id,

        )

        self.tools = ToolRegistry(config, self.audit, self.memory, self.personality)

        self.provider: LLMProvider = create_provider(config)

        self.messages: list[dict[str, Any]] = [

            {"role": "system", "content": self._build_system_prompt()}

        ]



    def _build_system_prompt(self) -> str:

        parts: list[str] = []

        if self.personality.enabled:

            prefix = self.personality.system_prompt_prefix()

            if prefix.strip():

                parts.append(prefix)

                parts.append("\n\n---\n\n")

        base = HEADLESS_PROMPT if self.headless else INTERACTIVE_PROMPT

        parts.append(base.format(workspace=self.config.workspace))

        parts.append("\n\n")
        parts.append(self.config.integration_prompt_section())

        if self.memory.enabled:

            parts.append(

                "\n\nLong-term memory (Memory Anchor) is enabled. "

                "Use memory_search before assuming unknown user context. "

                "Use memory_remember for durable preferences and facts."

            )

        if not self.headless:
            parts.append(
                "\n\nPrefer the home_assistant tool for device control. "
                "Use network_discover only when config and discovered.json lack the target."
            )

        if self.personality.enabled and not self.headless:

            parts.append(personality_system_hint())

        if self.config.extra_instructions:

            parts.append(f"\n\n{self.config.extra_instructions}")

        return "".join(parts)



    def _refresh_system_prompt(self) -> None:

        if not self.messages or self.messages[0].get("role") != "system":

            return

        self.messages[0]["content"] = self._build_system_prompt()



    def run(
        self,
        user_input: str,
        max_turns: int = 25,
        *,
        on_tool_start: Callable[[str], None] | None = None,
    ) -> str:

        self.audit.record("user_message", content=user_input, headless=self.headless)



        user_content = user_input

        if (

            self.memory.enabled

            and self.config.memory.auto_recall

            and not self.headless

        ):

            ctx = self.memory.recall_context(user_input)

            if ctx:

                user_content = f"{user_input}\n\n{ctx}"



        self.messages.append({"role": "user", "content": user_content})



        tool_schemas = self._tool_definitions()



        for _ in range(max_turns):

            turn = self.provider.chat(self.messages, tool_schemas)



            if turn.tool_calls:

                self._append_assistant_tool_turn(turn)

                for call in turn.tool_calls:

                    if on_tool_start:

                        on_tool_start(call.name)

                    result = self.tools.execute(call.name, call.arguments)

                    self._append_tool_result(call, result.output)

                    if call.name == "personality_update" and result.success:

                        self._refresh_system_prompt()

                continue



            if turn.content:

                self.messages.append({"role": "assistant", "content": turn.content})

                self.audit.record("assistant_message", content=turn.content)

                if self.memory.enabled:

                    self.memory.after_turn(user_input, turn.content)

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


