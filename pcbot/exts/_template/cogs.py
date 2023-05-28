import logging

import discord
from sqlalchemy.ext.asyncio import AsyncEngine

from ...bot import PygameCommunityBot
from ..bases import BaseExtCog

BotT = PygameCommunityBot

_logger = logging.getLogger(__package__)


class MyExtCog(BaseExtCog, name="my-ext"):
    """..."""  # describe your extension

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        revision_number: int,
        theme_color: int | discord.Color = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.db_engine = db_engine
        self.revision_number = revision_number  # use to regulate functionality for db table backwards compatibility

    # add event listeners, commands, state, interface with the database, etc.
