import asyncio
from collections import OrderedDict
from typing import Optional, Sequence, Union

import discord
from discord.ext import commands
import snakecore
from snakecore.utils.pagination import EmbedPaginator

from .. import __version__

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]


class BaseCommandCog(commands.Cog):
    __version__ = __version__

    def __init__(self, bot: BotT, theme_color: Union[int, discord.Color] = 0) -> None:
        super().__init__()
        self.bot = bot
        self.theme_color = discord.Color(int(theme_color))
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

    async def send_or_edit_response(
        self,
        ctx: commands.Context[BotT],
        content: Optional[str] = discord.utils.MISSING,
        *,
        tts: bool = discord.utils.MISSING,
        embed: Optional[discord.Embed] = discord.utils.MISSING,
        embeds: Optional[Sequence[discord.Embed]] = discord.utils.MISSING,
        attachments: Sequence[
            Union[discord.Attachment, discord.File]
        ] = discord.utils.MISSING,
        file: Optional[discord.File] = discord.utils.MISSING,
        files: Optional[Sequence[discord.File]] = discord.utils.MISSING,
        stickers: Optional[
            Sequence[Union[discord.GuildSticker, discord.StickerItem]]
        ] = None,
        delete_after: Optional[float] = None,
        nonce: Optional[Union[str, int]] = None,
        allowed_mentions: Optional[discord.AllowedMentions] = discord.utils.MISSING,
        reference: Optional[
            Union[discord.Message, discord.MessageReference, discord.PartialMessage]
        ] = None,
        mention_author: Optional[bool] = None,
        view: Optional[discord.ui.View] = discord.utils.MISSING,
        suppress_embeds: bool = False,
        suppress: bool = False,
        destination: Optional[discord.abc.Messageable] = None,
    ) -> discord.Message:  # type: ignore

        suppress_embeds = suppress or suppress_embeds
        destination = destination or ctx.channel

        send = False
        if (
            response_message := self.cached_response_messages.get(ctx.message.id)
        ) is not None:
            try:
                return await response_message.edit(
                    content=content,
                    embed=embed,
                    embeds=embeds,
                    attachments=attachments,
                    delete_after=delete_after,
                    allowed_mentions=allowed_mentions,
                    suppress=suppress_embeds,
                    view=view,
                )  # type: ignore
            except discord.NotFound:
                send = True
        else:
            send = True

        if send:
            self.cached_response_messages[
                ctx.message.id
            ] = response_message = await destination.send(
                content=None if content is discord.utils.MISSING else content,
                tts=None if tts is discord.utils.MISSING else tts,
                embed=None if embed is discord.utils.MISSING else embed,
                embeds=None if embeds is discord.utils.MISSING else embeds,
                file=None if file is discord.utils.MISSING else file,
                files=None if files is discord.utils.MISSING else files,
                stickers=stickers,
                delete_after=delete_after,
                nonce=nonce,
                allowed_mentions=None
                if allowed_mentions is discord.utils.MISSING
                else allowed_mentions,
                reference=reference,
                mention_author=mention_author,
                view=None if view is discord.utils.MISSING else view,
                suppress_embeds=suppress_embeds,
            )  # type: ignore

            return response_message

    async def send_paginated_embeds(
        self,
        ctx: commands.Context[BotT],
        *embeds: discord.Embed,
        destination: Optional[discord.abc.Messageable] = None,
    ):
        assert isinstance(
            ctx.author, discord.Member
        )  # this shouldn't normally be false
        paginator = None

        if not embeds:
            return

        destination = destination or ctx.channel

        if (
            response_message := self.cached_response_messages.get(ctx.message.id)
        ) is not None:
            try:
                if (
                    paginator_tuple := self.cached_embed_paginators.get(
                        response_message.id
                    )
                ) is not None:
                    if paginator_tuple[0].is_running():
                        await paginator_tuple[0].stop()

                if len(embeds) == 1:
                    await response_message.edit(embed=embeds[0])
                    return

                paginator = snakecore.utils.pagination.EmbedPaginator(
                    (
                        response_message := await response_message.edit(
                            content="\u200b", embed=None
                        )
                    ),
                    *embeds,
                    caller=ctx.author,
                    inactivity_timeout=60,
                    theme_color=int(self.theme_color),
                )
            except discord.NotFound:

                if len(embeds) == 1:
                    self.cached_response_messages[
                        ctx.message.id
                    ] = await destination.send(embed=embeds[0])
                    return

                paginator = snakecore.utils.pagination.EmbedPaginator(
                    (response_message := await destination.send(content="\u200b")),
                    *embeds,
                    caller=ctx.author,
                    inactivity_timeout=60,
                    theme_color=int(self.theme_color),
                )
        else:
            if len(embeds) == 1:
                self.cached_response_messages[ctx.message.id] = await destination.send(
                    embed=embeds[0]
                )
                return

            paginator = snakecore.utils.pagination.EmbedPaginator(
                (response_message := await destination.send(content="\u200b")),
                *embeds,
                caller=ctx.author,
                inactivity_timeout=60,
                theme_color=int(self.theme_color),
            )

        paginator_tuple = (
            paginator,
            asyncio.create_task(
                paginator.mainloop(client=ctx.bot),
                name=f"embed_paginator({response_message.jump_url})",
            ),
        )

        self.cached_response_messages[ctx.message.id] = response_message
        self.cached_embed_paginators[response_message.id] = paginator_tuple
