import os

from ollama import AsyncClient

from .commands import COMMAND_TOOL
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
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

        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        calls = response.message.tool_calls or []

        if not calls:
            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )
            return None

        reply_calls = []
        close_calls = []
        other_calls = []

        for call in calls:
            command = self._get_command(call)

            if not command:
                continue

            name = command.split(maxsplit=1)[0].lower()

            if name == "reply":
                reply_calls.append(call)
            elif name == "close":
                close_calls.append(call)
            else:
                other_calls.append(call)

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
        for call in reply_calls:
            if not thread.channel:
                break

            await self._run_command(
                call,
                thread,
                allowed,
                message,
            )

        # Close can be used with or without reply.
        for call in close_calls:
            if not thread.channel:
                break

            await self._run_command(
                call,
                thread,
                allowed,
                message,
            )

        # Ensure every response produces a user-facing action.
        if not reply_calls and not close_calls and thread.channel:
            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )

        return None

    @staticmethod
    def _get_command(call):
        arguments = call.function.arguments

        if not isinstance(arguments, dict):
            return None

        command = arguments.get("command")

        if not isinstance(command, str):
            return None

        return command.strip() or None

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