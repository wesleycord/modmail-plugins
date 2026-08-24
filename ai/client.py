import os

from ollama import AsyncClient

from .commands import COMMAND_TOOL
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
COMMAND_RESPONSE_FALLBACK = (
    "I've taken care of that. Is there anything else I can help with?"
)


class AIClient:
    """Small Ollama client for chat and approved command execution."""

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

        # First AI call.
        # The AI decides whether it needs to execute commands.
        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        assistant = response.message

        # No commands needed.
        if not assistant.tool_calls:
            return assistant.content.strip()

        # Keep Ollama's original assistant message.
        messages.append(assistant)

        # Run every requested command sequentially.
        results = []

        for call in assistant.tool_calls:
            result = await self._run_command(
                call,
                thread,
                settings["commands"],
                message,
            )

            results.append(result)

            # Stop if a command closed the thread.
            if not thread.channel:
                return None

        # Give every command result back to Ollama.
        for result in results:
            messages.append({
                "role": "tool",
                "content": result,
            })

        # Final AI call.
        # Do NOT provide tools here.
        response = await self.client.chat(
            model=model,
            messages=messages,
        )

        content = response.message.content.strip()

        return content or COMMAND_RESPONSE_FALLBACK

    async def _run_command(self, call, thread, allowed, message):
        arguments = call.function.arguments

        if not isinstance(arguments, dict):
            return (
                "Command failed: invalid command arguments. "
                "Continue responding normally."
            )

        command = arguments.get("command")

        if not command:
            return (
                "Command failed: no command was provided. "
                "Continue responding normally."
            )

        return await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

    async def close(self):
        await self.client._client.aclose()