import random
from typing import Optional, Union
import discord
from discord.ext import commands
import snakecore

from pgbot import constants, PygameBot, __version__ as bot_version

from .base import BaseCommandCog

BotT = PygameBot


class DebugInfo(BaseCommandCog, name="debug-info"):
    invoke_on_message_edit: bool = True

    def __init__(self, bot: BotT) -> None:
        super().__init__(bot)

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

        response_message = self.cached_response_messages.get(ctx.message.id)

        try:
            if response_message is not None:
                response_message = await response_message.edit(embed=response_embed)
                timedelta = response_message.edited_at - (
                    ctx.message.edited_at or ctx.message.created_at
                )
        except discord.NotFound:
            pass

        finally:
            if response_message is None:
                self.cached_response_messages[
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
