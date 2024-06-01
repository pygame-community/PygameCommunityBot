"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file defines constants
"""

from typing import Any
import discord

UID = "pcbot"
"The unique identifier of this bot application."

DEFAULT_EMBED_COLOR = 0xFFD868
SUCCESS_COLOR = 0x00AA00
KNOWN_COMMAND_ERROR_COLOR = 0x851D08
UNKNOWN_COMMAND_ERROR_COLOR = 0xFF0000
PGC_LOADING_EMOJI_ID = 1017826887990509661


LOG_LEVEL_NAMES: set[str] = {
    "CRITICAL",
    "FATAL",
    "ERROR",
    "WARN",
    "WARNING",
    "INFO",
    "DEBUG",
    "NOTSET",
}


DEFAULT_EXTENSIONS: list[dict[str, Any]] = [
    # Add extensions here that should always be loaded upon startup.
    # These can only be excluded through the --ignore-ext' or '--disable-all-exts'
    # CLI options.
    {
        "name": f"{__package__}.exts.bot_management",
        "config": {
            "color": DEFAULT_EMBED_COLOR,
        },
    },
    {
        "name": f"{__package__}.exts.docs_pre",
        "config": {"color": DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.help",
        "config": {"color": DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.messaging",
    },
    {
        "name": f"{__package__}.exts.polls_pre",
    },
    {
        "name": f"{__package__}.exts.text_command_manager",
        "config": {"color": DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.channel_manager",
        "config": {"color": DEFAULT_EMBED_COLOR},
    },
]

DEFAULT_CONFIG: dict[str, Any] = {  # default bot configuration settings
    "intents": discord.Intents.default().value,
    "command_prefix": "!",
    "final_prefix": None,
    "mention_as_command_prefix": False,
    "extensions": [],
    "log_level": None,
}
