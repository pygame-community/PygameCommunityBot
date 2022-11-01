from ast import literal_eval
import asyncio
import io
import json
from typing import TYPE_CHECKING, Optional, Union

import discord
from discord.ext import commands
import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import CodeBlock, String

from .base import BaseCommandCog

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]
MessageableGuildChannel = Union[
    discord.TextChannel, discord.VoiceChannel, discord.Thread
]


class Messaging(BaseCommandCog, name="messaging"):
    @commands.group(invoke_without_command=True, aliases=["msg"])
    async def message(self, ctx: commands.Context[BotT]):
        pass

    @commands.guild_only()
    @message.command(
        name="sendtext", aliases=["text"], extras=dict(delete_invocation=True)
    )
    async def message_sendtext(
        self,
        ctx: commands.Context[BotT],
        content: str,
        to: Optional[tuple[MessageableGuildChannel, ...]] = None,
        reply_to: Optional[discord.PartialMessage] = None,
        delete_after: Optional[float] = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: Union[tuple[discord.User], bool] = False,
        mention_roles: Union[tuple[discord.Role], bool] = False,
        mention_replied_user: bool = False,
    ):
        assert ctx.guild and isinstance(ctx.channel, discord.abc.GuildChannel)

        destinations = to
        if not destinations:
            destinations = (ctx.channel,)

        for dest in destinations:
            msg = await (
                reply_to.reply(
                    content=content,
                    allowed_mentions=(
                        discord.AllowedMentions.all()
                        if mention_all
                        else discord.AllowedMentions(
                            everyone=mention_everyone,
                            users=mention_users,
                            roles=mention_roles,
                            replied_user=mention_replied_user,
                        )
                    ),
                )
                if reply_to
                else dest.send(
                    content=content,
                    allowed_mentions=(
                        discord.AllowedMentions.all()
                        if mention_all
                        else discord.AllowedMentions(
                            everyone=mention_everyone,
                            users=mention_users,
                            roles=mention_roles,
                            replied_user=mention_replied_user,
                        )
                    ),
                )
            )
            if delete_after:
                await msg.delete(delay=delete_after)

    @commands.guild_only()
    @message.command(
        name="edittext",
        extras=dict(inject_reference_as_first_argument=True, delete_invocation=True),
    )
    async def message_edittext(
        self,
        ctx: commands.Context[BotT],
        message: Optional[discord.Message],
        content: str,
    ):
        assert ctx.guild and isinstance(ctx.channel, discord.abc.GuildChannel)

        if not message:
            raise commands.CommandInvokeError(
                commands.BadArgument("No message given as input.")
            )
        await message.edit(
            content=content,
        )

    @message.command(name="send", extras=dict(delete_invocation=True))
    @flagconverter_kwargs()
    async def message_send(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        c: Optional[String] = None,
        text: Optional[String] = None,
        content: Optional[String] = None,
        embeds: tuple[CodeBlock, ...],
        to: Optional[tuple[MessageableGuildChannel, ...]] = None,
        reply_to: Optional[discord.PartialMessage] = None,
        delete_after: Optional[float] = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: Union[tuple[discord.User], bool] = False,
        mention_roles: Union[tuple[discord.Role], bool] = False,
        mention_replied_user: bool = False,
    ):
        assert ctx.guild and isinstance(ctx.channel, discord.abc.GuildChannel)

        content = c or text or content

        if not (content or attachments or embeds):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        destinations = to
        if not destinations:
            destinations = (ctx.channel,)

        parsed_embeds = []
        files = []

        if embeds:
            for i, code_block in enumerate(embeds):
                if code_block.language in ("json", None):
                    try:
                        embed_dict = json.loads(code_block.code)
                    except Exception as jerr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing JSON code block "
                                f"{i}: {jerr.__class__.__name__}: {jerr.args[0]}"
                            )
                        )
                elif code_block.language in ("py", "python"):
                    try:
                        embed_dict = literal_eval(code_block.code)
                    except Exception as perr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing Python dict code block "
                                f"{i}: {perr.__class__.__name__}: {perr.args[0]}"
                            )
                        )

                else:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Unsupported code block language: {code_block.language}"
                        )
                    )

                parsed_embeds.append(discord.Embed.from_dict(embed_dict))

        if attachments:
            for i, att in enumerate(attachments):
                if att.size > 2**20 * 8:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Attachment {i} is too large to be resent (> 8MiB)"
                        )
                    )
                files.append(await att.to_file(use_cached=True))

        for dest in destinations:
            msg = await (
                reply_to.reply(
                    content=content,
                    embeds=parsed_embeds,
                    files=files,
                    allowed_mentions=(
                        discord.AllowedMentions.all()
                        if mention_all
                        else discord.AllowedMentions(
                            everyone=mention_everyone,
                            users=mention_users,
                            roles=mention_roles,
                            replied_user=mention_replied_user,
                        )
                    ),
                )
                if reply_to
                else dest.send(
                    content=content,
                    embeds=parsed_embeds,
                    files=files,
                    allowed_mentions=(
                        discord.AllowedMentions.all()
                        if mention_all
                        else discord.AllowedMentions(
                            everyone=mention_everyone,
                            users=mention_users,
                            roles=mention_roles,
                            replied_user=mention_replied_user,
                        )
                    ),
                )
            )
            if delete_after:
                await msg.delete(delay=delete_after)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="edit",
        extras=dict(inject_reference_as_first_argument=True, delete_invocation=True),
    )
    @flagconverter_kwargs()
    async def message_edit(
        self,
        ctx: commands.Context[BotT],
        message: Optional[discord.Message],
        attachments: commands.Greedy[discord.Attachment],
        *,
        c: Optional[String] = None,
        text: Optional[String] = None,
        content: Optional[String] = None,
        embeds: Optional[tuple[CodeBlock, ...]] = None,
        remove_content: bool = False,
        remove_embeds: bool = False,
        remove_all_attachments: bool = False,
        remove_old_attachments: bool = False,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: Union[tuple[discord.User], bool] = False,
        mention_roles: Union[tuple[discord.Role], bool] = False,
        mention_replied_user: bool = False,
    ):
        assert ctx.guild and isinstance(ctx.channel, discord.abc.GuildChannel)

        content = c or text or content

        if not message:
            raise commands.CommandInvokeError(
                commands.BadArgument("No message given as input.")
            )

        if not (content or attachments or embeds):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        parsed_embeds = []
        files = []
        old_attachments = [] if remove_old_attachments else message.attachments

        if embeds:
            for i, code_block in enumerate(embeds):
                if code_block.language in ("json", None):
                    try:
                        embed_dict = json.loads(code_block.code)
                    except Exception as jerr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing JSON code block "
                                f"{i}: {jerr.__class__.__name__}: {jerr.args[0]}"
                            )
                        )
                elif code_block.language in ("py", "python"):
                    try:
                        embed_dict = literal_eval(code_block.code)
                    except Exception as perr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing Python dict code block "
                                f"{i}: {perr.__class__.__name__}: {perr.args[0]}"
                            )
                        )

                else:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Unsupported code block language: {code_block.language}"
                        )
                    )

                parsed_embeds.append(discord.Embed.from_dict(embed_dict))

        if attachments:
            for i, att in enumerate(attachments):
                if att.size > 2**20 * 8:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Attachment {i} is too large to be resent (> 8MiB)"
                        )
                    )
                files.append(await att.to_file(use_cached=True))

        await message.edit(
            content=content
            if content
            else None
            if remove_content
            else discord.utils.MISSING,
            embeds=parsed_embeds
            if parsed_embeds
            else []
            if remove_embeds
            else discord.utils.MISSING,
            attachments=old_attachments + files
            if (files or old_attachments)
            else []
            if remove_all_attachments
            else discord.utils.MISSING,
            allowed_mentions=(
                discord.AllowedMentions.all()
                if mention_all
                else discord.AllowedMentions(
                    everyone=mention_everyone,
                    users=mention_users,
                    roles=mention_roles,
                    replied_user=mention_replied_user,
                )
            ),
        )


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: Union[int, discord.Color] = 0):
    await bot.add_cog(Messaging(bot, theme_color=color))
