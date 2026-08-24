import os

from ollama import AsyncClient

from .commands import COMMAND_TOOL
from .prompts import SYSTEM_PROMPT

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
COMMAND_RESPONSE_FALLBACK = (
    "I've taken care of that. Is there anything else I can help with?"
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

        # "reply" is always allowed regardless of server settings.
        allowed = set(settings.get("commands", []))
        allowed.add("reply")

        print("AI call")

        # There is exactly ONE AI call.
        response = await self.client.chat(
            model=model,
            messages=messages,
            tools=[COMMAND_TOOL],
        )

        assistant = response.message

        print(response)

        # The AI is required to use a tool.
        # If it somehow doesn't, send the fallback through the reply command.
        if not assistant.tool_calls:
            print("AI did not use a tool, sending fallback reply")

            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )

            return None

        # Extract the requested commands.
        calls = assistant.tool_calls

        # Only one reply is allowed.
        reply_call = None
        other_calls = []

        for call in calls:
            arguments = call.function.arguments

            if not isinstance(arguments, dict):
                continue

            command = arguments.get("command")

            if not isinstance(command, str):
                continue

            command = command.strip()

            if not command:
                continue

            name = command.split(maxsplit=1)[0].lower()

            if name == "reply":
                if reply_call is None:
                    reply_call = call
                else:
                    # Ignore additional reply commands.
                    continue
            else:
                other_calls.append(call)

        # Find commands that close the thread.
        close_calls = []
        normal_calls = []

        for call in other_calls:
            arguments = call.function.arguments

            command = arguments.get("command", "")
            name = command.split(maxsplit=1)[0].lower()

            if name == "close":
                close_calls.append(call)
            else:
                normal_calls.append(call)

        # Execute normal commands first.
        for call in normal_calls:
            if not thread.channel:
                break

            await self._run_command(
                call,
                thread,
                allowed,
                message,
            )

        # The reply MUST happen before close.
        if reply_call is not None and thread.channel:
            await self._run_command(
                reply_call,
                thread,
                allowed,
                message,
            )

        elif thread.channel:
            # The model failed to provide a reply.
            # Always provide one anyway.
            print("AI did not provide reply command, using fallback")

            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )

        # Close only after the reply has been sent.
        for call in close_calls:
            if not thread.channel:
                break

            await self._run_command(
                call,
                thread,
                allowed,
                message,
            )

        return None

    async def _run_command(self, call, thread, allowed, message):
        arguments = call.function.arguments

        if not isinstance(arguments, dict):
            return "Command failed: invalid command arguments."

        command = arguments.get("command")

        if not isinstance(command, str) or not command.strip():
            return "Command failed: no command was provided."

        return await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

    async def _run_reply(self, content, thread, allowed, message):
        command = f"reply {content}"

        return await self.execute_command(
            command,
            thread,
            allowed,
            message,
        )

    async def close(self):
        await self.client._client.aclose()