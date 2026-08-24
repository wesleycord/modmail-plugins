import asyncio
import logging
from collections import defaultdict

from discord.ext import commands
from dotenv import load_dotenv

from core import checks
from core.models import PermissionLevel

from .client import AIClient, DEFAULT_MODEL
from .commands import execute_command
from .conversation import build

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "_id": "settings",
    "prompt": "",
    "commands": [],
    "model": DEFAULT_MODEL,
    "ai_default": True,
}


class AI(commands.Cog):
    """AI assistant for this Modmail server."""

    def __init__(self, bot):
        load_dotenv()

        self.bot = bot
        self.coll = bot.plugin_db.get_partition(self)
        self.settings = {
            "_id": DEFAULT_SETTINGS["_id"],
            "prompt": DEFAULT_SETTINGS["prompt"],
            "commands": list(DEFAULT_SETTINGS["commands"]),
            "model": DEFAULT_SETTINGS["model"],
            "ai_default": DEFAULT_SETTINGS["ai_default"],
        }
        self.client = AIClient(execute_command)
        self.locks = defaultdict(asyncio.Lock)

    async def cog_load(self):
        self.settings = await self.coll.find_one({"_id": "settings"})
        if not self.settings:
            self.settings = {
                "_id": DEFAULT_SETTINGS["_id"],
                "prompt": DEFAULT_SETTINGS["prompt"],
                "commands": list(DEFAULT_SETTINGS["commands"]),
                "model": DEFAULT_SETTINGS["model"],
                "ai_default": DEFAULT_SETTINGS["ai_default"],
            }
            await self._save()

        self.settings["prompt"] = str(self.settings.get("prompt", ""))
        self.settings["model"] = str(self.settings.get("model", DEFAULT_MODEL)).strip()
        self.settings["ai_default"] = bool(self.settings.get("ai_default", True))
        commands = self.settings.get("commands", [])
        if not isinstance(commands, list):
            commands = []

        self.settings["commands"] = [
            command.strip().lower()
            for command in commands
            if isinstance(command, str) and command.strip()
        ]

    def cog_unload(self):
        self.bot.loop.create_task(self.client.close())

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        await self.bot.api.logs.update_one(
            {"channel_id": str(thread.id)},
            {"$set": {"ai": self.settings["ai_default"]}},
        )

    @commands.Cog.listener()
    async def on_thread_reply(self, thread, is_mod, message, anonymous, plain):
        if is_mod or message.author.bot or not message.content.strip():
            return

        async with self.locks[thread.channel.id]:
            try:
                log = await self.bot.api.get_log(thread.channel.id)
                if not log:
                    return

                if "ai" not in log:
                    log["ai"] = self.settings["ai_default"]
                    await self.bot.api.logs.update_one(
                        {"channel_id": str(thread.channel.id)},
                        {"$set": {"ai": log["ai"]}},
                    )
                if not log["ai"]:
                    return

                await thread.channel.send("AI: Generating Response")
                response = await self.client.respond(
                    build(log, message),
                    thread,
                    self.settings,
                    message,
                )
                print(response, 10110101010101010101010)
                if response:
                    message.author = self.bot.user
                    await thread.reply(message, response, anonymous=False, plain=False)
            except Exception:
                logger.exception("Failed to process AI message %s", message.id)

    @commands.group(name="ai", invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MODERATOR)
    @commands.guild_only()
    async def ai(self, ctx):
        """
        Manage the AI assistant.

        Enable or disable AI for the current thread (moderators):
        - `{prefix}ai on`
        - `{prefix}ai off`
        - `{prefix}ai enable`
        - `{prefix}ai disable`

        View or change the server prompt:
        - `{prefix}ai prompt`
        - `{prefix}ai prompt set <instructions>`
        - `{prefix}ai prompt clear`

        Manage allowed AI commands:
        - `{prefix}ai commands`
        - `{prefix}ai commands add ping`
        - `{prefix}ai commands remove ping`

        Manage the Ollama model:
        - `{prefix}ai models`
        - `{prefix}ai models set <model>`

        Set the default for new threads (owner):
        - `{prefix}ai default on`
        - `{prefix}ai default off`

        View the current AI configuration and this thread's status:
        - `{prefix}ai status`
        """
        await ctx.send_help(ctx.command)

    @ai.command(name="status")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def status(self, ctx):
        """Show the AI assistant's current configuration and this thread's status."""
        prompt = self.settings["prompt"]
        lines = [
            f"Model: `{self.settings['model']}`",
            f"Default for new threads: **{'on' if self.settings['ai_default'] else 'off'}**",
            f"Prompt: {'set (' + str(len(prompt)) + ' chars)' if prompt else 'not set'}",
            "Allowed commands: " + (", ".join(self.settings["commands"]) or "none"),
        ]

        log = await self.bot.api.get_log(ctx.channel.id)
        if log:
            ai_enabled = log.get("ai", self.settings["ai_default"])
            lines.insert(0, f"This thread: **{'enabled' if ai_enabled else 'disabled'}**")
        else:
            lines.insert(0, "This thread: not a Modmail thread")

        await ctx.send("\n".join(lines))

    @ai.group(invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.OWNER)
    async def prompt(self, ctx):
        """View the server-specific AI prompt."""
        await ctx.send(self.settings["prompt"] or "No custom prompt set")

    @prompt.command(name="set")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def prompt_set(self, ctx, *, value):
        """Set server-specific instructions for the AI."""
        self.settings["prompt"] = value.strip()[:4000]
        await self._save()
        await ctx.send("AI prompt updated")

    @prompt.command(name="clear")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def prompt_clear(self, ctx):
        """Remove the server-specific AI prompt."""
        self.settings["prompt"] = ""
        await self._save()
        await ctx.send("AI prompt cleared")

    @ai.group(name="commands", aliases=["command"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.OWNER)
    async def command_list(self, ctx):
        """View commands the AI is allowed to use."""
        allowed = self.settings["commands"]
        await ctx.send("Allowed AI commands: " + (", ".join(allowed) or "none"))

    @command_list.command(name="add")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def command_add(self, ctx, *, value):
        """Add an implemented command to the AI allowlist."""
        value = value.strip().lower()
        if value not in self.settings["commands"]:
            self.settings["commands"].append(value)
            await self._save()
        await ctx.send(f"Allowed AI command: `{value}`")

    @command_list.command(name="remove")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def command_remove(self, ctx, *, value):
        """Remove a command from the AI allowlist."""
        value = value.strip().lower()
        if value in self.settings["commands"]:
            self.settings["commands"].remove(value)
            await self._save()
        await ctx.send(f"Removed AI command: `{value}`")

    @ai.group(name="models", aliases=["model"], invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.OWNER)
    async def models(self, ctx):
        """List installed Ollama models and show the selected model."""
        models = await self.client.models()
        selected = self.settings["model"]
        lines = [
            f"- {model}{' (selected)' if model == selected else ''}"
            for model in models
        ]
        await ctx.send("\n".join(lines) or "No Ollama models are installed")

    @models.command(name="set")
    @checks.has_permissions(PermissionLevel.OWNER)
    async def model_set(self, ctx, *, value):
        """Select an installed Ollama model."""
        value = value.strip()
        if value not in await self.client.models():
            return await ctx.send("That model is not installed. Use `ai models` first")

        self.settings["model"] = value
        await self._save()
        await ctx.send(f"AI model set to `{value}`")

    async def _set_thread_ai(self, ctx, enabled):
        log = await self.bot.api.get_log(ctx.channel.id)
        if not log:
            return await ctx.send("No log found for this thread")

        await self.bot.api.logs.update_one(
            {"channel_id": str(ctx.channel.id)},
            {"$set": {"ai": enabled}},
        )
        await ctx.send(f"AI {'enabled' if enabled else 'disabled'} for this thread")

    @ai.command(name="on", aliases=["enable"])
    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    async def ai_on(self, ctx):
        """Enable AI responses for the current thread."""
        await self._set_thread_ai(ctx, True)

    @ai.command(name="off", aliases=["disable"])
    @checks.has_permissions(PermissionLevel.MODERATOR)
    @checks.thread_only()
    async def ai_off(self, ctx):
        """Disable AI responses for the current thread."""
        await self._set_thread_ai(ctx, False)

    @ai.group(name="default", invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.OWNER)
    async def ai_default(self, ctx):
        """Configure whether AI starts enabled in new threads."""
        await ctx.send_help(ctx.command)

    async def _set_default(self, enabled):
        self.settings["ai_default"] = enabled
        await self._save()

    @ai_default.command(name="on", aliases=["enable"])
    @checks.has_permissions(PermissionLevel.OWNER)
    async def ai_default_on(self, ctx):
        """Start AI enabled in new threads."""
        await self._set_default(True)
        await ctx.send("AI is on by default")

    @ai_default.command(name="off", aliases=["disable"])
    @checks.has_permissions(PermissionLevel.OWNER)
    async def ai_default_off(self, ctx):
        """Start AI disabled in new threads."""
        await self._set_default(False)
        await ctx.send("AI is off by default")

    async def _run_command(self, command, thread, allowed, message):
        from .commands import execute_command

        return await execute_command(command, thread, allowed, message)

    async def _save(self):
        await self.coll.replace_one({"_id": "settings"}, self.settings, upsert=True)


async def setup(bot):
    await bot.add_cog(AI(bot))