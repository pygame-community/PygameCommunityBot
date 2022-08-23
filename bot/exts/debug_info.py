import datetime
import random
from typing import Optional
import discord
from discord.ext import commands
import snakecore

from bot import constants, __version__ as bot_version


class DebugInfo(commands.Cog):
    def __init__(self, bot: snakecore.commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @commands.command()
    async def version(self, ctx: commands.Context):
        await ctx.send(
            embed=discord.Embed(
                title="Bot Version",
                description=f"`{bot_version}`",
                color=constants.DEFAULT_EMBED_COLOR,
            ),
        )

    @commands.command()
    async def ping(self, ctx: commands.Context):
        """
        ->type Other commands
        ->signature pg!ping
        ->description Get the ping of the bot
        -----
        Implement pg!ping, to get ping
        """
        # now: datetime.datetime = getattr(ctx, "created_at", datetime.datetime.now(datetime.timezone.utc))
        # timedelta = now - ctx.message.created_at
        # sec = timedelta.total_seconds()
        sec2 = self.bot.latency  # This does not refresh that often
        # if sec < sec2:
        #     sec2 = sec

        await ctx.send(
            embed=discord.Embed(
                title=random.choice(("Pingy Pongy", "Pong!")),
                description=""  # f"The bot's ping is `{snakecore.utils.format_time_by_units(sec, decimal_places=0)}`\n"""
                f"The Discord API latency is `{snakecore.utils.format_time_by_units(sec2, decimal_places=0)}`",
                color=constants.DEFAULT_EMBED_COLOR,
            )
        )


async def setup(bot: snakecore.commands.Bot):
    await bot.add_cog(DebugInfo(bot))
