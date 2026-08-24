import copy

from discord.ext import commands


COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute one complete ModMail command. Put the command name first, "
            "followed by its arguments separated by spaces. <value> means "
            "required and [value] means optional. Brackets are notation only and "
            "must not be included in the command. Use only real command names "
            "available in the current command list; never invent one. To send a "
            "normal response, start the command with reply followed by the text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "One complete command string, including the command name "
                        "and any required arguments. Use the exact argument order "
                        "defined by the ModMail command. Do not add explanations, "
                        "formatting, or placeholder brackets."
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