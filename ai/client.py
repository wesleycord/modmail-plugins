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

        # First AI call:
        # Let the AI decide whether commands need to be executed.
        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        assistant = response.message

        # The AI decided that no command is necessary.
        if not assistant.tool_calls:
            return assistant.content.strip()

        # Preserve the assistant's tool calls in the conversation.
        messages.append({
            "role": "assistant",
            "content": assistant.content or "",
            "tool_calls": assistant.tool_calls,
        })

        # Execute commands sequentially in the exact order requested.
        results = []

        for call in assistant.tool_calls:
            result = await self._run_command(
                call,
                thread,
                settings["commands"],
                message,
            )

            results.append(result)

            # A command may have closed the thread.
            if not thread.channel:
                return None

        # Give all command results to the final AI call.
        for result in results:
            messages.append({
                "role": "tool",
                "content": result,
            })

        # Final AI call:
        # No tools are provided, so the AI can only formulate a response.
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
                "Command denied: invalid command arguments. "
                "Continue responding normally."
            )

        command = arguments.get("command")

        if not command:
            return (
                "Command denied: no command was provided. "
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