import asyncio
from collections import OrderedDict
import time
from typing import MutableMapping, Union

import discord
from discord.ext import commands
import snakecore
from snakecore.utils.pagination import EmbedPaginator

from pgbot import PygameBot

BotT = PygameBot


class BaseCommandCog(commands.Cog):
    def __init__(self, bot: BotT) -> None:
        super().__init__()
        self.bot = bot
        self._global_response_message_cache = hasattr(
            bot, "recent_response_messages"
        ) and isinstance(bot.recent_response_messages, MutableMapping)

        if self._global_response_message_cache:
            self.recent_response_messages: MutableMapping[int, discord.Message]
            self.recent_response_messages = bot.recent_response_messages
        else:
            self.recent_response_messages: OrderedDict[int, discord.Message]
            self.recent_response_messages = OrderedDict()

        self._global_embed_paginator_cache = hasattr(
            bot, "recent_embed_paginators"
        ) and isinstance(bot.recent_embed_paginators, MutableMapping)

        if self._global_embed_paginator_cache:
            self.recent_embed_paginators: MutableMapping[
                int, list[Union[EmbedPaginator, asyncio.Task[None]]]
            ]
            self.recent_embed_paginators = bot.recent_embed_paginators
        else:
            self.recent_embed_paginators: OrderedDict[
                int, list[Union[EmbedPaginator, asyncio.Task[None]]]
            ]
            self.recent_embed_paginators = OrderedDict()

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message) -> None:
        if new.author.bot or not self._global_response_message_cache:
            return

        if (time.time() - (new.edited_at or new.created_at).timestamp()) < 120:
            if (ctx := await self.bot.get_context(new)).valid and (
                ctx.command.extras.get("invoke_on_message_edit", False)
                or ctx.command.extras.get("invoke_on_message_edit") is not False
                and ctx.cog is not None
                and getattr(ctx.cog, "invoke_on_message_edit", False)
            ):
                await self.bot.invoke(ctx)

    async def cog_after_invoke(self, ctx: commands.Context[BotT]) -> None:
        if not self._global_response_message_cache and not self._global_embed_paginator_cache:
            for _ in range(min(100, max(len(self.recent_response_messages) - 512, 0))):
                _, response_message = self.recent_response_messages.popitem(last=False)
                paginator_list = self.recent_embed_paginators.get(response_message.id)
                if paginator_list is not None and paginator_list[0].is_running():
                    paginator_list[1].cancel()

        elif not self._global_response_message_cache:
            for _ in range(min(100, max(len(self.recent_response_messages) - 512, 0))):
                self.recent_response_messages.popitem(last=False)

        elif not self._global_embed_paginator_cache:
            for _ in range(min(100, max(len(self.recent_embed_paginators) - 512, 0))):
                _, paginator_list = self.recent_embed_paginators.popitem(last=False)
                if paginator_list[0].is_running():
                    paginator_list[1].cancel()
