"""Database updates and Discord ticket changes performed by Teams commands."""

import io
from datetime import datetime

import discord
from core import thread as core_thread

from . import team_helpers


async def load_teams(cog):
    async for team in cog.coll.find():
        team.setdefault("sync_permissions", True)
        team.setdefault("access", [])
        team.setdefault("log_access", [])
        team.setdefault("log_channel_id", None)
        team.setdefault("log_status", True)
        cog.teams[team["_id"]] = team


async def save_team(cog, team):
    await cog.coll.find_one_and_update(
        {"_id": team["_id"]}, {"$set": team}, upsert=True
    )
    cog.teams[team["_id"]] = team


async def save_thread_team(cog, thread, team):
    await cog.bot.api.logs.update_one(
        {"channel_id": str(thread.channel.id)},
        {"$set": {"team": team["name"]}},
    )
    _channel_team_cache[thread.channel.id] = team


# ----- per-team log channel redirection -------------------------------
#
# Core posts the closed-thread transcript embed to ``bot.log_channel``, a
# property with no knowledge of which team (if any) a thread belongs to. To
# redirect that single post per team, we wrap ``Thread._close`` to stash the
# team's configured channel id on the bot for the duration of the close, and
# patch the ``log_channel`` property to prefer that override when present.

_original_thread_close = None
_original_log_channel_property = None

# Shared cache of channel id -> team dict (or None), used by both the log
# channel redirection above and the database logging gate below. Team dicts
# are the same objects stored in ``cog.teams``, so in-place edits (e.g. from
# `team logs status`) are reflected immediately without invalidating this.
_channel_team_cache = {}


def install_log_channel_override(cog):
    global _original_thread_close, _original_log_channel_property

    if _original_thread_close is None:
        _original_thread_close = core_thread.Thread._close

        async def patched_close(self, *args, **kwargs):
            channel_id = self.channel.id if self.channel else None
            self.bot._team_log_channel_override = await _team_log_channel_id(cog, self)
            self.bot._team_log_transcript_data = None
            try:
                await _original_thread_close(self, *args, **kwargs)
            finally:
                self.bot._team_log_channel_override = None
                self.bot._team_log_transcript_data = None
                if channel_id is not None:
                    _channel_team_cache.pop(channel_id, None)

        core_thread.Thread._close = patched_close

    bot_cls = type(cog.bot)
    if _original_log_channel_property is None:
        _original_log_channel_property = bot_cls.log_channel

        def patched_log_channel(bot_self):
            channel_id = getattr(bot_self, "_team_log_channel_override", None)
            channel = bot_self.get_channel(channel_id) if channel_id else None
            if channel is None:
                channel = _original_log_channel_property.fget(bot_self)
            if channel is None:
                return None

            log_data = getattr(bot_self, "_team_log_transcript_data", None)
            if log_data:
                return _TranscriptChannelProxy(channel, log_data)
            return channel

        bot_cls.log_channel = property(patched_log_channel)


def uninstall_log_channel_override(cog):
    global _original_thread_close, _original_log_channel_property

    if _original_thread_close is not None:
        core_thread.Thread._close = _original_thread_close
        _original_thread_close = None

    if _original_log_channel_property is not None:
        type(cog.bot).log_channel = _original_log_channel_property
        _original_log_channel_property = None


async def _resolve_team_for_channel(cog, channel_id):
    """Look up (and cache) the team assigned to a thread's channel, if any."""
    if channel_id in _channel_team_cache:
        return _channel_team_cache[channel_id]

    team = None
    try:
        log_entry = await cog.bot.api.get_log(channel_id)
    except Exception:
        log_entry = None
    team_name = log_entry.get("team") if log_entry else None
    if team_name:
        team = team_helpers.find_team_exact(cog.teams, team_name)

    _channel_team_cache[channel_id] = team
    return team


async def _team_log_channel_id(cog, thread):
    """Resolve the configured log channel id for the team assigned to ``thread``, if any."""
    if thread.channel is None:
        return None
    team = await _resolve_team_for_channel(cog, thread.channel.id)
    return team.get("log_channel_id") if team else None


# ----- plain-text transcript attachment ---------------------------------
#
# Attach a `Modmail-Log-<recipient>.txt` transcript alongside the embed core
# posts to the log channel on thread close.

