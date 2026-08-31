from typing import Union

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Teams(commands.Cog):
    """Move threads to configurable teams instead of raw categories."""

    def __init__(self, bot, old_move=None, old_contact=None):
        self.bot = bot
        self.coll = bot.plugin_db.get_partition(self)
        self.teams = {}
        self._old_move = old_move
        self._old_contact = old_contact

    async def cog_load(self):
        async for doc in self.coll.find():
            doc.setdefault("sync_permissions", True)
            self.teams[doc["_id"]] = doc

    def cog_unload(self):
        self.bot.remove_command("move")
        if self._old_move is not None:
            self.bot.add_command(self._old_move)

        self.bot.remove_command("contact")
        if self._old_contact is not None:
            self.bot.add_command(self._old_contact)

    # ----- helpers -----------------------------------------------------

    def find_team_exact(self, name):
        return self.teams.get(name.strip().lower())

    def find_team(self, name):
        """Find a team by exact name, or by a unique name prefix."""
        candidate = name.strip().lower()
        if not candidate:
            return None

        team = self.teams.get(candidate)
        if team:
            return team

        matches = [t for key, t in self.teams.items() if key.startswith(candidate)]
        if len(matches) == 1:
            return matches[0]
        return None

    def match_team(self, text):
        """Find a team at the start of `text`, trying the longest word match first.

        Returns a `(team, rest)` tuple, where `rest` is whatever followed the
        matched team name. Team names may be given in full, or as a prefix
        that uniquely identifies one team, and multi-word names don't need
        to be quoted.
        """
        words = text.split()
        for i in range(len(words), 0, -1):
            team = self.find_team(" ".join(words[:i]))
            if team:
                return team, " ".join(words[i:])
        return None, text

    @staticmethod
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

    @staticmethod
    def permission_key(target):
        kind = "role" if isinstance(target, discord.Role) else "user"
        return f"{kind}:{target.id}"

    @staticmethod
    def resolve_permission_target(guild, key):
        kind, sep, id_str = key.partition(":")
        if not sep:
            # legacy data stored plain role IDs
            kind, id_str = "role", key
        try:
            target_id = int(id_str)
        except ValueError:
            return None
        if kind == "role":
            return guild.get_role(target_id)
        return guild.get_member(target_id) or discord.Object(id=target_id)

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
            "sync_permissions": True,
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
            for key, perms in team["permissions"].items():
                kind, sep, id_str = key.partition(":")
                if not sep:
                    kind, id_str = "role", key
                if kind == "role":
                    role = self.bot.modmail_guild.get_role(int(id_str))
                    label = role.mention if role else f"`{id_str}`"
                else:
                    member = self.bot.modmail_guild.get_member(int(id_str))
                    label = member.mention if member else f"<@{id_str}>"
                perms_str = ", ".join(
                    f"{'+' if v else '-'}{p}" for p, v in perms.items()
                )
                lines.append(f"{label}: {perms_str}")
            embed.add_field(name="Permissions", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Permissions", value="None set", inline=False)

        embed.add_field(
            name="Sync With Category",
            value="Enabled" if team.get("sync_permissions", True) else "Disabled",
            inline=False,
        )

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
        if self.find_team_exact(name):
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
    async def team_category(self, ctx, *, arguments: str):
        """Set the category a team moves threads into.

        Leave the category out to use the channel's current category.
        Example: `{prefix}team category Admin Team #admin-category`
        """
        team, rest = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        if not rest:
            category = ctx.channel.category
            if category is None:
                return await ctx.send(embed=discord.Embed(
                    color=self.bot.error_color,
                    description="This channel has no category. Provide one explicitly.",
                ))
        else:
            try:
                category = await commands.CategoryChannelConverter().convert(ctx, rest)
            except commands.BadArgument:
                return await ctx.send(embed=discord.Embed(
                    color=self.bot.error_color,
                    description=f"Could not find a category matching `{rest}`.",
                ))

        team["category_id"] = category.id
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Team `{team['name']}` will now move threads to {category.mention}.",
        ))

    @team.command(name="permission", aliases=["perm", "permissions", "perms"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_permission(self, ctx, *, arguments: str):
        """Set channel permission overwrites for a role or user for this team.

        Example: `{prefix}team permission Admin Team @Admins allow view_channel send_messages`
        You may target a specific user instead of a role the same way.
        """
        team, rest = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        parts = rest.split()
        if len(parts) < 2:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="Provide a role/user and an action (`allow`, `deny`, or `reset`).",
            ))

        target_text, action, *perms = parts
        target = await self.convert_role_member_user(ctx, target_text)
        if target is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Could not find a role or user matching `{target_text}`.",
            ))

        action = action.lower()
        if action not in ("allow", "deny", "reset"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="`action` must be `allow`, `deny`, or `reset`.",
            ))

        target_key = self.permission_key(target)

        if action == "reset":
            team["permissions"].pop(target_key, None)
            await self.save_team(team)
            return await ctx.send(embed=discord.Embed(
                color=self.bot.main_color,
                description=f"Reset permissions for {target.mention} on team `{team['name']}`.",
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
        target_perms = team["permissions"].setdefault(target_key, {})
        for perm in perms:
            target_perms[perm] = value

        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"{'Allowed' if value else 'Denied'} "
                f"{', '.join(perms)} for {target.mention} on team `{team['name']}`."
            ),
        ))

    @team.command(name="sync")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_sync(self, ctx, *, arguments: str):
        """Toggle syncing the channel's permissions with the destination category on move.

        Enabled by default, so the category's base permissions always apply
        unless turned off. Example: `{prefix}team sync Admin Team off`
        """
        team, rest = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        value = rest.strip().lower()
        if value not in ("on", "off"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="Provide `on` or `off`.",
            ))

        team["sync_permissions"] = value == "on"
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"Category permission syncing is now "
                f"{'enabled' if team['sync_permissions'] else 'disabled'} for team `{team['name']}`."
            ),
        ))

    @team.command(name="mentions", aliases=["mention", "ping"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_mentions(self, ctx, *, arguments: str):
        """Add or remove one or more roles/users to mention when a thread is moved to this team.

        Example: `{prefix}team mentions Admin Team add @Admins @Kewi 123456789012345678`
        """
        team, rest = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        parts = rest.split()
        if len(parts) < 2:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="Provide an action (`add` or `remove`) and at least one role or user.",
            ))

        action, *target_texts = parts
        action = action.lower()
        if action not in ("add", "remove"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="`action` must be `add` or `remove`.",
            ))

        targets = []
        not_found = []
        for text in target_texts:
            target = await self.convert_role_member_user(ctx, text)
            if target is None:
                not_found.append(text)
            else:
                targets.append(target)

        if not targets:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Could not find a role or user matching: {', '.join(not_found)}",
            ))

        for target in targets:
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

        description = (
            f"{'Added' if action == 'add' else 'Removed'} "
            f"{', '.join(t.mention for t in targets)} "
            f"{'to' if action == 'add' else 'from'} the mentions list for team `{team['name']}`."
        )
        if not_found:
            description += f"\nCould not find: {', '.join(not_found)}"

        await ctx.send(embed=discord.Embed(color=self.bot.main_color, description=description))

    @team.command(name="response")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_response(self, ctx, *, arguments: str):
        """Set the message sent to the user when a thread is moved to this team.

        Leave the message empty to clear it.
        Example: `{prefix}team response Admin Team You have been moved to the admin team.`
        """
        team, message = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        team["response"] = message or None
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the user response for team `{team['name']}`.",
        ))

    @team.command(name="note")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def team_note(self, ctx, *, arguments: str):
        """Set the staff-only note sent in the thread channel when moved to this team.

        Leave the message empty to clear it.
        Example: `{prefix}team note Admin Team Escalate to an admin ASAP.`
        """
        team, message = self.match_team(arguments)
        if not team:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching team found in that command.",
            ))

        team["note"] = message or None
        await self.save_team(team)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the staff note for team `{team['name']}`.",
        ))

    # ----- move override -------------------------------------------------

    async def apply_team(self, thread, team, *, guild, reason):
        """Move `thread`'s channel into `team`'s category and apply its settings.

        Returns an error message string on failure, or `None` on success.
        Shared by the `move` command, `contact`, and the thread-creation menu
        hook, so all three stay in sync with each other.
        """
        category = guild.get_channel(team["category_id"]) if team["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            return (
                f"Team `{team['name']}` does not have a valid category set. "
                f"Use `{self.bot.prefix}team category` to configure it."
            )

        await thread.channel.edit(
            category=category,
            sync_permissions=team.get("sync_permissions", True),
            reason=reason,
        )

        for key, perms in team["permissions"].items():
            target = self.resolve_permission_target(guild, key)
            if target is None:
                continue
            overwrite = discord.PermissionOverwrite(**perms)
            await thread.channel.set_permissions(
                target, overwrite=overwrite, reason="Team permissions."
            )

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
                color=self.bot.mod_color,
            ))

        if team["response"]:
            await thread.recipient.send(embed=discord.Embed(
                title=self.bot.config["thread_move_title"],
                description=team["response"],
                color=self.bot.main_color,
            ))

        return None

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, creator, category, initial_message):
        """Apply a team linked to a thread-creation menu option (set via the
        `menu` plugin's `menu option team` command), bypassing core's fragile
        alias-based command invocation for menu options entirely.
        """
        option = getattr(thread, "_selected_thread_creation_menu_option", None)
        if not isinstance(option, dict):
            return

        team_name = option.get("team")
        if not team_name:
            return

        team = self.find_team(team_name)
        if not team:
            return

        await self.apply_team(
            thread,
            team,
            guild=self.bot.modmail_guild,
            reason=f"Menu option {option.get('label')} selected.",
        )

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

        error = await self.apply_team(
            ctx.thread,
            team,
            guild=ctx.guild,
            reason=f"{ctx.author} moved this thread to team {team['name']}.",
        )
        if error:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description=error,
            ))

        await ctx.channel.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Thread moved to team **{team['name']}**.",
        ))

        sent_emoji, _ = await self.bot.retrieve_emoji()
        await self.bot.add_reaction(ctx.message, sent_emoji)

    # ----- contact override ----------------------------------------------

    @commands.command(usage="<user> [team]")
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def contact(
        self,
        ctx,
        user: Union[discord.Member, discord.User],
        *,
        team_name: str = None,
    ):
        """Create a thread with a specified member, optionally straight into a team.

        `team_name` may be any team name set up with `{prefix}team create`.
        Since this is staff-initiated, it always bypasses the thread-creation menu.
        """
        if user.bot:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"{user} is a bot, cannot add to thread.",
            ))

        if await self.bot.is_blocked(user):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"{user.mention} is currently blocked from contacting {self.bot.user.name}.",
            ))

        existing_thread = await self.bot.threads.find(recipient=user)
        if existing_thread:
            description = f"A thread for {user.mention} already exists"
            if existing_thread.channel:
                description += f" in {existing_thread.channel.mention}."
            else:
                description += "."
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description=description,
            ))

        team = None
        category = None
        if team_name:
            team = self.find_team(team_name)
            if not team:
                return await ctx.send(embed=discord.Embed(
                    color=self.bot.error_color,
                    description=f"No team matching `{team_name}` exists.",
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

        # creator != recipient, so ThreadManager.create's thread-creation-menu
        # path (which only triggers for user-initiated DMs) is bypassed here.
        thread = await self.bot.threads.create(
            recipient=user,
            creator=ctx.author,
            category=category,
            manual_trigger=True,
        )

        if thread.cancelled:
            return

        description = self.bot.formatter.format(
            self.bot.config["thread_creation_contact_response"], creator=ctx.author
        )
        em = discord.Embed(
            title=self.bot.config["thread_creation_contact_title"],
            description=description,
            color=self.bot.main_color,
        )
        if self.bot.config["show_timestamp"]:
            em.timestamp = discord.utils.utcnow()
        em.set_footer(
            text=f"{ctx.author}",
            icon_url=ctx.author.display_avatar.url if ctx.author.display_avatar else None,
        )
        await user.send(embed=em)

        await thread.wait_until_ready()

        if team is not None:
            for key, perms in team["permissions"].items():
                target = self.resolve_permission_target(ctx.guild, key)
                if target is None:
                    continue
                overwrite = discord.PermissionOverwrite(**perms)
                await thread.channel.set_permissions(
                    target, overwrite=overwrite, reason="Team contact permissions."
                )

            if team["note"]:
                await thread.channel.send(embed=discord.Embed(
                    title="Staff Note",
                    description=team["note"],
                    color=self.bot.mod_color,
                ))

        embed = discord.Embed(
            title="Created Thread",
            description=(
                f"Thread started by {ctx.author.mention} for {user.mention}."
                + (f" Assigned to team **{team['name']}**." if team else "")
            ),
            color=self.bot.main_color,
        )
        await thread.channel.send(embed=embed)

        sent_emoji, _ = await self.bot.retrieve_emoji()
        await self.bot.add_reaction(ctx.message, sent_emoji)
        try:
            await ctx.message.delete(delay=5)
        except (discord.Forbidden, discord.NotFound):
            pass


async def setup(bot):
    # Remove the built-in move/contact commands first so our cog's own versions
    # (added automatically when the cog is injected) don't collide with them.
    old_move = bot.remove_command("move")
    old_contact = bot.remove_command("contact")
    await bot.add_cog(Teams(bot, old_move, old_contact))
