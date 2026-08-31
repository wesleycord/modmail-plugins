from typing import Union

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Teams(commands.Cog):
    """Move threads to configurable teams instead of raw categories."""

    def __init__(self, bot, old_move=None):
        self.bot = bot
        self.coll = bot.plugin_db.get_partition(self)
        self.teams = {}
        self._old_move = old_move

    async def cog_load(self):
        async for doc in self.coll.find():
            self.teams[doc["_id"]] = doc

    def cog_unload(self):
        self.bot.remove_command("move")
        if self._old_move is not None:
            self.bot.add_command(self._old_move)

    # ----- helpers -----------------------------------------------------

    def find_team(self, name):
        return self.teams.get(name.strip().lower())

    async def save_team(self, team):
        await self.coll.find_one_and_update(
            {"_id": team["_id"]}, {"$set": team}, upsert=True
        )
        self.teams[team["_id"]] = team

    @staticmethod
    def new_team(name):
        return {
            "_id": name.strip().lower(),
            "name": name.strip(),
            "category_id": None,
            "permissions": {},
            "pings": [],
            "response": None,
            "note": None,
        }

    def team_embed(self, team):
        embed = discord.Embed(
            title=f"Team: {team['name']}", color=self.bot.main_color
        )

        category = (
            self.bot.modmail_guild.get_channel(team["category_id"])
            if team["category_id"]
            else None
        )
        embed.add_field(
            name="Category",
            value=category.mention if category else "Not set",
            inline=False,
        )

        if team["permissions"]:
            lines = []
            for role_id, perms in team["permissions"].items():
                role = self.bot.modmail_guild.get_role(int(role_id))
                role_name = role.mention if role else f"`{role_id}`"
                perms_str = ", ".join(
                    f"{'+' if v else '-'}{p}" for p, v in perms.items()
                )
                lines.append(f"{role_name}: {perms_str}")
            embed.add_field(name="Permissions", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Permissions", value="None set", inline=False)

        if team["pings"]:
            mentions = []
            for ping in team["pings"]:
                if ping["type"] == "role":
                    role = self.bot.modmail_guild.get_role(ping["id"])
                    mentions.append(role.mention if role else f"`{ping['id']}`")
                else:
                    mentions.append(f"<@{ping['id']}>")
            embed.add_field(name="Pings", value=" ".join(mentions), inline=False)
        else:
            embed.add_field(name="Pings", value="None set", inline=False)

        embed.add_field(
            name="User Response", value=team["response"] or "Not set", inline=False
        )
        embed.add_field(
            name="Staff Note", value=team["note"] or "Not set", inline=False
        )

        return embed

    # ----- team management ----------------------------------------------

    @commands.group(invoke_without_command=True, aliases=["teams"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team(self, ctx):
        """Manage move teams."""
        await ctx.send_help(ctx.command)

    @team.command(name="create", aliases=["add"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_create(self, ctx, *, name: str):
        """Create a new team."""
        if self.find_team(name):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"A team named `{name}` already exists.",
            ))

        team = self.new_team(name)
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Created team `{team['name']}`.",
        ))

    @team.command(name="delete", aliases=["remove", "del"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_delete(self, ctx, *, name: str):
        """Delete a team."""
        team = self.find_team(name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{name}` exists.",
            ))

        await self.coll.delete_one({"_id": team["_id"]})
        del self.teams[team["_id"]]
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Deleted team `{team['name']}`.",
        ))

    @team.command(name="list")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_list(self, ctx):
        """List all teams."""
        if not self.teams:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="There are no teams set up yet.",
            ))

        embed = discord.Embed(
            title="Teams",
            description="\n".join(f"- {t['name']}" for t in self.teams.values()),
            color=self.bot.main_color,
        )
        await ctx.send(embed=embed)

    @team.command(name="info")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_info(self, ctx, *, name: str):
        """Show the configuration for a team."""
        team = self.find_team(name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{name}` exists.",
            ))

        await ctx.send(embed=self.team_embed(team))

    @team.command(name="category")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_category(
        self, ctx, team_name: str, *, category: discord.CategoryChannel
    ):
        """Set the category a team moves threads into.

        Quote `team_name` if it contains spaces, e.g. `"senior mod team"`.
        """
        team = self.find_team(team_name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{team_name}` exists.",
            ))

        team["category_id"] = category.id
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Team `{team['name']}` will now move threads to {category.mention}.",
        ))

    @team.command(name="permission", aliases=["perm", "permissions", "perms"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_permission(
        self,
        ctx,
        team_name: str,
        role: discord.Role,
        action: str,
        *perms: str,
    ):
        """Set channel permission overwrites for a role for this team.

        `action` must be `allow`, `deny`, or `reset`.
        Quote `team_name` if it contains spaces, e.g. `"senior mod team"`.
        Example: `{prefix}team permission uefn @UEFN-Team allow view_channel send_messages`
        """
        team = self.find_team(team_name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{team_name}` exists.",
            ))

        action = action.lower()
        if action not in ("allow", "deny", "reset"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="`action` must be `allow`, `deny`, or `reset`.",
            ))

        role_key = str(role.id)

        if action == "reset":
            team["permissions"].pop(role_key, None)
            await self.save_team(team)
            return await ctx.send(embed=discord.Embed(
                color=self.bot.main_color,
                description=f"Reset permissions for {role.mention} on team `{team['name']}`.",
            ))

        if not perms:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="Provide at least one permission name.",
            ))

        invalid = [p for p in perms if p not in discord.Permissions.VALID_FLAGS]
        if invalid:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Invalid permission(s): {', '.join(invalid)}",
            ))

        value = action == "allow"
        role_perms = team["permissions"].setdefault(role_key, {})
        for perm in perms:
            role_perms[perm] = value

        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"{'Allowed' if value else 'Denied'} "
                f"{', '.join(perms)} for {role.mention} on team `{team['name']}`."
            ),
        ))

    @team.command(name="mentions", aliases=["mention", "ping"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_mentions(
        self,
        ctx,
        team_name: str,
        action: str,
        *,
        target: Union[discord.Role, discord.Member, discord.User],
    ):
        """Add or remove a role/user to mention when a thread is moved to this team.

        `action` must be `add` or `remove`.
        Quote `team_name` if it contains spaces, e.g. `"senior mod team"`.
        """
        team = self.find_team(team_name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{team_name}` exists.",
            ))

        action = action.lower()
        if action not in ("add", "remove"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="`action` must be `add` or `remove`.",
            ))

        mention_type = "role" if isinstance(target, discord.Role) else "user"
        entry = {"type": mention_type, "id": target.id}

        if action == "add":
            if entry not in team["pings"]:
                team["pings"].append(entry)
        else:
            team["pings"] = [
                p for p in team["pings"] if not (p["type"] == mention_type and p["id"] == target.id)
            ]

        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"{'Added' if action == 'add' else 'Removed'} {target.mention} "
            f"{'to' if action == 'add' else 'from'} the mentions list for team `{team['name']}`.",
        ))

    @team.command(name="response")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_response(self, ctx, team_name: str, *, message: str = None):
        """Set the message sent to the user when a thread is moved to this team.

        Quote `team_name` if it contains spaces, e.g. `"senior mod team"`.
        Leave `message` empty to clear it.
        """
        team = self.find_team(team_name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{team_name}` exists.",
            ))

        team["response"] = message
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the user response for team `{team['name']}`.",
        ))

    @team.command(name="note")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_note(self, ctx, team_name: str, *, message: str = None):
        """Set the staff-only note sent in the thread channel when moved to this team.

        Quote `team_name` if it contains spaces, e.g. `"senior mod team"`.
        Leave `message` empty to clear it.
        """
        team = self.find_team(team_name)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No team named `{team_name}` exists.",
            ))

        team["note"] = message
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the staff note for team `{team['name']}`.",
        ))

    # ----- move override -------------------------------------------------

    @commands.command(usage="<team name>")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    async def move(self, ctx, *, name: str):
        """Move a thread to a configured team.

        `name` may be any team name set up with `{prefix}team create`, e.g.
        `{prefix}move uefn`, `{prefix}move admin team`, `{prefix}move senior mod team`.
        """
        team = self.find_team(name)
        if not team:
            available = ", ".join(f"`{t['name']}`" for t in self.teams.values())
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=(
                    f"No team named `{name}` exists.\n"
                    f"Available teams: {available or 'None'}"
                ),
            ))

        category = (
            ctx.guild.get_channel(team["category_id"]) if team["category_id"] else None
        )
        if not isinstance(category, discord.CategoryChannel):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=(
                    f"Team `{team['name']}` does not have a valid category set. "
                    f"Use `{ctx.prefix}team category` to configure it."
                ),
            ))

        thread = ctx.thread

        await thread.channel.edit(
            category=category,
            reason=f"{ctx.author} moved this thread to team {team['name']}.",
        )

        for role_id, perms in team["permissions"].items():
            role = ctx.guild.get_role(int(role_id))
            if role is None:
                continue
            overwrite = discord.PermissionOverwrite(**perms)
            await thread.channel.set_permissions(
                role, overwrite=overwrite, reason="Team move permissions."
            )

        if team["pings"]:
            mentions = []
            for ping in team["pings"]:
                if ping["type"] == "role":
                    role = ctx.guild.get_role(ping["id"])
                    if role:
                        mentions.append(role.mention)
                else:
                    mentions.append(f"<@{ping['id']}>")
            if mentions:
                await ctx.channel.send(
                    " ".join(mentions),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True),
                )

        await ctx.channel.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Thread moved to team **{team['name']}**.",
        ))

        if team["note"]:
            await ctx.channel.send(embed=discord.Embed(
                title="Staff Note",
                description=team["note"],
                color=self.bot.mod_color,
            ))

        if team["response"]:
            await thread.recipient.send(embed=discord.Embed(
                title=self.bot.config["thread_move_title"],
                description=team["response"],
                color=self.bot.main_color,
            ))

        sent_emoji, _ = await self.bot.retrieve_emoji()
        await self.bot.add_reaction(ctx.message, sent_emoji)


async def setup(bot):
    # Remove the built-in move command first so our cog's own "move" command
    # (added automatically when the cog is injected) doesn't collide with it.
    old_move = bot.remove_command("move")
    await bot.add_cog(Teams(bot, old_move))
