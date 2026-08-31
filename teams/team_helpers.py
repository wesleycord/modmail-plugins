"""Pure team configuration, target conversion, and embed display helpers."""

import discord
from discord.ext import commands


ACCESS_PERMISSIONS = ("view_channel", "read_message_history", "send_messages")


def find_team_exact(teams, name):
    return teams.get(name.strip().lower())


def find_team(teams, name):
    """Find a team by exact name, or by a unique name prefix."""
    candidate = name.strip().lower()
    if not candidate:
        return None

    team = teams.get(candidate)
    if team:
        return team

    matches = [team for key, team in teams.items() if key.startswith(candidate)]
    if len(matches) == 1:
        return matches[0]
    return None


def match_team(teams, text):
    """Find the longest team name match at the beginning of ``text``."""
    words = text.split()
    for index in range(len(words), 0, -1):
        team = find_team(teams, " ".join(words[:index]))
        if team:
            return team, " ".join(words[index:])
    return None, text


async def convert_role_member_user(ctx, text):
    for converter in (
        commands.RoleConverter,
        commands.MemberConverter,
        commands.UserConverter,
    ):
        try:
            return await converter().convert(ctx, text)
        except commands.BadArgument:
            continue
    return None


def permission_key(target):
    kind = "role" if isinstance(target, discord.Role) else "user"
    return f"{kind}:{target.id}"


def resolve_permission_target(guild, key):
    kind, separator, id_str = key.partition(":")
    if not separator:
        kind, id_str = "role", key
    try:
        target_id = int(id_str)
    except ValueError:
        return None
    if kind == "role":
        return guild.get_role(target_id)
    return guild.get_member(target_id) or discord.Object(id=target_id)


def new_team(name):
    return {
        "_id": name.strip().lower(),
        "name": name.strip(),
        "category_id": None,
        "permissions": {},
        "access": [],
        "log_access": [],
        "pings": [],
        "response": None,
        "note": None,
        "sync_permissions": True,
    }


def target_label(guild, key):
    kind, separator, id_str = key.partition(":")
    if not separator:
        kind, id_str = "role", key
    if kind == "role":
        role = guild.get_role(int(id_str))
        return role.mention if role else f"`{id_str}`"
    member = guild.get_member(int(id_str))
    return member.mention if member else f"<@{id_str}>"


def team_embed(bot, team):
    embed = discord.Embed(title=f"Team: {team['name']}", color=bot.main_color)
    guild = bot.modmail_guild
    category = guild.get_channel(team["category_id"]) if team["category_id"] else None
    embed.add_field(
        name="Category", value=category.mention if category else "Not set", inline=False
    )

    if team["permissions"]:
        lines = []
        for key, perms in team["permissions"].items():
            perms_str = ", ".join(f"{'+' if value else '-'}{permission}" for permission, value in perms.items())
            lines.append(f"{target_label(guild, key)}: {perms_str}")
        embed.add_field(name="Permissions", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Permissions", value="None set", inline=False)

    for field_name, title in (("access", "Thread Access"), ("log_access", "Log Access")):
        targets = team.get(field_name, [])
        value = " ".join(target_label(guild, key) for key in targets) if targets else "Not restricted"
        embed.add_field(name=title, value=value, inline=False)

    embed.add_field(
        name="Sync With Category",
        value="Enabled" if team.get("sync_permissions", True) else "Disabled",
        inline=False,
    )

    if team["pings"]:
        mentions = []
        for ping in team["pings"]:
            if ping["type"] == "role":
                role = guild.get_role(ping["id"])
                mentions.append(role.mention if role else f"`{ping['id']}`")
            else:
                mentions.append(f"<@{ping['id']}>")
        embed.add_field(name="Pings", value=" ".join(mentions), inline=False)
    else:
        embed.add_field(name="Pings", value="None set", inline=False)

    embed.add_field(name="User Response", value=team["response"] or "Not set", inline=False)
    embed.add_field(name="Staff Note", value=team["note"] or "Not set", inline=False)
    return embed