_TYPE_TAGS = {
    "thread_message": "SENT",
    "anonymous": "ANON",
    "note": "NOTE",
    "internal": "SYSTEM",
}


class _TranscriptChannelProxy:
    """Wraps a channel so its next `send` call also attaches a transcript file."""

    def __init__(self, channel, log_data):
        self._channel = channel
        self._log_data = log_data

    def __getattr__(self, name):
        return getattr(self._channel, name)

    async def send(self, *args, **kwargs):
        kwargs.setdefault("file", build_transcript_file(self._log_data))
        return await self._channel.send(*args, **kwargs)


def _format_header_timestamp(value):
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y - %H:%M")
    except (TypeError, ValueError):
        return value or "Unknown"


def _format_message_timestamp(value):
    try:
        return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        return ""


def build_transcript_text(log_data):
    divider = "─" * 50
    recipient = log_data.get("recipient") or {}
    creator = log_data.get("creator") or recipient
    closer = log_data.get("closer") or {}

    lines = [
        f"Thread created at {_format_header_timestamp(log_data.get('created_at'))} UTC",
        f"[{'M' if creator.get('mod') else 'R'}] {creator.get('name')} "
        f"({creator.get('id')}) created a Modmail thread. ",
        divider,
    ]

    for message in log_data.get("messages", []):
        author = message.get("author") or {}
        tag = _TYPE_TAGS.get(message.get("type"), "SENT")
        role = "M" if author.get("mod") else "R"
        timestamp = _format_message_timestamp(message.get("timestamp"))
        lines.append(f"{timestamp} [{tag}] {role} {author.get('name')}: {message.get('content')}")

    lines.append(divider)
    if closer:
        lines.append(
            f"[{'M' if closer.get('mod') else 'R'}] {closer.get('name')} "
            f"({closer.get('id')}) closed the Modmail thread. "
        )
    lines.append(f"Thread closed at {_format_header_timestamp(log_data.get('closed_at'))} UTC")

    return "\n".join(lines) + "\n"


def build_transcript_file(log_data):
    recipient = log_data.get("recipient") or {}
    filename = f"Modmail-Log-{recipient.get('name', 'unknown')}.txt"
    buffer = io.BytesIO(build_transcript_text(log_data).encode("utf-8"))
    return discord.File(buffer, filename=filename)


# ----- per-team database logging status -------------------------------
#
# When a team's `log_status` is disabled, new ticket messages and the
# closing summary are not persisted to the database for threads assigned to
# that team. The log entry created when the thread is first opened (before
# any team is assigned) is left untouched.

_original_append_log = None
_original_post_log = None


def install_database_logging_override(cog):
    global _original_append_log, _original_post_log
    api_cls = type(cog.bot.api)

    if _original_append_log is None:
        _original_append_log = api_cls.append_log

        async def patched_append_log(self, message, **kwargs):
            channel_id = kwargs.get("channel_id")
            if channel_id is not None:
                team = await _resolve_team_for_channel(cog, int(channel_id))
                if team is not None and not team.get("log_status", True):
                    return None
            return await _original_append_log(self, message, **kwargs)

        api_cls.append_log = patched_append_log

    if _original_post_log is None:
        _original_post_log = api_cls.post_log

        async def patched_post_log(self, channel_id, data):
            team = await _resolve_team_for_channel(cog, int(channel_id))
            if team is not None and not team.get("log_status", True):
                self.bot._team_log_transcript_data = None
                return None
            result = await _original_post_log(self, channel_id, data)
            self.bot._team_log_transcript_data = result
            return result

        api_cls.post_log = patched_post_log


def uninstall_database_logging_override(cog):
    global _original_append_log, _original_post_log
    api_cls = type(cog.bot.api)

    if _original_append_log is not None:
        api_cls.append_log = _original_append_log
        _original_append_log = None

    if _original_post_log is not None:
        api_cls.post_log = _original_post_log
        _original_post_log = None


