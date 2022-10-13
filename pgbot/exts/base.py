import asyncio
from collections import OrderedDict
import time
from typing import MutableMapping, Union

import discord
from discord.ext import commands
import snakecore
from snakecore.utils.pagination import EmbedPaginator

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]


class BaseCommandCog(commands.Cog):
    def __init__(self, bot: BotT) -> None:
        # type: ignore
        super().__init__()
        self.bot = bot
        self._global_cached_response_messages = (
            hasattr(bot, "cached_response_messages")
            and hasattr(bot, "cached_response_messages_maxsize")
            and isinstance(bot.cached_response_messages, OrderedDict)  # type: ignore
        )

        if self._global_cached_response_messages:
            self.cached_response_messages: OrderedDict[
                int, discord.Message
            ] = bot.cached_response_messages  # type: ignore
            self.cached_response_messages_maxsize = int(
                bot.cached_response_messages_maxsize  # type: ignore
            )
        else:
            self.cached_response_messages: OrderedDict[
                int, discord.Message
            ] = OrderedDict()
            self.cached_response_messages_maxsize: int = 50

        self._global_cached_embed_paginators = (
            hasattr(bot, "cached_embed_paginators")
            and hasattr(bot, "cached_embed_paginators_maxsize")
            and isinstance(bot.cached_embed_paginators, OrderedDict)  # type: ignore
        )

        if self._global_cached_embed_paginators:
            self.cached_embed_paginators: OrderedDict[  # type: ignore
                int, tuple[EmbedPaginator, asyncio.Task[None]]
            ] = bot.cached_embed_paginators  # type: ignore
            self.cached_embed_paginators_maxsize = int(
                bot.cached_embed_paginators_maxsize  # type: ignore
            )
        else:
            self.cached_embed_paginators: OrderedDict[
                int, tuple[EmbedPaginator, asyncio.Task[None]]
            ] = OrderedDict()
            self.cached_embed_paginators_maxsize: int = 50

    async def cog_after_invoke(self, ctx: commands.Context[BotT]) -> None:
        if (
            not self._global_cached_response_messages
            and not self._global_cached_embed_paginators
        ):
            for _ in range(
                min(
                    100,
                    max(
                        len(self.cached_response_messages)
                        - self.cached_response_messages_maxsize,
                        0,
                    ),
                )
            ):
                _, response_message = self.cached_response_messages.popitem(last=False)
                paginator_tuple = self.cached_embed_paginators.get(response_message.id)
                if paginator_tuple is not None and paginator_tuple[0].is_running():  # type: ignore
                    paginator_tuple[1].cancel()  # type: ignore

        elif not self._global_cached_response_messages:
            for _ in range(
                min(
                    100,
                    max(
                        len(self.cached_response_messages)
                        - self.cached_response_messages_maxsize,
                        0,
                    ),
                )
            ):
                self.cached_response_messages.popitem(last=False)

        elif not self._global_cached_embed_paginators:
            for _ in range(
                min(
                    100,
                    max(
                        len(self.cached_embed_paginators)
                        - self.cached_embed_paginators_maxsize,
                        0,
                    ),
                )
            ):
                _, paginator_tuple = self.cached_embed_paginators.popitem(last=False)
                if paginator_tuple[0].is_running():  # type: ignore
                    paginator_tuple[1].cancel()  # type: ignore
