import asyncio
import os

from ollama import AsyncClient

from .commands import COMMAND_TOOL, execute_command
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
MAX_CALLS = 2
COMMAND_RESPONSE_FALLBACK = "I've taken care of that. Is there anything else I can help with?"


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

        messages = [{"role": "system", "content": system}, *conversation]
        model = settings.get("model") or DEFAULT_MODEL

        for _ in range(MAX_CALLS):
            response = await self.client.chat(
                model=model,
                messages=messages,
                tools=[COMMAND_TOOL],
            )
            assistant = response.message

            if not assistant.tool_calls:
                return assistant.content.strip()
            print(response, "resp")

            messages.append(assistant)

            # Run every tool call requested in this turn concurrently
            # instead of one at a time. If the model asks for 3 commands,
            # they all execute in parallel, so the round-trip only costs
            # as much as the slowest single command instead of the sum
            # of all of them.
            results = await asyncio.gather(
                *(
                    self._run_command(call, thread, settings["commands"], message)
                    for call in assistant.tool_calls
                )
            )
            for result in results:
                print(result, "r")
                messages.append({"role": "tool", "content": result})

        return assistant.content.strip() or COMMAND_RESPONSE_FALLBACK

    async def _run_command(self, call, thread, allowed, message):
        arguments = call.function.arguments
        if not isinstance(arguments, dict):
            return "No action was taken. Continue responding conversationally without mentioning command execution."

        result = await self.execute_command(
            arguments.get("command"),
            thread,
            allowed,
            message,
        )
        if result.startswith(("Command denied:", "Command failed:")):
            return "No action was taken. Continue responding conversationally without mentioning command execution."
        return result

    async def close(self):
        await self.client._client.aclose()