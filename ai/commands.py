import copy

from discord.ext import commands


COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute a ModMail command. "
            "For every user message, execute at least one user-facing command: "
            "reply or close. "
            "reply and close are always allowed and may both be used. "
            "If both are used, reply must come before close. "
            "Other commands are only allowed when they are present in the "
            "server command allowlist. "
            "Be extremely careful with close: NEVER close a thread unless "
            "the current user message explicitly requests, confirms, or "
            "clearly instructs that the thread should be closed. "
            "Do not infer a request to close from greetings, resolved issues, "
            "thanks, inactivity, conversation endings, or general statements. "
            "Closing must be explicitly mentioned or unambiguously requested "
            "by the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The complete ModMail command. "
                        "Use one of these formats:\n"
                        "- reply <response>\n"
                        "- close\n"
                        "- close <time>\n"
                        "- close <reason>\n"
                        "- close <time> <reason>\n\n"
                        "For close, time and reason are both optional and "
                        "can be provided independently. "
                        "Time uses durations such as 5h30m.\n\n"
                        "IMPORTANT: Only use a close command when the user "
                        "explicitly asks or clearly confirms that the thread "
                        "should be closed. Never close based on assumptions, "
                        "conversation context, a greeting, thanks, inactivity, "
                        "or because the issue appears resolved.\n\n"
                        "Examples:\n"
                        "reply Thanks for the report!\n"
                        "close\n"
                        "close 5h30m\n"
                        "close No further information was provided\n"
                        "close 5h30m No further information was provided"
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

    # These commands are always available to the AI.
    if name not in {"reply", "close"}:
        if command not in allowed and name not in allowed:
            return "Command denied: it is not on the allowlist"

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