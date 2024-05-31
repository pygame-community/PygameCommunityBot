"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""


import discord
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class MyExtensionCog(BaseExtensionCog, name="my-ext"):
    """..."""  # describe your extension cog

    def __init__(self, bot: BotT, theme_color: int | discord.Color = 0) -> None:
        super().__init__(bot, theme_color)

    # add event listeners, commands, state, etc.


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: int | discord.Color = 0,  # add more optional parameters as desired
):
    await bot.add_cog(MyExtensionCog(bot, theme_color=color))
