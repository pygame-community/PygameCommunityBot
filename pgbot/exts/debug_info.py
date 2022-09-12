import asyncio
from collections import OrderedDict
import datetime
import random
import time
from typing import Optional, TypeVar
import discord
from discord.ext import commands
import snakecore

from pgbot import constants, __version__ as bot_version
from pgbot.utils import message_delete_reaction_listener

BotT = TypeVar("BotT", snakecore.commands.Bot, snakecore.commands.AutoShardedBot)


class DebugInfo(commands.Cog):
    def __init__(self, bot: BotT) -> None:
        super().__init__()
        self.bot = bot
        self.response_message_cache: OrderedDict[int, discord.Message] = OrderedDict()

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message) -> None:
        if new.author.bot:
            return

        if (time.time() - (new.edited_at or new.created_at).timestamp()) < 120:
            if (
                ctx := await self.bot.get_context(new)
            ).valid and ctx.command.cog is self:
                await self.bot.invoke(ctx)

        elif new.id in self.response_message_cache:
            del self.response_message_cache[new.id]

    async def cog_after_invoke(self, ctx: commands.Context[BotT]) -> None:
        for _ in range(min(100, max(len(self.response_message_cache) - 512, 0))):
            self.response_message_cache.popitem(last=False)

    @commands.command()
    async def version(self, ctx: commands.Context[BotT]):
        await ctx.send(
            embed=discord.Embed(
                title="Bot Version",
                description=f"`{bot_version}`",
                color=constants.DEFAULT_EMBED_COLOR,
            ),
        )

    @commands.command()
    async def ping(self, ctx: commands.Context[BotT]):
        """
        ->type Other commands
        ->signature pg!ping
        ->description Get the ping of the bot
        -----
        Implement pg!ping, to get ping
        """

        response_embed = discord.Embed(
            title=random.choice(("Pingy Pongy", "Pong!")),
            color=constants.DEFAULT_EMBED_COLOR,
        )

        try:
            if response_message := self.response_message_cache.get(ctx.message.id):
                response_message = await response_message.edit(embed=response_embed)
                timedelta = response_message.edited_at - (
                    ctx.message.edited_at or ctx.message.created_at
                )
        except discord.NotFound:
            pass
        finally:
            if response_message is None:
                self.response_message_cache[
                    ctx.message.id
                ] = response_message = await ctx.send(embed=response_embed)
                timedelta = response_message.created_at - ctx.message.created_at

        sec = timedelta.total_seconds()
        sec2 = self.bot.latency

        response_embed.description = (
            "The currently measured bot ping is "
            f"`{snakecore.utils.format_time_by_units(sec, decimal_places=0)}`\n"
            f"The Discord API latency is "
            f"`{snakecore.utils.format_time_by_units(sec2, decimal_places=0)}`"
        )

        await response_message.edit(embed=response_embed)


async def setup(bot: BotT):
    await bot.add_cog(DebugInfo(bot))
