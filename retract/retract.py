import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel


RETRACTED = "[Retracted by {name} ({id})]"
DM_RETRACTED = "[RETRACTED]"


class Retract(commands.Cog):
    """Allows moderators to permanently retract messages."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def retract(self, ctx, message_id: int = None):
        """Permanently retract a message from a Modmail thread."""

        message = await self.get_message(ctx, message_id)

        if message is None:
            await ctx.send(
                "You must reply to a message or provide a message ID.",
                delete_after=5,
            )
            return

        log = await self.bot.api.get_log(ctx.channel.id)

        if not log:
            await ctx.send(
                "Could not find the log for this thread.",
                delete_after=5,
            )
            return

        log_message = self.get_log_message(log, message)

        if log_message is None:
            await ctx.send(
                "That message could not be found in the Modmail log.",
                delete_after=5,
            )
            return

        if log_message.get("retracted"):
            await ctx.send(
                "That message has already been retracted.",
                delete_after=5,
            )
            return

        await self.retract_log_entry(ctx, log, log_message, message)

        await ctx.message.delete()

    async def get_message(self, ctx, message_id):
        """Get the target Discord message."""

        if message_id:
            try:
                return await ctx.channel.fetch_message(message_id)
            except discord.NotFound:
                return None

        if not ctx.message.reference:
            return None

        if not ctx.message.reference.message_id:
            return None

        try:
            return await ctx.channel.fetch_message(
                ctx.message.reference.message_id
            )
        except discord.NotFound:
            return None

    @staticmethod
    def get_log_message(log, discord_message):
        """Find a message in the Modmail log."""

        message_ids = Retract.get_message_ids(discord_message)

        for message in log.get("messages", []):
            log_ids = {
                str(message.get(field))
                for field in (
                    "message_id",
                    "id",
                    "channel_message_id",
                    "thread_message_id",
                    "dm_message_id",
                )
                if message.get(field) is not None
            }
            if message_ids & log_ids:
                return message

        return None

    @staticmethod
    def get_message_ids(message):
        """Get Discord IDs linked to a relay message."""

        message_ids = {str(getattr(message, "id", message))}
        for embed in getattr(message, "embeds", []):
            author_url = getattr(getattr(embed, "author", None), "url", None)
            if author_url and "#" in author_url:
                message_ids.add(author_url.rsplit("#", 1)[1])

            footer_text = getattr(getattr(embed, "footer", None), "text", "")
            if footer_text.startswith("Message ID: "):
                message_ids.add(
                    footer_text[len("Message ID: ") :].split(" ", 1)[0]
                )

        return message_ids

    async def retract_log_entry(
        self,
        ctx,
        log,
        log_message,
        discord_message,
    ):
        """Retract any message represented by a log entry."""

        self.retract_log_message(
            log_message,
            ctx.author,
        )

        await self.bot.api.post_log(
            ctx.channel.id,
            log,
        )

        await self.edit_message(discord_message, log_message["content"])

        if log_message.get("author", {}).get("mod"):
            await self.edit_user_message(log, log_message, discord_message)

    @staticmethod
    def retract_log_message(log_message, moderator):
        """Replace all retained message content with the retraction."""

        log_message["content"] = RETRACTED.format(
            name=moderator.name,
            id=moderator.id,
        )

        # Do not retain attachments belonging to the retracted message.
        log_message["attachments"] = []

        # Remove other potentially retained message data.
        log_message.pop("embeds", None)

        # Mark it so it cannot accidentally be retracted twice.
        log_message["retracted"] = True
        log_message["retracted_by"] = {
            "name": moderator.name,
            "id": moderator.id,
        }

    async def edit_message(self, message, content):
        """Replace a message with a retraction embed."""

        color = None
        if message.embeds:
            color = message.embeds[0].colour
        if color is None:
            color = getattr(self.bot, "error_color", 0xED4245)
        embed = discord.Embed(
            description=content,
            color=color,
        )
        try:
            await message.edit(embed=embed, attachments=[], content=None)
        except discord.NotFound:
            pass

    async def edit_user_message(self, log, log_message, discord_message):
        """Replace the moderator copy in the recipient's DM."""

        recipient = log.get("recipient")
        if not isinstance(recipient, dict):
            return

        recipient_id = recipient.get("id")
        if not recipient_id:
            return

        dm_message_id = log_message.get("dm_message_id") or log_message.get(
            "message_id"
        )
        if not dm_message_id:
            dm_message_id = None

        linked_ids = self.get_message_ids(discord_message)

        user = self.bot.get_user(int(recipient_id))
        if user is None:
            user = await self.bot.fetch_user(int(recipient_id))

        dm = user.dm_channel or await user.create_dm()
        if dm_message_id:
            try:
                message = await dm.fetch_message(int(dm_message_id))
            except discord.NotFound:
                message = None
            else:
                await self.edit_message(message, DM_RETRACTED)
                return

        async for message in dm.history(limit=None):
            if self.get_message_ids(message) & linked_ids:
                await self.edit_message(message, DM_RETRACTED)
                return


async def setup(bot):
    await bot.add_cog(Retract(bot))