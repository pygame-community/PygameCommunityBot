from abc import ABC
import re
from typing import Any, Callable, Collection, Literal, NotRequired, TypedDict
import discord
import snakecore

from .utils import *
from .validators import *

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class ShowcaseChannelConfig(TypedDict):
    """A typed dict for specifying showcase channel configurations."""

    channel_id: int
    default_auto_archive_duration: NotRequired[int]
    default_thread_slowmode_delay: NotRequired[int]
    showcase_message_rules: RuleSpecifier | RuleSpecifierPair | RuleSpecifierList
    "A rule specifier dict for validating messages posted to the showcase channel"
