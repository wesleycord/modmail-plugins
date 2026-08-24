import copy

from discord.ext import commands


COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute one or more ModMail commands for the current user message. "
            "Always use reply or close for a user-facing result. Both may be used, "
            "but reply must come before close. Other commands require the server "
            "allowlist. Syntax uses <required> and [optional] placeholders; do "
            "not include the brackets. reply requires non-empty text. Only close "
            "when the current user explicitly asks or clearly confirms it; never "
            "infer close from thanks, resolution, inactivity, or conversation end."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Complete command. <value> is required and [value] is "
                        "optional; do not include brackets. Formats:\n"
                        "- reply <response>\n"
                        "- close\n"
                        "- close <silent|silently|cancel>\n"
                        "- close <silent|silently> <duration>\n\n"
                        "For close, use only the forms above. A duration uses "
                        "formats such as 5h30m. Close only on an explicit user "
                        "request; do not add a reason because the command does "
                        "not support one.\n\n"
                        "Examples:\n"
                        "reply Thanks for the report!\n"
                        "close\n"
                        "close silent\n"
                        "close silently 5h30m"
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


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