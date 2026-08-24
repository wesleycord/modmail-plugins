import copy

from discord.ext import commands


COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": (
            "Execute a ModMail command. "
            "For every user message, execute at least one user-facing command "
            "using reply or close. "
            "reply and close are always allowed and may both be used; if both "
            "are used, reply must come before close. "
            "Other commands are only allowed when they are present in the "
            "server command allowlist. "
            "Command syntax: <value> is required and [value] is optional. "
            "Never include the angle brackets or square brackets in the command. "
            "A reply must always include a non-empty response. "
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
                    "minLength": 1,
                    "description": (
                        "The complete ModMail command. In the syntax below, "
                        "<value> is required and [value] is optional; do not "
                        "include the brackets in the command. Use one of these "
                        "formats:\n"
                        "- reply <response>\n"
                        "- close [time] [reason]\n\n"
                        "For close, both arguments are optional and can be used "
                        "independently. If the first argument is a duration such "
                        "as 5h30m, it is treated as <time>; otherwise it is "
                        "treated as <reason>. A second argument is always "
                        "treated as <reason>.\n\n"
                        "A reply without <response> is invalid.\n\n"
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

    if name == "reply" and len(command.split(maxsplit=1)) == 1:
        return "Command failed: reply requires a non-empty response"

    # These commands are always available to the AI.
    if name not in {"reply", "close"}:
        if command not in allowed and name not in allowed:
            return "Command denied: it is not on the allowlist"

    await thread.channel.send(f"Executing: {command}")

    bot = thread.bot

    print(1011, thread.channel, 1011)
    command_message = copy.copy(message)
    command_message.content = f"{bot.prefix}{command}"
    command_message.guild = getattr(thread.channel, "guild", None)
    command_message.attachments = []
    command_message.embeds = []
    command_message.stickers = []
    command_message.message_snapshots = []
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