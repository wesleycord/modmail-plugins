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

        # First call: let the AI decide whether it needs to execute
        # a command or can answer the user directly.
        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        assistant = response.message

        # The AI decided that no command is necessary.
        if not assistant.tool_calls:
            return assistant.content.strip()

        # Only execute the first requested command.
        call = assistant.tool_calls[0]

        result = await self._run_command(
            call,
            thread,
            settings["commands"],
            message,
        )

        # The command may have closed the thread.
        # Don't make another AI request if the thread is no longer open.
        if not thread.channel:
            return None

        # Add the assistant's tool call to the conversation.
        messages.append({
            "role": "assistant",
            "content": assistant.content or "",
            "tool_calls": assistant.tool_calls,
        })

        # Give the command result to the AI.
        messages.append({
            "role": "tool",
            "content": result,
        })

        # Second call: tools are intentionally NOT provided.
        # The AI can only use the command result to formulate
        # the final response.
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
                "No action was taken. "
                "Continue responding conversationally."
            )

        command = arguments.get("command")

        if not command:
            return (
                "No action was taken. "
                "Continue responding conversationally."
            )

        result = await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

        if result.startswith(("Command denied:", "Command failed:")):
            return (
                "No action was taken. "
                "Continue responding conversationally without "
                "mentioning command execution."
            )

        return result

    async def close(self):
        await self.client._client.aclose()