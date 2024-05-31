"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""
import discord
import snakecore

from ...base import ExtensionManager
from ... import __version__
from ...bot import PygameCommunityBot

from .constants import DB_PREFIX
from .migrations import MIGRATIONS

__all__ = ("extension_manager",)

BotT = PygameCommunityBot

# will be needed for CLI
extension_manager = ExtensionManager(
    __name__,
    MIGRATIONS,
    True,  # Always set to True until CLI supports manual migration
    DB_PREFIX,
)


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: int | discord.Color = 0
    # add more optional parameters as desired
):
    from .cogs import TextCommandManagerCog

    await extension_manager.prepare(bot)

    extension_data = await bot.read_extension_data(extension_manager.name)
    await bot.add_cog(
        TextCommandManagerCog(
            bot,
            bot.get_database_engine(),  # type: ignore
            extension_data["revision_number"],
            theme_color=int(color),
        )
    )
