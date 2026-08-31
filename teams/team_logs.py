"""Core `logs` command overrides, folded in from the standalone logs plugin.

Filters the `.logs` command family so a team's closed tickets are only
visible to roles/users granted access via `{prefix}team logs access`.
"""

from typing import Optional

import discord

from core.paginator import EmbedPaginatorSession
from core.utils import User, safe_typing


async def visible_logs(bot, author, entries):
    """Filter entries only when the Teams cog is loaded."""
    teams = bot.get_cog("Teams")
    if teams is None:
        return entries
    return [entry for entry in entries if await teams.can_view_log(author, entry)]


def install(cog):
    """Swap the core `logs` command family's callbacks for team-aware versions."""
    if getattr(cog, "_log_command_originals", None) is not None:
        return

    logs_command = cog.bot.get_command("logs")
    if logs_command is None:
        return

    originals = {None: logs_command.callback}
    logs_command.callback = logs

    overrides = {
        "closed-by": closed_by,
        "key": key,
        "responded": responded,
        "search": search,
    }
    for name, callback in overrides.items():
        command = logs_command.get_command(name)
        if command is not None:
            originals[name] = command.callback
            command.callback = callback

    cog._log_command_originals = originals


def uninstall(cog):
    """Restore the original core `logs` command callbacks."""
    originals = getattr(cog, "_log_command_originals", None)
    if originals is None:
        return

    logs_command = cog.bot.get_command("logs")
    if logs_command is not None:
        for name, callback in originals.items():
            command = logs_command if name is None else logs_command.get_command(name)
            if command is not None:
                command.callback = callback

    cog._log_command_originals = None


async def logs(core_cog, ctx, *, user: User = None):
    async with safe_typing(ctx):
        pass

    if not user:
        thread = ctx.thread
        if not thread:
            return
        user = thread.recipient or await ctx.bot.get_or_fetch_user(thread.id)

    default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
    icon_url = getattr(user, "avatar_url", default_avatar)
    entries = await ctx.bot.api.get_user_logs(user.id)
    entries = [entry for entry in entries if not entry["open"]]
    entries = await visible_logs(ctx.bot, ctx.author, entries)

    if not entries:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="This user does not have any previous logs.",
        ))

    core_cog = ctx.command.cog
    embeds = core_cog.format_log_embeds(reversed(entries), avatar_url=icon_url)
    await EmbedPaginatorSession(ctx, *embeds).run()


async def closed_by(core_cog, ctx, *, user: User = None):
    user = user if user is not None else ctx.author
    entries = await ctx.bot.api.search_closed_by(user.id)
    entries = await visible_logs(ctx.bot, ctx.author, entries)
    core_cog = ctx.command.cog
    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="No log entries have been found for that query.",
        ))
    await EmbedPaginatorSession(ctx, *embeds).run()


async def key(core_cog, ctx, key: str):
    entries = await ctx.bot.api.find_log_entry(key)
    entries = await visible_logs(ctx.bot, ctx.author, entries)
    if not entries:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description=f"Log entry `{key}` not found.",
        ))
    core_cog = ctx.command.cog
    embeds = core_cog.format_log_embeds(entries, avatar_url=ctx.author.avatar.url)
    await EmbedPaginatorSession(ctx, *embeds).run()


async def responded(core_cog, ctx, *, user: User = None):
    user = user if user is not None else ctx.author
    entries = await ctx.bot.api.get_responded_logs(user.id)
    entries = await visible_logs(ctx.bot, ctx.author, entries)
    core_cog = ctx.command.cog
    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description=f"{getattr(user, 'mention', user.id)} has not responded to any threads.",
        ))
    await EmbedPaginatorSession(ctx, *embeds).run()


async def search(core_cog, ctx, limit: Optional[int] = None, *, query):
    async with safe_typing(ctx):
        pass

    entries = await ctx.bot.api.search_by_text(query, limit)
    entries = await visible_logs(ctx.bot, ctx.author, entries)
    core_cog = ctx.command.cog
    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="No log entries have been found for that query.",
        ))
    await EmbedPaginatorSession(ctx, *embeds).run()
