from typing import Union

import discord
from discord.ext import commands
import snakecore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.engine import Result
from sqlalchemy import text

from ... import __version__
from ...bot import PygameCommunityBot
from ..base import BaseCommandCog
from .constants import DB_TABLE_PREFIX
from .migrations import MIGRATIONS

BotT = PygameCommunityBot


class Polls(BaseCommandCog, name="polls"):
    def __init__(self, bot: BotT, theme_color: int = 0) -> None:
        super().__init__(bot)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: Union[int, discord.Color] = 0):
    await bot.add_cog(Polls(bot, theme_color=int(color)))
