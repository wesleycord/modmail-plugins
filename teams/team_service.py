"""Database updates and Discord ticket changes performed by Teams commands."""

import discord

from . import team_helpers


async def load_teams(cog):
    async for team in cog.coll.find():
        team.setdefault("sync_permissions", True)
        team.setdefault("access", [])
        team.setdefault("log_access", [])
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