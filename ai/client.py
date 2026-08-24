import os
import json

from ollama import AsyncClient

from .commands import COMMAND_TOOL
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
MAX_TOOL_CALLS = 4
COMMAND_RESPONSE_FALLBACK = (
    "Sorry, I encountered an unexpected issue while processing your request. "
    "Please contact a server administrator for assistance."
)


class AIClient:
    """Ollama client for AI-driven Modmail command execution."""

    def __init__(self, execute_command):
        url = os.getenv("OLLAMA_URL")

        if not url:
            raise RuntimeError("Missing OLLAMA_URL in environment variables")

        self.client = AsyncClient(host=url.rstrip("/"))
        self.execute_command = execute_command

    async def models(self):
        response = await self.client.list()
        return [model.model for model in response.models]

    async def _debug(self, thread, settings, text):
        if settings.get("debug") and thread.channel:
            await thread.channel.send(f"**AI:** [DEBUG] {text}")

    async def respond(self, conversation, thread, settings, message):
        system = SYSTEM_PROMPT

        if settings.get("prompt"):
            system += f"\n\nSERVER PROMPT\n{settings['prompt']}"

        messages = [
            {"role": "system", "content": system},
            *conversation,
        ]

        model = settings.get("model") or DEFAULT_MODEL
        allowed = set(settings.get("commands", []))
        await self._debug(
            thread,
            settings,
            f"request started using {model}; context messages: {len(conversation)}",
        )

        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        response_message = self._field(response, "message")
        calls = self._field(response_message, "tool_calls") or []
        await self._debug(
            thread,
            settings,
            "model response: "
            f"{type(response).__name__}/{type(response_message).__name__}; "
            f"raw tool calls: {len(calls) if isinstance(calls, list) else 'invalid'}",
        )

        if not calls:
            assistant_text = self._field(response_message, "content") or ""
            if isinstance(assistant_text, str) and assistant_text.strip():
                await self._run_reply(
                    assistant_text.strip(),
                    thread,
                    allowed,
                    message,
                )
                await self._debug(thread, settings, "text response sent")
                return None

            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )
            await self._debug(thread, settings, "empty model response; fallback sent")
            return None

        reply_calls = []
        close_calls = []
        other_calls = []

        valid_calls = 0
        for call in calls[:MAX_TOOL_CALLS] if isinstance(calls, list) else []:
            command = self._get_command(call)

            if not command:
                continue
            valid_calls += 1

            name = command.split(maxsplit=1)[0].lower()

            if name == "reply":
                reply_calls.append(call)
            elif name == "close":
                close_calls.append(call)
            else:
                other_calls.append(call)

        await self._debug(
            thread,
            settings,
            f"parsed {valid_calls} valid command(s): "
            f"{len(reply_calls)} reply, {len(close_calls)} close, "
            f"{len(other_calls)} other",
        )

        if not reply_calls and not close_calls:
            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )
            await self._debug(thread, settings, "no valid command; fallback sent")
            return None

        # Execute other commands first.
        for call in other_calls:
            if not thread.channel:
                break

            await self._run_command(
                call,
                thread,
                allowed,
                message,
            )

        # Reply always happens before close.
        successful_reply = False
        for call in reply_calls:
            if not thread.channel:
                break

            result = await self._run_command(
                call,
                thread,
                allowed,
                message,
            )
            await self._debug(thread, settings, f"reply result: {result}")
            successful_reply |= self._command_succeeded(result)

        # Close can be used with or without reply.
        successful_close = False
        for call in close_calls:
            if not thread.channel:
                break

            result = await self._run_command(
                call,
                thread,
                allowed,
                message,
            )
            await self._debug(thread, settings, f"close result: {result}")
            successful_close |= self._command_succeeded(result)

        if not successful_reply and not successful_close and thread.channel:
            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )
            await self._debug(thread, settings, "all user-facing commands failed; fallback sent")

        return None

    @staticmethod
    def _command_succeeded(result):
        return isinstance(result, str) and result.startswith("Command executed:")

    @staticmethod
    def _get_command(call):
        function = AIClient._field(call, "function")
        if function is None or AIClient._field(
            function, "name", "execute_command"
        ) != "execute_command":
            return None

        arguments = AIClient._field(function, "arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None

        if not isinstance(arguments, dict):
            return None

        command = arguments.get("command")

        if not isinstance(command, str):
            return None

        return command.strip() or None

    @staticmethod
    def _field(value, name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    async def _run_command(self, call, thread, allowed, message):
        command = self._get_command(call)

        if not command:
            return "Command failed: invalid command arguments."

        return await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

    async def _run_reply(self, content, thread, allowed, message):
        return await self.execute_command(
            f"reply {content}",
            thread,
            allowed,
            message,
        )

    async def close(self):
        await self.client._client.aclose()