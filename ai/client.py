import os
import json

from ollama import AsyncClient

from .commands import COMMANDS_SCHEMA
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

    async def _chat(self, chat_options):
        """Send one chat request and return (commands, response type name)."""
        response = await self.client.chat(**chat_options)
        response_message = self._field(response, "message")
        content = self._field(response_message, "content") or ""
        content = content.strip() if isinstance(content, str) else ""
        return self._parse_commands(content), f"{type(response).__name__}/{type(response_message).__name__}"

    @staticmethod
    def _parse_commands(content):
        if not content:
            return []

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, dict):
            return []

        commands = data.get("commands")
        if not isinstance(commands, list):
            return []

        return [
            command.strip()
            for command in commands
            if isinstance(command, str) and command.strip()
        ]

    async def respond(self, conversation, thread, settings, message):
        system = SYSTEM_PROMPT

        if settings.get("prompt"):
            system += f"\n\nSERVER PROMPT\n{settings['prompt']}"

        model = settings.get("model") or DEFAULT_MODEL
        allowed = set(settings.get("commands", []))
        available_commands = sorted({"reply", "close", *allowed})
        system += (
            "\n\nAVAILABLE COMMAND NAMES\n"
            + ", ".join(available_commands)
            + "\nUse only these command names. Never invent a command name."
        )
        messages = [
            {"role": "system", "content": system},
            *conversation,
        ]
        await self._debug(
            thread,
            settings,
            f"request started using {model}; context messages: {len(conversation)}",
        )

        chat_options = {
            "model": model,
            "messages": messages,
            "format": COMMANDS_SCHEMA,
            # Disabled so the response is the direct structured command output
            # instead of chain-of-thought reasoning.
            "think": True,
        }
        commands, response_type = await self._chat(chat_options)
        commands = commands[:MAX_TOOL_CALLS]

        await self._debug(
            thread,
            settings,
            f"model response: {response_type}; commands: {len(commands)}",
        )

        if not commands:
            await self.execute_command(
                f"reply {COMMAND_RESPONSE_FALLBACK}",
                thread,
                allowed,
                message,
            )
            await self._debug(
                thread,
                settings,
                "model returned no commands; fallback sent",
            )
            return None

        succeeded_user_facing = False
        for command in commands:
            if not thread.channel:
                break

            result = await self._run_command(command, thread, allowed, message)
            if self._command_succeeded(result):
                name = command.split(maxsplit=1)[0].lower()
                if name in {"reply", "close"}:
                    succeeded_user_facing = True

        if not succeeded_user_facing and thread.channel:
            await self.execute_command(
                f"reply {COMMAND_RESPONSE_FALLBACK}",
                thread,
                allowed,
                message,
            )
            await self._debug(
                thread, settings, "no reply/close command succeeded; fallback sent"
            )

        return None

    @staticmethod
    def _command_succeeded(result):
        return isinstance(result, str) and result.startswith("Command executed:")

    @staticmethod
    def _field(value, name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    async def _run_command(self, command, thread, allowed, message):
        if not isinstance(command, str) or not command.strip():
            return "Command failed: invalid command arguments."

        name = command.split(maxsplit=1)[0].lower()
        if name not in {"reply", "close", *allowed}:
            return f"Command denied: unknown command name: {name}"

        return await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

    async def close(self):
        await self.client._client.aclose()