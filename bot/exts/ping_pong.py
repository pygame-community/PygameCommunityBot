"""A sample bot extension.
"""
from discord.ext import commands


@commands.command()
async def ping(ctx: commands.Context[commands.Bot]):
    await ctx.channel.send("pong!")


async def setup(bot: commands.Bot):
    bot.add_command(ping)
