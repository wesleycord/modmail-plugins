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
            "tools": [COMMAND_TOOL],
            # Thinking models (e.g. qwen3) can burn the whole response on
            # reasoning and leave `content` empty; force a direct answer.
            "think": False,
        }
        response = await self.client.chat(**chat_options)

        response_message = self._field(response, "message")
        calls = self._field(response_message, "tool_calls") or []
        content = self._field(response_message, "content") or ""
        has_content = isinstance(content, str) and bool(content.strip())
        if not has_content:
            # Some models still leak the answer into `thinking` even with think=False.
            thinking = self._field(response_message, "thinking") or ""
            if isinstance(thinking, str) and thinking.strip():
                content = thinking.strip()
                has_content = True
        await self._debug(
            thread,
            settings,
            "model response: "
            f"{type(response).__name__}/{type(response_message).__name__}; "
            f"raw tool calls: {len(calls) if isinstance(calls, list) else 'invalid'}",
        )

        if not calls:
            if has_content:
                if not thread.channel:
                    await self._debug(
                        thread,
                        settings,
                        "thread is closed; normal model response was not sent",
                    )
                    return None

                await self._run_reply(
                    content.strip(),
                    thread,
                    allowed,
                    message,
                )
                await self._debug(thread, settings, "normal model response sent as reply command")
                return None

            await self._run_reply(
                COMMAND_RESPONSE_FALLBACK,
                thread,
                allowed,
                message,
            )
            await self._debug(
                thread,
                settings,
                "model returned no tool calls; fallback tool command sent",
            )
            return None

        reply_calls = []
        close_calls = []
        other_calls = []
        parsed_commands = []

        valid_calls = 0
        for call in calls[:MAX_TOOL_CALLS] if isinstance(calls, list) else []:
            command = self._get_command(call)

            if not command:
                continue
            valid_calls += 1

            name = command.split(maxsplit=1)[0].lower()
            parsed_commands.append(name)

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
            f"{len(other_calls)} other; commands: "
            f"{', '.join(parsed_commands) or 'none'}",
        )

        if has_content and thread.channel:
            await thread.channel.send(f"**AI:** {content.strip()}")
            await self._debug(thread, settings, "content sent with tool command(s)")

        if not reply_calls and not close_calls:
            if has_content:
                await thread.channel.send(f"**AI:** {content.strip()}")
                await self._debug(
                    thread,
                    settings,
                    "content sent; no valid user-facing tool command",
                )
                return None

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
            successful_close |= self._command_succeeded(result)

        if not has_content and not successful_reply and not successful_close and thread.channel:
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

        name = command.split(maxsplit=1)[0].lower()
        if name not in {"reply", "close", *allowed}:
            return f"Command denied: unknown command name: {name}"

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