async def update_access(cog, ctx, arguments, field, label):
    team, rest = team_helpers.match_team(cog.teams, arguments)
    if not team:
        return await ctx.send(embed=discord.Embed(
            color=cog.bot.error_color,
            description="No matching team found in that command.",
        ))

    parts = rest.split()
    if not parts:
        targets = team.get(field, [])
        value = (
            " ".join(
                team_helpers.target_label(cog.bot.modmail_guild, key)
                for key in targets
            )
            if targets else "Not restricted"
        )
        return await ctx.send(embed=discord.Embed(
            color=cog.bot.main_color,
            title=f"{label}: {team['name']}",
            description=value,
        ))

    action, *target_texts = parts
    action = action.lower()
    if action not in ("add", "remove") or not target_texts:
        return await ctx.send(embed=discord.Embed(
            color=cog.bot.error_color,
            description="Provide `add` or `remove` and at least one role or user.",
        ))

    targets = []
    not_found = []
    for text in target_texts:
        target = await team_helpers.convert_role_member_user(ctx, text)
        if target is None:
            not_found.append(text)
        else:
            targets.append(target)

    if not targets:
        return await ctx.send(embed=discord.Embed(
            color=cog.bot.error_color,
            description=f"Could not find a role or user matching: {', '.join(not_found)}",
        ))

    configured_targets = team.setdefault(field, [])
    for target in targets:
        key = team_helpers.permission_key(target)
        if action == "add" and key not in configured_targets:
            configured_targets.append(key)
        elif action == "remove" and key in configured_targets:
            configured_targets.remove(key)

    await save_team(cog, team)
    description = (
        f"{'Added' if action == 'add' else 'Removed'} "
        f"{', '.join(target.mention for target in targets)} "
        f"{'to' if action == 'add' else 'from'} {label.lower()} for team `{team['name']}`."
    )
    if not_found:
        description += f"\nCould not find: {', '.join(not_found)}"
    await ctx.send(embed=discord.Embed(color=cog.bot.main_color, description=description))


async def apply_permissions(cog, thread, team, guild, reason):
    for key, permissions in team["permissions"].items():
        target = team_helpers.resolve_permission_target(guild, key)
        if target is None:
            continue
        overwrite = thread.channel.overwrites_for(target)
        for permission, value in permissions.items():
            setattr(overwrite, permission, value)
        await thread.channel.set_permissions(target, overwrite=overwrite, reason=reason)


async def apply_access(cog, thread, team, guild, reason):
    for key in team.get("access", []):
        target = team_helpers.resolve_permission_target(guild, key)
        if target is None:
            continue
        overwrite = thread.channel.overwrites_for(target)
        for permission in team_helpers.ACCESS_PERMISSIONS:
            setattr(overwrite, permission, True)
        await thread.channel.set_permissions(target, overwrite=overwrite, reason=reason)


async def apply_team(cog, thread, team, *, guild, reason):
    guild = guild or cog.bot.modmail_guild
    if guild is None:
        return (
            "This action cannot continue because the thread is not associated "
            "with a guild. Please retry from a server channel."
        )

    if team["category_id"]:
        category = guild.get_channel(team["category_id"])
        if not isinstance(category, discord.CategoryChannel):
            return (
                f"Team `{team['name']}` has an invalid category configured. "
                f"Use `{cog.bot.prefix}team category` to update it."
            )
        await thread.channel.edit(
            category=category,
            sync_permissions=team.get("sync_permissions", True),
            reason=reason,
        )

    await apply_permissions(cog, thread, team, guild, "Team permissions.")
    await apply_access(cog, thread, team, guild, "Team access.")

    if team["pings"]:
        mentions = []
        for ping in team["pings"]:
            if ping["type"] == "role":
                role = guild.get_role(ping["id"])
                if role:
                    mentions.append(role.mention)
            else:
                mentions.append(f"<@{ping['id']}>")
        if mentions:
            await thread.channel.send(
                " ".join(mentions),
                allowed_mentions=discord.AllowedMentions(roles=True, users=True),
            )

    if team["note"]:
        await thread.channel.send(embed=discord.Embed(
            title="Staff Note",
            description=team["note"],
            color=cog.bot.mod_color,
        ))

    if team["response"]:
        await thread.recipient.send(embed=discord.Embed(
            title=cog.bot.config["thread_move_title"],
            description=team["response"],
            color=cog.bot.main_color,
        ))

    await save_thread_team(cog, thread, team)
    return None