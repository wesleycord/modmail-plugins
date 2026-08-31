"""Apply optional team visibility rules to Modmail's logs commands."""

from typing import Optional

import discord
from discord.ext import commands

from core.paginator import EmbedPaginatorSession
from core.utils import User, safe_typing


async def visible_logs(bot, author, entries):
	"""Filter entries only when the optional Teams plugin is loaded."""
	teams = bot.get_cog("Teams")
	if teams is None:
		return entries
	return [entry for entry in entries if await teams.can_view_log(author, entry)]


class LogAccessOverrides(commands.Cog):
	"""Own the core logs callback overrides and restore them on unload."""

	def __init__(self, bot):
		self.bot = bot
		self.original_callbacks = {}

	async def cog_load(self):
		logs = self.bot.get_command("logs")
		if logs is None:
			return

		self.original_callbacks[None] = logs.callback
		logs.callback = LogAccessOverrides.logs
		callbacks = {
			"closed-by": LogAccessOverrides.closed_by,
			"key": LogAccessOverrides.key,
			"responded": LogAccessOverrides.responded,
			"search": LogAccessOverrides.search,
		}
		for name, callback in callbacks.items():
			command = logs.get_command(name)
			if command is not None:
				self.original_callbacks[name] = command.callback
				command.callback = callback

	def cog_unload(self):
		logs = self.bot.get_command("logs")
		if logs is None:
			return
		for name, callback in self.original_callbacks.items():
			command = logs if name is None else logs.get_command(name)
			if command is not None:
				command.callback = callback

	async def logs(core_cog, ctx, *, user: User = None):
		async with safe_typing(ctx):
			pass

		if not user:
			thread = ctx.thread
			if not thread:
				return
			user = thread.recipient or await ctx.bot.get_or_fetch_user(thread.id)

		default_avatar = "https://cdn.discordapp.com/embed/avatars/0.png"
		icon_url = getattr(user, "avatar_url", default_avatar)
		entries = await ctx.bot.api.get_user_logs(user.id)
		entries = [entry for entry in entries if not entry["open"]]
		entries = await visible_logs(ctx.bot, ctx.author, entries)

		if not entries:
			return await ctx.send(embed=discord.Embed(
				color=ctx.bot.error_color,
				description="This user does not have any previous logs.",
			))

		core_cog = ctx.command.cog
		embeds = core_cog.format_log_embeds(reversed(entries), avatar_url=icon_url)
		await EmbedPaginatorSession(ctx, *embeds).run()

	async def closed_by(core_cog, ctx, *, user: User = None):
		user = user if user is not None else ctx.author
		entries = await ctx.bot.api.search_closed_by(user.id)
		entries = await visible_logs(ctx.bot, ctx.author, entries)
		core_cog = ctx.command.cog
		embeds = core_cog.format_log_embeds(
			entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
		)
		if not embeds:
			return await ctx.send(embed=discord.Embed(
				color=ctx.bot.error_color,
				description="No log entries have been found for that query.",
			))
		await EmbedPaginatorSession(ctx, *embeds).run()

	async def key(core_cog, ctx, key: str):
		entries = await ctx.bot.api.find_log_entry(key)
		entries = await visible_logs(ctx.bot, ctx.author, entries)
		if not entries:
			return await ctx.send(embed=discord.Embed(
				color=ctx.bot.error_color,
				description=f"Log entry `{key}` not found.",
			))
		core_cog = ctx.command.cog
		embeds = core_cog.format_log_embeds(entries, avatar_url=ctx.author.avatar.url)
		await EmbedPaginatorSession(ctx, *embeds).run()

	async def responded(core_cog, ctx, *, user: User = None):
		user = user if user is not None else ctx.author
		entries = await ctx.bot.api.get_responded_logs(user.id)
		entries = await visible_logs(ctx.bot, ctx.author, entries)
		core_cog = ctx.command.cog
		embeds = core_cog.format_log_embeds(
			entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
		)
		if not embeds:
			return await ctx.send(embed=discord.Embed(
				color=ctx.bot.error_color,
				description=f"{getattr(user, 'mention', user.id)} has not responded to any threads.",
			))
		await EmbedPaginatorSession(ctx, *embeds).run()

	async def search(core_cog, ctx, limit: Optional[int] = None, *, query):
		async with safe_typing(ctx):
			pass

		entries = await ctx.bot.api.search_by_text(query, limit)
		entries = await visible_logs(ctx.bot, ctx.author, entries)
		core_cog = ctx.command.cog
		embeds = core_cog.format_log_embeds(
			entries, avatar_url=ctx.bot.get_guild_icon(guild=ctx.guild)
		)
		if not embeds:
			return await ctx.send(embed=discord.Embed(
				color=ctx.bot.error_color,
				description="No log entries have been found for that query.",
			))
		await EmbedPaginatorSession(ctx, *embeds).run()


async def setup(bot):
	await bot.add_cog(LogAccessOverrides(bot))
