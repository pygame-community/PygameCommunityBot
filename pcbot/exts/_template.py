"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from typing import Union

import discord
from discord.ext import commands
import snakecore

from .base import BaseCommandCog

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]


class MyExt(
    BaseCommandCog, name="my-ext"
):  # if multiple cogs are present, use MyExtCog as a name instead
    """..."""  # describe your extension cog

    def __init__(self, bot: BotT, theme_color: Union[int, discord.Color] = 0) -> None:
        super().__init__(bot, theme_color)

    # add event listeners, commands, state, etc.


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: Union[int, discord.Color] = 0,  # add more optional parameters as desired
):
    await bot.add_cog(MyExt(bot))
