import copy

from discord.ext import commands


COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute an approved Discord Modmail command. "
            "You MUST use this tool to perform actions and to reply to the user. "
            "You MUST execute exactly one reply command. "
            "The reply command should contain the complete response to the user. "
            "If closing the thread, the reply must happen before the close command."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The complete Modmail command to execute. "
                        "For a user response, use: "
                        "'reply <message>'. "
                        "For example: "
                        "'reply Hi! How can I help you today?'. "
                        "Do not merely describe what should be done."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


async def execute_command(command, thread, allowed, message):
    """Run a command when it is allowlisted."""

    if not isinstance(command, str):
        await thread.channel.send(
            "Command denied: it is not on the allowlist"
        )
        return "Command denied: it is not on the allowlist"

    command = command.strip()

    name = command.split(maxsplit=1)[0].lower() if command else ""

    # Reply is ALWAYS allowed and cannot be removed from the allowlist.
    if name != "reply" and command not in allowed and name not in allowed:
        await thread.channel.send(
            "Command denied: it is not on the allowlist"
        )
        return "Command denied: it is not on the allowlist"

    if not command:
        return "Command failed: no command was provided"

    await thread.channel.send(f"Executing: {command}")

    bot = thread.bot

    command_message = copy.copy(message)
    command_message.content = f"{bot.prefix}{command}"
    command_message.channel = thread.channel

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