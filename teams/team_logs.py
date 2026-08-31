"""Restricted replacements for Modmail's read-only logs commands."""

import discord

from core.paginator import EmbedPaginatorSession
from core.utils import safe_typing

from . import team_helpers


async def can_view_log(teams_cog, author, log):
    team_name = log.get("team")
    team = team_helpers.find_team_exact(teams_cog.teams, team_name) if team_name else None
    if team is None:
        return True

    allowed_targets = set(team.get("log_access", []))
    if not allowed_targets:
        return True

    if await teams_cog.bot.is_owner(author):
        return True

    author_targets = {f"user:{author.id}"}
    author_targets.update(f"role:{role.id}" for role in getattr(author, "roles", ()))
    return not allowed_targets.isdisjoint(author_targets)


async def visible_logs(teams_cog, author, logs):
    return [log for log in logs if await can_view_log(teams_cog, author, log)]


async def restricted_logs_callback(core_cog, ctx, user=None):
    """Core's ``logs`` callback with team log-access filtering applied."""
    teams_cog = ctx.bot.get_cog("Teams")
    if teams_cog is None:
        return await core_cog.logs(ctx, user=user)

    async with safe_typing(ctx):
        pass

    if not user:
        thread = ctx.thread
        if not thread:
            # The original command's converter supplies this error before the
            # callback is reached, so this branch only protects direct calls.
            return
        user = thread.recipient or await ctx.bot.get_or_fetch_user(thread.id)

    default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
    icon_url = getattr(user, "avatar_url", default_avatar)
    logs = await ctx.bot.api.get_user_logs(user.id)
    logs = [log for log in logs if not log["open"]]
    logs = await visible_logs(teams_cog, ctx.author, logs)

    if not logs:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="This user does not have any previous logs.",
        ))

    embeds = core_cog.format_log_embeds(reversed(logs), avatar_url=icon_url)
    session = EmbedPaginatorSession(ctx, *embeds)
    await session.run()


async def restricted_logs_closed_by_callback(core_cog, ctx, user=None):
    user = user if user is not None else ctx.author
    teams_cog = ctx.bot.get_cog("Teams")
    entries = await ctx.bot.api.search_closed_by(user.id)
    if teams_cog is not None:
        entries = await visible_logs(teams_cog, ctx.author, entries)

    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="No log entries have been found for that query.",
        ))

    session = EmbedPaginatorSession(ctx, *embeds)
    await session.run()


async def restricted_logs_key_callback(core_cog, ctx, key):
    icon_url = ctx.author.avatar.url
    entries = await ctx.bot.api.find_log_entry(key)
    teams_cog = ctx.bot.get_cog("Teams")
    if teams_cog is not None:
        entries = await visible_logs(teams_cog, ctx.author, entries)

    if not entries:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description=f"Log entry `{key}` not found.",
        ))

    embeds = core_cog.format_log_embeds(entries, avatar_url=icon_url)
    session = EmbedPaginatorSession(ctx, *embeds)
    await session.run()


async def restricted_logs_responded_callback(core_cog, ctx, user=None):
    user = user if user is not None else ctx.author
    teams_cog = ctx.bot.get_cog("Teams")
    entries = await ctx.bot.api.get_responded_logs(user.id)
    if teams_cog is not None:
        entries = await visible_logs(teams_cog, ctx.author, entries)

    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description=f"{getattr(user, 'mention', user.id)} has not responded to any threads.",
        ))

    session = EmbedPaginatorSession(ctx, *embeds)
    await session.run()


async def restricted_logs_search_callback(core_cog, ctx, limit=None, *, query):
    async with safe_typing(ctx):
        pass

    entries = await ctx.bot.api.search_by_text(query, limit)
    teams_cog = ctx.bot.get_cog("Teams")
    if teams_cog is not None:
        entries = await visible_logs(teams_cog, ctx.author, entries)

    embeds = core_cog.format_log_embeds(
        entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
    )
    if not embeds:
        return await ctx.send(embed=discord.Embed(
            color=ctx.bot.error_color,
            description="No log entries have been found for that query.",
        ))

    session = EmbedPaginatorSession(ctx, *embeds)
    await session.run()


class TeamLogCallbacks:
    """Cog-shaped adapters that preserve Modmail's original command parsing."""

    async def logs(core_cog, ctx, *, user=None):
        return await restricted_logs_callback(core_cog, ctx, user)

    async def closed_by(core_cog, ctx, *, user=None):
        return await restricted_logs_closed_by_callback(core_cog, ctx, user)

    async def key(core_cog, ctx, key):
        return await restricted_logs_key_callback(core_cog, ctx, key)

    async def responded(core_cog, ctx, *, user=None):
        return await restricted_logs_responded_callback(core_cog, ctx, user)

    async def search(core_cog, ctx, limit=None, *, query):
        return await restricted_logs_search_callback(core_cog, ctx, limit, query=query)