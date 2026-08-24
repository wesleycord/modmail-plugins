import re

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


class Raw(commands.Cog):
    """Get raw information from Modmail messages."""

    def __init__(self, bot):
        self.bot = bot

    async def _get_thread(self, ctx):
        return await self.bot.api.get_log(ctx.channel.id)

    async def _get_message(self, ctx, message_id=None):
        if message_id is None:
            if ctx.message.reference is None:
                return None

            message_id = ctx.message.reference.message_id

        try:
            return await ctx.channel.fetch_message(message_id)
        except discord.HTTPException:
            return None

    @commands.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def raw(self, ctx, message_id: int = None):
        """Get the raw embed description."""
        if ctx.invoked_subcommand is not None:
            return

        await self._raw_message(ctx, message_id)

    async def _raw_message(self, ctx, message_id=None):
        thread = await self._get_thread(ctx)

        if not thread:
            return await ctx.send(
                "This command can only be used in a modmail thread"
            )

        msg = await self._get_message(ctx, message_id)

        if msg is None:
            return await ctx.send(
                "Please reply to a message or provide a valid message ID"
            )

        if not msg.embeds:
            return await ctx.send("That message has no embeds")

        description = msg.embeds[0].description

        if not description:
            return await ctx.send("That embed has no description")

        await ctx.send(f"`{description}`")

    @raw.command(name="message")
    async def raw_message(self, ctx, message_id: int = None):
        """Get the raw embed description."""

        await self._raw_message(ctx, message_id)

    @raw.command(name="ids")
    async def raw_ids(self, ctx, message_id: int = None):
        """Get all Discord IDs from an embed description."""

        thread = await self._get_thread(ctx)

        if not thread:
            return await ctx.send(
                "This command can only be used in a modmail thread"
            )

        msg = await self._get_message(ctx, message_id)

        if msg is None:
            return await ctx.send(
                "Please reply to a message or provide a valid message ID"
            )

        if not msg.embeds:
            return await ctx.send("That message has no embeds")

        description = msg.embeds[0].description

        if not description:
            return await ctx.send("That embed has no description")

        ids = re.findall(r"\b\d{17,20}\b", description)
        ids = list(dict.fromkeys(ids))

        if not ids:
            return await ctx.send("No Discord IDs found")

        result = "\n".join(f"- `{id}`" for id in ids)

        await ctx.send(result)


async def setup(bot):
    await bot.add_cog(Raw(bot))