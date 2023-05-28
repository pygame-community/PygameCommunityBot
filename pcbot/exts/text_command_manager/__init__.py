"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from typing import Literal

import discord
import snakecore

from ... import __version__
from ...bot import PygameCommunityBot
from ..bases import ExtSpec

from .constants import DB_TABLE_PREFIX, ZERO_UUID, UUID_PATTERN
from ._types import GuildTextCommandState
from .migrations import REVISIONS, ROLLBACKS

BotT = PygameCommunityBot

ChannelOrRoleOverrides = list[
    tuple[
        discord.Role
        | discord.TextChannel
        | discord.VoiceChannel
        | discord.ForumChannel
        | Literal[
            "all channels",
            "All Channels",
            "All channels",
            "all Channels",
            "ALL CHANNELS",
            "everyone",
            "@everyone",
            "Everyone",
            "EVERYONE",
        ],
        bool,
    ]
]


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
    color: int | discord.Color = 0
    # add more optional parameters as desired
):
    from .cogs import TextCommandManagerCog

    await ext_spec.prepare_setup(bot)
    extension_data = await bot.read_extension_data(ext_spec.name)
    await bot.add_cog(
        TextCommandManagerCog(
            bot,
            bot.get_database(),  # type: ignore
            extension_data["revision_number"],
            theme_color=int(color),
        )
    )
