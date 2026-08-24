import copy

from discord.ext import commands

COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": "Run one approved Discord assistant command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "One command name from the server allowlist.",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


async def execute_command(command, thread, allowed, message):
    """Run a command only when its exact name is allowlisted."""
    if not isinstance(command, str):
        return "Command denied: it is not on the allowlist"

    command = command.strip().lower()
    name = command.split(maxsplit=1)[0] if command else ""
    if command not in allowed and name not in allowed:
        return "Command denied: it is not on the allowlist"

    bot = thread.bot
    command_message = copy.copy(message)
    command_message.content = f"{bot.prefix}{command}"
    command_message.channel = thread.channel

    context = await bot.get_context(command_message)
    context.thread = thread
    if context.command is None:
        return "Command failed: the bot command was not found"

    try:
        command_message.author = bot.user
        if not await bot.can_run(context, call_once=True):
            return "Command failed: the bot is not allowed to run it"

        await context.command.invoke(context)
    except commands.CommandError as error:
        return f"Command failed: {error}"
    except Exception as error:
        bot.logger.exception("AI command failed: %s", command)
        return f"Command failed: {error}"

    if context.command_failed:
        return f"Command failed: {command}"

    return f"Command executed: {command}"
