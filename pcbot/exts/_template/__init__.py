"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import logging
from typing import Union

import discord
import snakecore
from sqlalchemy.ext.asyncio import AsyncEngine

from ... import __version__
from ...bot import PygameCommunityBot
from ..bases import ExtSpec, BaseExtCog
from .constants import DB_TABLE_PREFIX
from .migrations import REVISIONS, ROLLBACKS

BotT = PygameCommunityBot

_logger = logging.getLogger(__name__)


class MyExtCog(BaseExtCog, name="my-ext"):
    """..."""  # describe your extension

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        revision_number: int,
        theme_color: Union[int, discord.Color] = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.db_engine = db_engine
        self.revision_number = revision_number  # use to regulate enabled functionality

    # add event listeners, commands, state, interface with the database, etc.


ext_spec = ExtSpec(
    __name__,
    REVISIONS,
    ROLLBACKS,
    True,  # Always set to True until CLI supports manual migration
    DB_TABLE_PREFIX,
)

# both will be needed for the CLI
migrate = ext_spec.migrate
rollback = ext_spec.rollback


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: Union[int, discord.Color] = 0
    # add more optional parameters as desired
):
    await ext_spec.prepare_setup(bot)
    extension_data = await bot.read_extension_data(ext_spec.name)
    await bot.add_cog(
        MyExtCog(
            bot,
            bot.get_database(),  # type: ignore
            extension_data["revision_number"],
            theme_color=int(color),
        )
    )
