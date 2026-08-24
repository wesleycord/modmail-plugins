import os

from ollama import AsyncClient

from .commands import COMMAND_TOOL, execute_command
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
MAX_OUTPUT_TOKENS = 150
MAX_TOOL_CALLS = 2


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
        allowed = "\n".join(f"- {command}" for command in settings["commands"])
        system = SYSTEM_PROMPT.format(commands=allowed or "None")
        if settings.get("prompt"):
            system += f"\n\nSERVER PROMPT\n{settings['prompt']}"

        messages = [{"role": "system", "content": system}, *conversation]
        model = settings.get("model") or DEFAULT_MODEL

        for _ in range(MAX_TOOL_CALLS):
            response = await self.client.chat(
                model=model,
                messages=messages,
                tools=[COMMAND_TOOL],
            )
            print(response, 1011)
            assistant = response.message

            if not assistant.tool_calls:
                return assistant.content.strip()

            messages.append(assistant)
            for call in assistant.tool_calls:
                result = await self._run_command(call, thread, settings["commands"], message)
                messages.append({"role": "tool", "content": result})

        return "I could not complete that command. Please contact a moderator."

    async def _run_command(self, call, thread, allowed, message):
        arguments = call.function.arguments
        if not isinstance(arguments, dict):
            return "Command denied: invalid arguments."

        return await self.execute_command(
            arguments.get("command"),
            thread,
            allowed,
            message,
        )

    async def close(self):
        await self.client._client.aclose()
