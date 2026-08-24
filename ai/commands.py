import copy

from discord.ext import commands


# Structured-output schema (used as Ollama's `format`) instead of native
# function/tool calling, which small local models like qwen3 call unreliably.
COMMANDS_SCHEMA = {
    "type": "object",
    "properties": {
        "commands": {
            "type": "array",
            "description": (
                "One or more complete ModMail commands to run, in order. Each "
                "command string starts with the command name, followed by its "
                "arguments separated by spaces. <value> means required and "
                "[value] means optional; brackets are notation only and must "
                "not be included. Use only real command names available in "
                "the current command list; never invent one."
            ),
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
    },
    "required": ["commands"],
    "additionalProperties": False,
}

COMMAND_INSTRUCTIONS = """
RESPONSE FORMAT
Respond with exactly one JSON object: {"commands": ["<command>", ...]}. List
one or more complete commands to run in order. Output nothing else — no
prose, no explanation, no text outside the JSON object.

At least one command must be `reply` or `close`. Only use command names
exactly as listed under AVAILABLE COMMAND NAMES below; inventing a command
(e.g. "ask", "report_user") is rejected and wastes the response. `reply`
always needs real text after it (e.g. "reply Thanks for reaching out!");
never send `reply` alone.

Default to `reply`. Only use `close` when the user clearly confirms the
issue is resolved or needs no further help, or is abusive/off-topic with
nothing left to assist with. A greeting or ordinary message is never a
reason to close by itself.
"""


def build_command_prompt(available_commands):
    """Command-response instructions plus the current command allowlist."""
    return (
        COMMAND_INSTRUCTIONS
        + "\nAVAILABLE COMMAND NAMES\n"
        + ", ".join(available_commands)
        + "\nUse only these command names. Never invent a command name."
    )


async def execute_command(command, thread, allowed, message):
    """Run an AI command when it is allowed."""

    if not isinstance(command, str):
        return "Command denied: invalid command"

    command = command.strip()

    if not command:
        return "Command failed: no command was provided"

    name = command.split(maxsplit=1)[0].lower()

    if name == "reply" and len(command.split(maxsplit=1)) == 1:
        return "Command failed: reply requires a non-empty response"

    # These commands are always available to the AI.
    if name not in {"reply", "close"}:
        if command not in allowed and name not in allowed:
            return "Command denied: it is not on the allowlist"

    await thread.channel.send(f"**AI:** {command}")

    bot = thread.bot

    command_message = copy.copy(message)
    command_message.content = f"{bot.prefix}{command}"
    command_message.attachments = []
    command_message.embeds = []
    command_message.stickers = []
    command_message.message_snapshots = []

    context = await bot.get_context(command_message)
    context.thread = thread

    if context.command is None:
        return f"Command failed: {command} — command was not found"

    try:
        command_message.author = bot.user

        if not await bot.can_run(context, call_once=True):
            return (
                f"Command failed: {command} — "
                "bot is not allowed to run it"
            )

        await context.command.invoke(context)

    except commands.CommandError as error:
        return f"Command failed: {command} — {error}"

    except Exception as error:
        bot.logger.exception("AI command failed: %s", command)
        return f"Command failed: {command} — {error}"

    if context.command_failed:
        return f"Command failed: {command}"

    return f"Command executed: {command}"