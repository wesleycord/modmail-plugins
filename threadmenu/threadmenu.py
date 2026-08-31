import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class ThreadMenu(commands.Cog):
    """Ensures the thread-creation menu creates the channel immediately.

    Core already skips the menu for `.contact` (staff creating a thread for
    someone else) and still shows it for `.selfcontact`/organic DMs, since
    that decision is based on whether the creator is the recipient. The one
    thing core does not force on by default is precreating the channel
    before the user picks an option, which is what this plugin enables.
    """

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if not self.bot.config.get("thread_creation_menu_precreate_channel"):
            await self.bot.config.set("thread_creation_menu_precreate_channel", True)
            await self.bot.config.update()

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def threadmenuprecreate(self, ctx):
        """Check or toggle whether the thread channel is created before menu selection."""
        enabled = bool(self.bot.config.get("thread_creation_menu_precreate_channel"))
        await ctx.send(f"Precreate channel before menu selection is currently **{'on' if enabled else 'off'}**.")

    @threadmenuprecreate.command(name="toggle")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def threadmenuprecreate_toggle(self, ctx):
        """Toggle precreating the thread channel before menu selection."""
        enabled = not bool(self.bot.config.get("thread_creation_menu_precreate_channel"))
        await self.bot.config.set("thread_creation_menu_precreate_channel", enabled)
        await self.bot.config.update()
        await ctx.send(f"Precreate channel before menu selection is now **{'on' if enabled else 'off'}**.")


async def setup(bot):
    await bot.add_cog(ThreadMenu(bot))
