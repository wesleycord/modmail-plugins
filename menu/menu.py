import copy

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class ThreadMenu(commands.Cog):
    """Manage Modmail's built-in DM thread-creation menu configuration.

    This cog provides administrator commands for the
    `thread_creation_menu_*` configuration values used by Modmail core. It
    supports only flat options, and can run a configured command or apply a
    Teams plugin team after a thread created from a menu selection is ready.

    The menu presentation and thread creation remain the responsibility of
    Modmail core; this cog only manages its configuration and post-creation
    option actions.
    """

    def __init__(self, bot):
        self.bot = bot
        if not hasattr(bot, '_menu_before_invoke_added'):
            bot.before_invoke = self._fix_guild_before_invoke
            bot._menu_before_invoke_added = True

    async def _fix_guild_before_invoke(self, ctx):
        """Fix guild=None in contexts before command invocation."""
        if ctx.guild is None:
            ctx.guild = self.bot.modmail_guild
            if ctx.message:
                ctx.message.guild = self.bot.modmail_guild

    # ----- helpers -----------------------------------------------------

    @staticmethod
    def slugify(label):
        return label.strip().lower().replace(" ", "_")

    def get_options(self):
        options = self.bot.config.get("thread_creation_menu_options")
        return options if isinstance(options, dict) else {}

    async def save_options(self, options):
        self.bot.config["thread_creation_menu_options"] = options
        await self.bot.config.update()

    def find_option(self, options, key_or_label):
        key = self.slugify(key_or_label)
        if key in options:
            return key
        for opt_key, opt in options.items():
            if opt.get("label", "").strip().lower() == key_or_label.strip().lower():
                return opt_key
        return None

    def match_option(self, options, text):
        """Find an option at the start of `text`, trying the longest word match first.

        Returns a `(key, rest)` tuple, where `rest` is whatever followed the
        matched option. This allows multi-word labels to be used without
        quoting them, the same way Teams matches team names.
        """
        words = text.split()
        for i in range(len(words), 0, -1):
            key = self.find_option(options, " ".join(words[:i]))
            if key:
                return key, " ".join(words[i:])
        return None, text

    def option_embed(self, key, option):
        embed = discord.Embed(
            title=f"Menu Option: {option['label']}", color=self.bot.main_color
        )
        embed.add_field(name="Key", value=f"`{key}`", inline=False)
        embed.add_field(
            name="Description", value=option.get("description") or "Not set", inline=False
        )
        embed.add_field(name="Emoji", value=option.get("emoji") or "Not set", inline=False)

        category = (
            self.bot.modmail_guild.get_channel(option["category_id"])
            if option.get("category_id")
            else None
        )
        embed.add_field(
            name="Category", value=category.mention if category else "Default", inline=False
        )

        if option.get("type") == "command":
            embed.add_field(name="Runs Command", value=f"`{option.get('callback')}`", inline=False)

        if option.get("team"):
            embed.add_field(name="Linked Team", value=f"`{option['team']}`", inline=False)

        return embed

    # ----- top-level menu settings ---------------------------------------

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu(self, ctx):
        """Manage the DM thread-creation menu."""
        await ctx.send_help(ctx.command)

    @menu.command(name="status")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_status(self, ctx):
        """Show the current thread-creation menu configuration."""
        enabled = bool(self.bot.config.get("thread_creation_menu_enabled"))
        options = self.get_options()

        embed = discord.Embed(
            title="Thread Creation Menu",
            color=self.bot.main_color if enabled else self.bot.error_color,
        )
        embed.add_field(name="Enabled", value="Yes" if enabled else "No", inline=False)
        embed.add_field(
            name="Title",
            value=self.bot.config.get("thread_creation_menu_embed_title") or "Not set",
            inline=False,
        )
        embed.add_field(
            name="Text",
            value=self.bot.config.get("thread_creation_menu_embed_text") or "Not set",
            inline=False,
        )
        embed.add_field(
            name="Placeholder",
            value=self.bot.config.get("thread_creation_menu_dropdown_placeholder") or "Not set",
            inline=False,
        )
        embed.add_field(
            name="Timeout",
            value=str(self.bot.config.get("thread_creation_menu_timeout") or "Not set"),
            inline=False,
        )
        embed.add_field(
            name="Options",
            value="\n".join(f"- `{k}`: {o['label']}" for k, o in options.items()) or "None set",
            inline=False,
        )
        await ctx.send(embed=embed)

    @menu.command(name="enable")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_enable(self, ctx):
        """Enable the DM thread-creation menu."""
        if not self.get_options():
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Add at least one option with `{ctx.prefix}menu option add` before enabling.",
            ))

        self.bot.config["thread_creation_menu_enabled"] = True
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="The thread-creation menu is now enabled.",
        ))

    @menu.command(name="disable")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_disable(self, ctx):
        """Disable the DM thread-creation menu."""
        self.bot.config["thread_creation_menu_enabled"] = False
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="The thread-creation menu is now disabled.",
        ))

    @menu.command(name="title")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_title(self, ctx, *, text: str = None):
        """Set the menu embed's title. Leave empty to clear it."""
        self.bot.config["thread_creation_menu_embed_title"] = text
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu title.",
        ))

    @menu.command(name="text")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_text(self, ctx, *, text: str):
        """Set the menu embed's description text."""
        self.bot.config["thread_creation_menu_embed_text"] = text
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu text.",
        ))

    @menu.command(name="placeholder")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_placeholder(self, ctx, *, text: str):
        """Set the dropdown's placeholder text."""
        self.bot.config["thread_creation_menu_dropdown_placeholder"] = text
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the dropdown placeholder.",
        ))

    @menu.command(name="footer")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_footer(self, ctx, *, text: str = None):
        """Set the menu embed's footer. Leave empty to clear it."""
        self.bot.config["thread_creation_menu_embed_footer"] = text
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu footer.",
        ))

    @menu.command(name="color", aliases=["colour"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_color(self, ctx, color: discord.Color = None):
        """Set the menu embed's color. Leave empty to use the bot's default color."""
        self.bot.config["thread_creation_menu_embed_color"] = color.value if color else None
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu color.",
        ))

    @menu.command(name="thumbnail")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_thumbnail(self, ctx, url: str = None):
        """Set the menu embed's thumbnail image URL. Leave empty to clear it."""
        self.bot.config["thread_creation_menu_embed_thumbnail_url"] = url
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu thumbnail.",
        ))

    @menu.command(name="image")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_image(self, ctx, url: str = None):
        """Set the menu embed's large image URL. Leave empty to clear it."""
        self.bot.config["thread_creation_menu_embed_image_url"] = url
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description="Updated the menu image.",
        ))

    @menu.command(name="timeout")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_timeout(self, ctx, seconds: int):
        """Set how long (in seconds) the menu waits for a selection before timing out."""
        if seconds <= 0:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description="Provide a positive number of seconds.",
            ))

        self.bot.config["thread_creation_menu_timeout"] = seconds
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description=f"Menu timeout set to {seconds} seconds.",
        ))

    @menu.command(name="precreate")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_precreate(self, ctx, value: str):
        """Toggle whether the thread channel is created before the user picks an option.

        `value` must be `on` or `off`.
        """
        value = value.lower()
        if value not in ("on", "off"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description="Provide `on` or `off`.",
            ))

        self.bot.config["thread_creation_menu_precreate_channel"] = value == "on"
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Precreating the channel before selection is now "
            f"{'enabled' if value == 'on' else 'disabled'}.",
        ))

    @menu.command(name="log")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_log(self, ctx, value: str):
        """Toggle logging the selected menu option in the thread channel.

        `value` must be `on` or `off`.
        """
        value = value.lower()
        if value not in ("on", "off"):
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description="Provide `on` or `off`.",
            ))

        self.bot.config["thread_creation_menu_selection_log"] = value == "on"
        await self.bot.config.update()
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Logging menu selections is now {'enabled' if value == 'on' else 'disabled'}.",
        ))

    # ----- option management ----------------------------------------------

    @menu.group(name="option", aliases=["options"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option(self, ctx):
        """Manage individual menu options."""
        await ctx.send_help(ctx.command)

    @menu_option.command(name="add")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_add(self, ctx, *, arguments: str):
        """Add a menu option.

        Format: `{prefix}menu option add <label> | <description> | [emoji]`
        """
        parts = [p.strip() for p in arguments.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="Provide a label and description, separated by `|`.",
            ))

        label, description = parts[0], parts[1]
        emoji = parts[2] if len(parts) > 2 and parts[2] else None

        options = self.get_options()
        key = self.slugify(label)
        if key in options:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"An option with the label `{label}` already exists.",
            ))

        options[key] = {
            "label": label,
            "description": description,
            "emoji": emoji,
            "category_id": None,
            "type": "message",
            "callback": None,
            "team": None,
        }
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description=f"Added menu option `{label}`.",
        ))

    @menu_option.command(name="remove", aliases=["delete", "del"])
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_remove(self, ctx, *, key_or_label: str):
        """Remove a menu option."""
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
            ))

        label = options.pop(key)["label"]
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color, description=f"Removed menu option `{label}`.",
        ))

    @menu_option.command(name="list")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_list(self, ctx):
        """List all menu options."""
        options = self.get_options()
        if not options:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color, description="No menu options have been set up yet.",
            ))

        embed = discord.Embed(
            title="Menu Options",
            description="\n".join(f"- `{k}`: {o['label']}" for k, o in options.items()),
            color=self.bot.main_color,
        )
        await ctx.send(embed=embed)

    @menu_option.command(name="info")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_info(self, ctx, *, key_or_label: str):
        """Show the configuration for a menu option."""
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
            ))

        await ctx.send(embed=self.option_embed(key, options[key]))

    @menu_option.command(name="emoji")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_emoji(self, ctx, *, arguments: str):
        """Set (or clear) a menu option's emoji.

        Example: `{prefix}menu option emoji Billing Issue 💳`
        Leave the emoji out to clear it. Labels with spaces work without quoting.
        """
        options = self.get_options()
        key, emoji = self.match_option(options, arguments)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching menu option found in that command.",
            ))

        options[key]["emoji"] = emoji or None
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the emoji for `{options[key]['label']}`.",
        ))

    @menu_option.command(name="category")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_category(self, ctx, *, arguments: str):
        """Set (or clear) the category a menu option moves new threads into.

        Example: `{prefix}menu option category Billing Issue #billing`
        Leave the category out to clear it and fall back to the default
        category. Labels with spaces work without quoting.
        """
        options = self.get_options()
        key, rest = self.match_option(options, arguments)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching menu option found in that command.",
            ))

        category = None
        if rest:
            try:
                category = await commands.CategoryChannelConverter().convert(ctx, rest)
            except commands.BadArgument:
                return await ctx.send(embed=discord.Embed(
                    color=self.bot.error_color,
                    description=f"Could not find a category matching `{rest}`.",
                ))

        options[key]["category_id"] = category.id if category else None
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"`{options[key]['label']}` will now move new threads to {category.mention}."
                if category
                else f"`{options[key]['label']}` will now use the default category."
            ),
        ))

    @menu_option.command(name="command")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_command(self, ctx, *, arguments: str):
        """Set (or clear) a command to run instead of relaying the user's message.

        Example: `{prefix}menu option command Billing Issue move Billing Team`
        Leave the command out to make this option relay the message normally.
        Labels with spaces work without quoting. `alias` is resolved through
        discord.py's normal command pipeline, so it works with any registered
        command, including plugin overrides.
        """
        options = self.get_options()
        key, alias = self.match_option(options, arguments)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching menu option found in that command.",
            ))

        if alias:
            options[key]["type"] = "command"
            options[key]["callback"] = alias
        else:
            options[key]["type"] = "message"
            options[key]["callback"] = None

        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"`{options[key]['label']}` now runs `{alias}`." if alias
                else f"`{options[key]['label']}` now relays the message normally."
            ),
        ))

    @menu_option.command(name="team")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_team(self, ctx, *, arguments: str):
        """Link a menu option directly to a Teams plugin team.

        Example: `{prefix}menu option team Billing Issue Billing Team`
        Leave the team out to unlink it. This applies the team's category,
        permissions, mentions, and note as soon as the thread is ready.
        Labels with spaces work without quoting.
        """
        options = self.get_options()
        key, team_name = self.match_option(options, arguments)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="No matching menu option found in that command.",
            ))

        if team_name:
            teams_cog = self.bot.get_cog("Teams")
            if teams_cog is None or not teams_cog.find_team(team_name):
                return await ctx.send(embed=discord.Embed(
                    color=self.bot.error_color,
                    description=f"No team matching `{team_name}` exists.",
                ))

        options[key]["team"] = team_name or None
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=(
                f"`{options[key]['label']}` now applies team `{team_name}` on creation."
                if team_name
                else f"`{options[key]['label']}` is no longer linked to a team."
            ),
        ))

    # ----- reliable command invocation -----------------------------------

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, creator, category, initial_message):
        """Run a menu option's linked command ourselves, bypassing core's
        manual Context construction, which can fail to resolve overridden
        commands. We use `"command"` (not `"command"`) as the stored
        type so core's own built-in invocation never fires for these too.
        """
        option = getattr(thread, "_selected_thread_creation_menu_option", None)
        if not isinstance(option, dict):
            return

        if option.get("type") != "command":
            return

        alias = option.get("callback")
        if not isinstance(alias, str) or not alias.strip():
            await thread.channel.send(embed=discord.Embed(
                color=self.bot.error_color,
                description="This menu option has no valid command configured.",
            ))
            return

        await self.run_menu_command(thread, alias, initial_message)

    def resolve_command(self, alias):
        """Find the deepest (sub)command matching the start of `alias`.

        Tries the longest qualified name first, e.g. for `"team permission ..."`
        this matches the `permission` subcommand of the `team` group rather
        than just `team`. Returns a `(command, remaining_args)` tuple.
        """
        words = alias.split()
        for i in range(len(words), 0, -1):
            command_name = " ".join(words[:i])
            command = self.bot.get_command(command_name)
            if command is not None:
                remaining = " ".join(words[i:])
                return command, remaining
        return None, alias

    async def run_menu_command(self, thread, alias, source_message):
        if source_message is None:
            await thread.channel.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Menu command `{alias}` could not run because the initial message is unavailable.",
            ))
            return

        command, remaining = self.resolve_command(alias)
        if command is None:
            await thread.channel.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Menu command `{alias}` doesn't match any registered command.",
            ))
            return

        from discord.ext.commands.view import StringView

        from core.models import DummyMessage

        try:
            synthetic = DummyMessage(copy.copy(source_message))
            synthetic.author = self.bot.modmail_guild.me or self.bot.user
            synthetic.channel = thread.channel
            synthetic.guild = self.bot.modmail_guild
            synthetic.content = alias

            ctx = commands.Context(
                bot=self.bot,
                view=StringView(remaining),
                prefix=self.bot.prefix,
                message=synthetic,
            )
            ctx.command = command
            ctx.invoked_with = command.qualified_name
            ctx.thread = thread
            ctx.guild = self.bot.modmail_guild

            await command.invoke(ctx)
        except Exception as exc:
            error_msg = str(exc) if str(exc) else type(exc).__name__
            await thread.channel.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"Menu command `{alias}` failed: {error_msg}",
            ))



async def setup(bot):
    await bot.add_cog(ThreadMenu(bot))
