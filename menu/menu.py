import copy

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class ThreadMenu(commands.Cog):
    """Friendly commands for managing Modmail's built-in DM thread-creation menu.

    This doesn't reimplement the menu itself - it manages the same
    `thread_creation_menu_*` config keys that Modmail's core already reads
    when a new thread is set up, just with commands instead of raw config
    editing. Submenus aren't supported here, only flat options.

    Core only ever shows this menu for user-initiated DMs (it's skipped
    whenever a staff member starts the thread, e.g. via the contact command),
    so this plugin doesn't need to touch contact at all.
    """

    def __init__(self, bot):
        self.bot = bot

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

        if option.get("type") == "run_command":
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
    async def menu_option_emoji(self, ctx, key_or_label: str, emoji: str = None):
        """Set (or clear) a menu option's emoji.

        Identify the option by its `key` (see `{prefix}menu option list`) to
        avoid needing to quote multi-word labels.
        """
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
            ))

        options[key]["emoji"] = emoji
        await self.save_options(options)
        await ctx.send(embed=discord.Embed(
            color=self.bot.main_color,
            description=f"Updated the emoji for `{options[key]['label']}`.",
        ))

    @menu_option.command(name="category")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def menu_option_category(
        self, ctx, key_or_label: str, *, category: discord.CategoryChannel = None
    ):
        """Set (or clear) the category a menu option moves new threads into.

        Identify the option by its `key` (see `{prefix}menu option list`) to
        avoid needing to quote multi-word labels. Leave `category` empty to
        clear it and fall back to the default category.
        """
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
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
    async def menu_option_command(self, ctx, key_or_label: str, *, alias: str = None):
        """Set (or clear) a command to run instead of relaying the user's message.

        Identify the option by its `key` (see `{prefix}menu option list`) to
        avoid needing to quote multi-word labels. Leave `alias` empty to make
        this option relay the message normally.

        `alias` is resolved through discord.py's normal command pipeline
        (not core's built-in menu, which can miss overridden commands), so
        it works with any registered command, including plugin overrides.
        """
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
            ))

        if alias:
            options[key]["type"] = "run_command"
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
    async def menu_option_team(self, ctx, key_or_label: str, *, team_name: str = None):
        """Link a menu option directly to a Teams plugin team. Leave `team_name` empty to unlink.

        Identify the option by its `key` (see `{prefix}menu option list`) to
        avoid needing to quote multi-word labels. This applies the team's
        category, permissions, mentions, and note as soon as the thread is
        ready. Equivalent to `{prefix}menu option command <key> move <team>`,
        just without needing to spell out the move command yourself.
        """
        options = self.get_options()
        key = self.find_option(options, key_or_label)
        if key is None:
            return await ctx.send(embed=discord.Embed(
                color=self.bot.error_color,
                description=f"No option matching `{key_or_label}` exists.",
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
        """Run a menu option's linked command through discord.py's normal
        command-resolution pipeline (`bot.get_context`) instead of core's
        manual Context construction, which can fail to resolve overridden
        commands. We use `"run_command"` (not `"command"`) as the stored
        type so core's own built-in invocation never fires for these too.
        """
        option = getattr(thread, "_selected_thread_creation_menu_option", None)
        if not isinstance(option, dict) or option.get("type") != "run_command":
            return

        alias = option.get("callback")
        if alias:
            await self.run_menu_command(thread, alias, initial_message)

    async def run_menu_command(self, thread, alias, source_message):
        if source_message is None:
            return

        from core.models import DummyMessage

        synthetic = DummyMessage(copy.copy(source_message))
        synthetic.author = self.bot.modmail_guild.me or self.bot.user
        synthetic.channel = thread.channel
        synthetic.guild = thread.channel.guild
        synthetic.content = self.bot.prefix + alias

        ctx = await self.bot.get_context(synthetic)
        if ctx.command is None:
            return

        ctx.thread = thread

        old_checks = list(ctx.command.checks)
        ctx.command.checks = []
        try:
            await self.bot.invoke(ctx)
        finally:
            ctx.command.checks = old_checks


async def setup(bot):
    await bot.add_cog(ThreadMenu(bot))
