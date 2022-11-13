import datetime
import random
from typing import Optional, Union
import discord
from discord.ext import commands
import snakecore

from pcbot import constants, PygameCommunityBot, __version__ as bot_version

from .base import BaseCommandCog

BotT = PygameCommunityBot


class DebugInfo(BaseCommandCog, name="debug-info"):
    invoke_on_message_edit: bool = True

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
    async def ping(
        self,
        ctx: commands.Context[BotT],
    ):
        """Get the ping of the bot, including the current Discord API latency."""

        response_embed = discord.Embed(
            title=random.choice(("Pingy Pongy", "Pong!")),
            color=constants.DEFAULT_EMBED_COLOR,
        )

        response_message = await self.send_or_edit_response(ctx, embed=response_embed)

        timedelta = (response_message.edited_at or response_message.created_at) - (  # type: ignore
            ctx.message.edited_at or ctx.message.created_at
        )

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
