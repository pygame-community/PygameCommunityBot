"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import discord
import snakecore

from ...bot import PygameCommunityBot
from ...base import ExtensionManager
from .constants import DB_PREFIX
from .migrations import MIGRATIONS

__all__ = ("extension_manager",)

BotT = PygameCommunityBot

extension_manager = ExtensionManager(
    name=__name__,
    migrations=MIGRATIONS,
    default_auto_migrate=True,
    db_prefix=DB_PREFIX,
)


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    info_channel_id: int | None = None,
    info_channel_ids: list[int] | None = None,
    info_entry_key_regexp: str = r"(?:[a-z\d\-]+(?:\s*\|\s*[a-z\d\-]+)*)",
    theme_color: int | discord.Color = 0xFFD868,
):
    from .cogs import InfoChannelCog

    await extension_manager.prepare(bot)
    extension_data = await bot.read_extension_data(extension_manager.name)

    channel_ids: list[int] = []
    if info_channel_id is not None:
        channel_ids.append(int(info_channel_id))
    if info_channel_ids:
        channel_ids.extend(int(channel_id) for channel_id in info_channel_ids)
    channel_ids = list(dict.fromkeys(channel_ids))

    await bot.add_cog(
        InfoChannelCog(
            bot,
            bot.get_database_engine(),  # type: ignore
            extension_data["revision_number"],
            channel_ids,
            info_entry_key_regexp,
            theme_color=int(theme_color),
        )
    )
