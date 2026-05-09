"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from ast import literal_eval
import asyncio
import datetime
import io
import json
from typing import Literal

import aiohttp
import discord
from discord.ext import commands
import snakecore

from snakecore.utils.regex_patterns import HTTP_URL
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import (
    CodeBlock,
    Parens,
    ReferencedMessage,
    String,
    TimeDelta,
    StringExpr,
)

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)


def invocation_error(message: str) -> commands.CommandInvokeError:
    return commands.CommandInvokeError(commands.CommandError(message))


async def get_message_attachments_files(
    message: discord.Message,
    *,
    size_limit: int,
) -> list[discord.File]:
    """Collect attachments from a message with size checks."""

    files = []
    size_limit_mib = size_limit // (2**20)
    for i, attachment in enumerate(message.attachments):
        if attachment.size > size_limit:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    f"Attachment {i} is too large to be resent (> {size_limit_mib}MiB)"
                )
            )
        files.append(await attachment.to_file(use_cached=True))

    return files


async def get_message_attachment_file(
    message: discord.Message,
    *,
    index: int,
    size_limit: int,
) -> discord.File:
    """Collect a single attachment from a message by index with size checks."""

    if not message.attachments:
        raise commands.CommandInvokeError(
            commands.CommandError(
                "Message specified for `attachment_src` has no attachments to use."
            )
        )

    clamped_index = min(max(index, 0), len(message.attachments) - 1)
    attachment = message.attachments[clamped_index]
    size_limit_mib = size_limit // (2**20)
    if attachment.size > size_limit:
        raise commands.CommandInvokeError(
            commands.CommandError(
                f"Attachment {clamped_index} is too large to be resent (> {size_limit_mib}MiB)"
            )
        )

    return await attachment.to_file(use_cached=True)


def get_message_embed_by_index(
    message: discord.Message,
    *,
    index: int,
) -> discord.Embed:
    """Collect a single embed from a message by index."""

    if not message.embeds:
        raise commands.CommandInvokeError(
            commands.CommandError(
                "Message specified for `embed_src` has no embeds to use."
            )
        )

    clamped_index = min(max(index, 0), len(message.embeds) - 1)
    return message.embeds[clamped_index]


def trim_markdown_h1_prefix(content: str) -> str:
    """Trim a leading markdown H1 line from content if present."""

    lines = content.splitlines(True)
    if lines and lines[0].startswith("# "):
        return "".join(lines[1:])

    return content


def get_markdown_member_info(member: discord.Member | discord.User):
    member_name_info = f"\u200b\n*Name*: \n> {member.mention} \n> "
    if hasattr(member, "nick") and member.display_name:
        member_nick = (
            member.display_name.replace("\\", r"\\")
            .replace("*", r"\*")
            .replace("`", r"\`")
            .replace("_", r"\_")
        )
        member_name_info += (
            f"**{member_nick}**\n> (*{member.name}#{member.discriminator}*)\n\n"
        )
    else:
        member_name_info += f"**{member.name}**#{member.discriminator}\n\n"

    member_created_at_info = f"*Created On*:\n> {snakecore.utils.create_markdown_timestamp(member.created_at)}\n\n"

    if isinstance(member, discord.Member) and member.joined_at:
        member_joined_at_info = f"*Joined On*:\n> {snakecore.utils.create_markdown_timestamp(member.joined_at)}\n\n"
    else:
        member_joined_at_info = "*Joined On*: \n> `...`\n\n"

    member_func_role_count = (
        max(
            len(tuple(member.roles[i] for i in range(1, len(member.roles)))),
            0,
        )
        if isinstance(member, discord.Member)
        else ""
    )

    if isinstance(member, discord.Member) and member_func_role_count:
        member_top_role_info = f"*Highest Role*: \n> {member.roles[-1].mention}\n> `<@&{member.roles[-1].id}>`\n\n"
        if member_func_role_count != len(member.roles) - 1:
            member_role_count_info = f"*Role Count*: \n> `{member_func_role_count} ({len(member.roles) - 1})`\n\n"
        else:
            member_role_count_info = f"*Role Count*: \n> `{member_func_role_count}`\n\n"
    else:
        member_top_role_info = member_role_count_info = ""

    member_id_info = f"*Member ID*: \n> <@`{member.id}`>\n\n"

    if isinstance(member, discord.Member):
        member_stats = (
            f"*Is Pending Screening*: \n> `{'Yes' if member.pending else 'No'}`\n\n"
            f"*Is Bot Account*: \n> `{'Yes' if member.bot else 'No'}`\n\n"
            f"*Is System User (Discord Official)*: \n> `{'Yes' if member.system else 'No'}`\n\n"
        )
    else:
        member_stats = (
            f"*Is Bot Account*: \n> `{'Yes' if member.bot else 'No'}`\n\n"
            f"*Is System User (Discord Official)*: \n> `{'Yes' if member.system else 'No'}`\n\n"
        )

    return "".join(
        (
            member_name_info,
            member_created_at_info,
            member_joined_at_info,
            member_top_role_info,
            member_role_count_info,
            member_id_info,
            member_stats,
        )
    )


def get_msg_info_embed(msg: discord.Message, author: bool = True):
    """
    Generate an embed containing info about a message and its author.
    """
    member: discord.Member | discord.User = msg.author

    msg_created_at_info = f"*Created On:*\n> {snakecore.utils.create_markdown_timestamp(msg.created_at)}\n\n"

    if msg.edited_at:
        msg_edited_at_info = f"*Last Edited On*: \n> {snakecore.utils.create_markdown_timestamp(msg.edited_at)}\n\n"

    else:
        msg_edited_at_info = "*Last Edited On*: \n> `...`\n\n"

    msg_id_info = f"*Message ID*: \n> `{msg.id}`\n\n"
    msg_char_count_info = f"*Character Count*: \n> `{len(msg.content) if isinstance(msg.content, str) else 0}`\n\n"
    msg_attachment_info = f"*Number Of Attachments*: \n> `{len(msg.attachments)}`\n\n"
    msg_embed_info = f"*Number Of Embeds*: \n> `{len(msg.embeds)}`\n\n"
    msg_is_pinned = f"*Is Pinned*: \n> `{'Yes' if msg.pinned else 'No'}`\n\n"

    msg_info = "".join(
        (
            msg_created_at_info,
            msg_edited_at_info,
            msg_char_count_info,
            msg_id_info,
            msg_embed_info,
            msg_attachment_info,
            msg_is_pinned,
        )
    )

    if author:
        return discord.Embed.from_dict(
            dict(
                title="__Message & Author Info__",
                description="\n".join(
                    (
                        "__Text"
                        + (" (Shortened)" if len(msg.content) > 2000 else "")
                        + "__:",
                        (
                            f"\n {msg.content[:2001]}" + "\n\n[...]"
                            if len(msg.content) > 2000
                            else msg.content
                        ),
                        "\u200b",
                    )
                ),
                thumbnail=dict(url=member.display_avatar.url),
                fields=[
                    dict(name="__Message Info__", value=msg_info, inline=True),
                    dict(
                        name="__Message Author Info__",
                        value=get_markdown_member_info(member),
                        inline=True,
                    ),
                    dict(
                        name="\u200b",
                        value=f"**[View Original Message]({msg.jump_url})**",
                        inline=False,
                    ),
                ],  # type: ignore)
            )
        )

    member_name_info = f"\u200b\n*Name*: \n> {member.mention} \n> "

    if isinstance(member, discord.Member) and member.nick:
        member_nick = (
            member.nick.replace("\\", r"\\")
            .replace("*", r"\*")
            .replace("`", r"\`")
            .replace("_", r"\_")
        )
        member_name_info += (
            f"**{member_nick}**\n> (*{member.name}#{member.discriminator}*)\n\n"
        )
    else:
        member_name_info += f"**{member.name}**#{member.discriminator}\n\n"

    return discord.Embed.from_dict(
        dict(
            title="__Message Info__",
            author=dict(
                name=f"{member.name}#{member.discriminator}",
                icon_url=member.display_avatar.url,
            ),
            description="\n".join(
                (
                    "__Text"
                    + (" (Shortened)" if len(msg.content) > 2000 else "")
                    + "__:",
                    (
                        f"\n {msg.content[:2001]}" + "\n[...]"
                        if len(msg.content) > 2000
                        else msg.content
                    ),
                    "\u200b",
                )
            ),
            fields=[
                dict(
                    name="__" + ("Message " if author else "") + "Info__",
                    value=member_name_info + msg_info,
                    inline=True,
                ),
                dict(
                    name="\u200b",
                    value=f"**[View Original Message]({msg.jump_url})**",
                    inline=False,
                ),
            ],  # type: ignore)
        )
    )


class Messaging(BaseExtensionCog, name="messaging"):
    async def _fetch_url_bytes(self, url: str) -> bytes:
        """Fetch raw bytes from a URL using aiohttp.

        Reuses the Discord.py HTTP session when available.
        """

        existing_session = getattr(self.bot.http, "_HTTPClient__session", None)
        owns_session = (
            not isinstance(existing_session, aiohttp.ClientSession)
            or existing_session.closed
        )

        session: aiohttp.ClientSession
        if owns_session:
            session = aiohttp.ClientSession()
        else:
            assert isinstance(existing_session, aiohttp.ClientSession)
            session = existing_session

        try:
            async with session.get(url) as response:
                if response.status >= 400:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "Failed to fetch URL resource: "
                            f"HTTP {response.status} {response.reason or ''}".strip()
                        )
                    )
                return await response.read()
        except commands.CommandInvokeError:
            raise
        except aiohttp.ClientError as err:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    f"Failed to fetch URL resource: {err.__class__.__name__}: {err}"
                )
            )
        finally:
            if owns_session:
                await session.close()

    def _resolve_webhook_avatar_url(
        self,
        *,
        webhook_avatar_url: str | None = None,
        webhook_no_avatar: bool = False,
    ) -> str | None:
        """Resolve the effective avatar URL to use for webhook operations."""

        if webhook_no_avatar:
            return None

        if webhook_avatar_url:
            return webhook_avatar_url

        if self.bot.user is not None:
            return self.bot.user.display_avatar.url

        return None

    async def _resolve_messaging_webhook(
        self,
        channel: MessageableGuildChannel | discord.ForumChannel,
        *,
        webhook_name: str | None = None,
        webhook_url: str | None = None,
        webhook_avatar_url: str | None = None,
        webhook_no_avatar: bool = False,
    ) -> tuple[discord.Webhook, discord.Thread | None]:
        """Resolve a webhook for a target channel/thread, creating one if needed.

        If `webhook_url` is provided, it is used directly.
        Otherwise, this resolves an existing channel webhook by name or creates one.
        """

        thread = channel if isinstance(channel, discord.Thread) else None

        if webhook_url:
            try:
                webhook = discord.Webhook.from_url(str(webhook_url), client=self.bot)
            except Exception as err:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Invalid `webhook_url:` flag value: "
                        f"{err.__class__.__name__}: {err}"
                    )
                )

            return (webhook, thread)

        target_channel = (
            channel.parent if isinstance(channel, discord.Thread) else channel
        )
        if not isinstance(target_channel, (discord.TextChannel, discord.ForumChannel)):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Webhooks can only be used in text/forum channels and threads."
                )
            )

        resolved_webhook_name = str(
            webhook_name
            if webhook_name
            else f"{self.bot.user.name} Messaging"
            if self.bot.user
            else "Messaging"
        )

        try:
            existing_webhooks = await target_channel.webhooks()
        except discord.HTTPException as err:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Failed to fetch channel webhooks: "
                    f"{err.__class__.__name__}: {err.text or err}"
                )
            )

        for webhook in existing_webhooks:
            if webhook.name == resolved_webhook_name:
                return webhook, thread

        effective_webhook_avatar_url = self._resolve_webhook_avatar_url(
            webhook_avatar_url=webhook_avatar_url,
            webhook_no_avatar=webhook_no_avatar,
        )
        avatar_bytes = (
            await self._fetch_url_bytes(effective_webhook_avatar_url)
            if effective_webhook_avatar_url
            else None
        )

        try:
            webhook = await target_channel.create_webhook(
                name=resolved_webhook_name,
                avatar=avatar_bytes,
            )
        except discord.HTTPException as err:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Failed to create webhook in target channel: "
                    f"{err.__class__.__name__}: {err.text or err}"
                )
            )

        return (webhook, thread)

    async def _parse_embeds(
        self,
        embeds: tuple[Parens[discord.Message, int] | discord.Message | CodeBlock, ...],
    ) -> list[discord.Embed]:
        parsed: list[discord.Embed] = []
        for i, item in enumerate(embeds):
            if isinstance(item, CodeBlock):
                code_block = item
                if code_block.language in ("json", None):
                    try:
                        embed_dict = json.loads(code_block.code)
                    except Exception as err:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error while parsing JSON code block "
                                f"{i}: {err.__class__.__name__}: {err.args[0]}"
                            )
                        )
                elif code_block.language in ("py", "python"):
                    try:
                        embed_dict = literal_eval(code_block.code)
                    except Exception as err:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error while parsing Python dict code block "
                                f"{i}: {err.__class__.__name__}: {err.args[0]}"
                            )
                        )
                else:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Unsupported code block language: {code_block.language}"
                        )
                    )
            elif isinstance(item, (discord.Message, tuple)):
                embed_msg = item
                attachment_index = 0
                if isinstance(embed_msg, tuple):
                    embed_msg, attachment_index = embed_msg[0], embed_msg[1]

                if not (embed_msg_attachments := embed_msg.attachments):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Error with `embeds` argument {i}: Messages "
                            "specified for flag `embeds` must have at least one "
                            "attachment as `.txt`, `.py` file containing a Python "
                            "dictionary, or a `.json` file containing embed data. "
                            "It must be less than 10KB in size."
                        )
                    )

                embed_attachment = embed_msg_attachments[
                    min(attachment_index, len(embed_msg_attachments) - 1)
                ]

                if not (
                    embed_attachment.content_type
                    and embed_attachment.content_type.startswith(
                        ("text", "application/json")
                    )
                    and embed_attachment.size < 10240
                ):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Error with `embeds` argument {i}: Messages "
                            "specified for flag `embeds` must have at least one "
                            "attachment as `.txt`, `.py` file containing a Python "
                            "dictionary, or a `.json` file containing embed data. "
                            "It must be less than 10KB in size."
                        )
                    )

                embed_data = (await embed_attachment.read()).decode("utf-8")

                if (
                    embed_attachment.content_type.startswith(
                        ("application/json", "text")
                    )
                    and "x-python" not in embed_attachment.content_type
                ):
                    try:
                        embed_dict = json.loads(embed_data)
                    except Exception as err:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error while parsing embed JSON from attachment "
                                f"{i}: {err.__class__.__name__}: {err.args[0]}"
                            )
                        )
                else:
                    try:
                        embed_dict = literal_eval(embed_data)
                    except Exception as err:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error while parsing Python embed dict from attachment "
                                f"{i}: {err.__class__.__name__}: {err.args[0]}"
                            )
                        )
            else:
                continue

            parsed.append(discord.Embed.from_dict(embed_dict))

        return parsed

    async def _resolve_embeds(
        self,
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        message_src: discord.Message | ReferencedMessage | None = None,
        *,
        former_embeds: list[discord.Embed] | None = None,
    ) -> list[discord.Embed]:
        if embeds:
            parsed = await self._parse_embeds(embeds)
            if former_embeds is not None:
                parsed = [
                    embed or former_embeds[i]
                    for i, embed in enumerate(parsed)
                    if embed or i < len(former_embeds)
                ]
            return parsed

        if embed_src:
            return [
                get_message_embed_by_index(msg, index=idx) for msg, idx in embed_src
            ]

        if embeds_src is not None:
            if not embeds_src.embeds:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Message specified for `embeds_src` has no embeds to use."
                    )
                )
            return list(embeds_src.embeds)

        if message_src is not None:
            return list(message_src.embeds)

        return []

    async def _resolve_send_files(
        self,
        attachments: list[discord.Attachment],
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        attachments_src: discord.Message | ReferencedMessage | None = None,
        message_src: discord.Message | ReferencedMessage | None = None,
        *,
        size_limit: int = 2**20 * 25,
    ) -> list[discord.File]:
        files: list[discord.File] = []

        if attachments:
            for i, att in enumerate(attachments):
                if att.size > size_limit:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Attachment {i} is too large to be resent "
                            f"(> {size_limit // 2**20} MiB)"
                        )
                    )
                files.append(await att.to_file(use_cached=True))
            return files

        if attachment_src:
            for src_message, index in attachment_src:
                files.append(
                    await get_message_attachment_file(
                        src_message,
                        index=index,
                        size_limit=size_limit,
                    )
                )
        elif attachments_src is not None:
            if not attachments_src.attachments:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Message specified for `attachments_src` has no attachments to use."
                    )
                )
            files.extend(
                await get_message_attachments_files(
                    attachments_src,
                    size_limit=size_limit,
                )
            )
        elif message_src is not None and message_src.attachments:
            files.extend(
                await get_message_attachments_files(
                    message_src,
                    size_limit=size_limit,
                )
            )

        return files

    def _build_allowed_mentions(
        self,
        mention_all: bool,
        mention_everyone: bool = False,
        mention_users: bool | tuple = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool | tuple = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool = False,
    ) -> discord.AllowedMentions:
        if mention_all:
            return discord.AllowedMentions.all()
        return discord.AllowedMentions(
            everyone=mention_everyone,
            users=(mention_these_users if mention_these_users else mention_users),
            roles=(mention_these_roles if mention_these_roles else mention_roles),
            replied_user=mention_replied_user,
        )

    async def message_send_func(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String | str | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        to: tuple[MessageableGuildChannel, ...] = (),
        reply_to: discord.PartialMessage | None = None,
        delete_after: float | TimeDelta | None = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: bool = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool = False,
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
    ):
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not (
            content
            or attachments
            or embeds
            or content_src
            or embed_src
            or attachments_src
            or attachment_src
            or embeds_src
            or message_src
        ):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        destinations = to or (ctx.channel,)

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author, destinations, "view_channel"
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    "target channel(s) "
                    f"({', '.join(f'<#{dest.id}>' for dest in destinations)})."
                )
            )

        resolved_content = None
        if content is not None:
            resolved_content = content
        elif content_src is not None:
            if not content_src.content:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Message specified for `content_src` has no content to use."
                    )
                )
            resolved_content = content_src.content
        elif message_src is not None and message_src.content:
            resolved_content = message_src.content

        parsed_embeds = await self._resolve_embeds(
            embeds=embeds,
            embed_src=embed_src,
            embeds_src=embeds_src,
            message_src=message_src,
        )
        files = await self._resolve_send_files(
            attachments,
            attachment_src=attachment_src,
            attachments_src=attachments_src,
            message_src=message_src,
            size_limit=2**20 * 25,
        )
        allowed_mentions = self._build_allowed_mentions(
            mention_all,
            mention_everyone,
            mention_users,
            mention_these_users,
            mention_roles,
            mention_these_roles,
            mention_replied_user,
        )

        delete_after_seconds = (
            delete_after.total_seconds()
            if isinstance(delete_after, datetime.timedelta)
            else delete_after
        )

        explicit_webhook_flags = bool(
            webhook_name
            or webhook_url
            or webhook_username
            or webhook_avatar_url
            or webhook_no_avatar
        )
        effective_webhook_avatar_url = self._resolve_webhook_avatar_url(
            webhook_avatar_url=(webhook_avatar_url or None),
            webhook_no_avatar=webhook_no_avatar,
        )

        if reply_to is not None and explicit_webhook_flags:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Webhook flags cannot be used together with `reply_to:`."
                )
            )

        for dest in destinations:
            if reply_to is None:
                if explicit_webhook_flags:
                    webhook, thread = await self._resolve_messaging_webhook(
                        dest,
                        webhook_name=webhook_name,
                        webhook_url=webhook_url,
                        webhook_avatar_url=(webhook_avatar_url or None),
                        webhook_no_avatar=webhook_no_avatar,
                    )
                    if webhook is not None:
                        send_kwargs = dict(
                            content=(
                                str(resolved_content)
                                if resolved_content is not None
                                else ""
                            ),
                            embeds=parsed_embeds,
                            files=files,
                            allowed_mentions=allowed_mentions,
                            username=(
                                str(webhook_username)
                                if webhook_username
                                else discord.utils.MISSING
                            ),
                            avatar_url=(
                                effective_webhook_avatar_url
                                if effective_webhook_avatar_url
                                else discord.utils.MISSING
                            ),
                            wait=True,
                        )
                        if thread is not None:
                            send_kwargs["thread"] = thread  # type: ignore
                        try:
                            msg = await webhook.send(**send_kwargs)  # type: ignore
                        except discord.HTTPException as err:
                            raise commands.CommandInvokeError(
                                commands.CommandError(
                                    "Failed to send message via webhook: "
                                    f"{err.__class__.__name__}: {err.text or err}"
                                )
                            )
                        if delete_after_seconds:
                            await msg.delete(delay=delete_after_seconds)
                        continue

                await dest.send(
                    content=resolved_content,
                    embeds=parsed_embeds,
                    files=files,
                    allowed_mentions=allowed_mentions,
                    delete_after=delete_after_seconds,  # type: ignore
                )
            else:
                await reply_to.reply(
                    content=resolved_content,
                    embeds=parsed_embeds,
                    files=files,
                    allowed_mentions=allowed_mentions,
                    delete_after=delete_after_seconds,  # type: ignore
                )

    async def message_edit_func(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message | ReferencedMessage,
        attachments: commands.Greedy[discord.Attachment],
        *,
        name: String[100] | None = None,
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        tags: tuple[str, ...] = (),
        auto_hide_duration: Literal["1h", "24h", "1d", "3d", "1w"] | None = None,
        slowmode_delay: TimeDelta = datetime.timedelta(),
        remove_content: bool = False,
        remove_embeds: bool = False,
        remove_all_attachments: bool = False,
        remove_old_attachments: bool = False,
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
        mention_all: bool | None = None,
        mention_everyone: bool | None = None,
        mention_users: bool | None = None,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool | None = None,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool | None = None,
    ):
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(ctx.channel, MessageableGuildChannel.__args__)
            and isinstance(ctx.author, discord.Member)
        )

        if not (
            content
            or name
            or tags
            or attachments
            or embeds
            or content_src
            or attachment_src
            or embed_src
            or attachments_src
            or embeds_src
            or message_src
        ):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            message.channel,  # type: ignore
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"target channel(s) (<#{message.channel.id}>)."  # type: ignore
                )
            )

        is_thread_starter_msg = False

        if name and not isinstance(message.channel, discord.Thread):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Flag 'name:' or 'title:' can only be specified if targeting "
                    "the starter message of a thread."
                )
            )
        elif tags and not (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent
            and isinstance(message.channel.parent, discord.ForumChannel)
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Flag 'tags:' can only be specified if targeting the starter "
                    "message of a forum channel post."
                )
            )
        elif (name or tags) and isinstance(message.channel, discord.Thread):
            is_thread_starter_msg = True

        tag_names = tuple(tag_name.casefold() for tag_name in tags)

        resolved_content = None
        if content is not None:
            resolved_content = content
        elif content_src is not None:
            if not content_src.content:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Message specified for `content_src` has no content to use."
                    )
                )
            resolved_content = content_src.content
        elif message_src is not None and message_src.content:
            resolved_content = message_src.content

        parsed_embeds = await self._resolve_embeds(
            embeds=embeds,
            embed_src=embed_src,
            embeds_src=embeds_src,
            message_src=message_src,
            former_embeds=message.embeds,
        )
        files = await self._resolve_send_files(
            attachments,
            attachment_src=attachment_src,
            attachments_src=attachments_src,
            message_src=message_src,
            size_limit=2**20 * 8,
        )

        old_attachments = [] if remove_old_attachments else message.attachments
        final_attachments = discord.utils.MISSING
        if files or old_attachments:
            final_attachments = (old_attachments + files)[
                max(-10, -(len(old_attachments) + len(files))) :
            ]
        elif remove_all_attachments:
            final_attachments = []

        allowed_mentions_kwargs: dict = {}
        if not mention_all:
            for kwarg, value in (
                ("everyone", mention_everyone),
                (
                    "users",
                    mention_these_users if mention_these_users else mention_users,
                ),
                (
                    "roles",
                    mention_these_roles if mention_these_roles else mention_roles,
                ),
                ("replied_user", mention_replied_user),
            ):
                if value is not None:
                    allowed_mentions_kwargs[kwarg] = value

        final_allowed_mentions = (
            discord.AllowedMentions.all()
            if mention_all
            else (
                discord.AllowedMentions(**allowed_mentions_kwargs)
                if allowed_mentions_kwargs
                else discord.utils.MISSING
            )
        )

        AUTO_ARCHIVE = {"1h": 60, "24h": 1440, "3d": 4320, "1w": 10080}
        if is_thread_starter_msg:
            await message.channel.edit(  # type: ignore
                name=name or discord.utils.MISSING,
                applied_tags=[
                    tag
                    for tag in message.channel.parent.available_tags  # type: ignore
                    if tag.name.casefold() in tag_names
                ]
                or discord.utils.MISSING,
                auto_archive_duration=(
                    AUTO_ARCHIVE[auto_hide_duration]
                    if auto_hide_duration
                    else discord.utils.MISSING
                ),  # type: ignore
                slowmode_delay=(
                    slowmode_delay.seconds if slowmode_delay else discord.utils.MISSING
                ),
            )

        final_content = (
            str(resolved_content)
            if resolved_content
            else None
            if remove_content
            else discord.utils.MISSING
        )
        final_embeds = (
            parsed_embeds
            if parsed_embeds
            else []
            if remove_embeds
            else discord.utils.MISSING
        )

        explicit_webhook_flags = bool(
            webhook_url
            or webhook_name
            or webhook_username
            or webhook_avatar_url
            or webhook_no_avatar
        )
        effective_webhook_avatar_url = self._resolve_webhook_avatar_url(
            webhook_avatar_url=(webhook_avatar_url or None),
            webhook_no_avatar=webhook_no_avatar,
        )

        if explicit_webhook_flags:
            resolved_webhook, resolved_thread = await self._resolve_messaging_webhook(
                message.channel,  # type: ignore
                webhook_name=webhook_name,
                webhook_url=webhook_url,
                webhook_avatar_url=(webhook_avatar_url or None),
                webhook_no_avatar=webhook_no_avatar,
            )

            if resolved_webhook is None:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Webhook flags were provided but no usable webhook could be resolved."
                    )
                )

            if webhook_username or webhook_avatar_url or webhook_no_avatar:
                try:
                    await resolved_webhook.edit(
                        name=(
                            str(webhook_username)
                            if webhook_username
                            else discord.utils.MISSING
                        ),
                        avatar=(
                            None
                            if webhook_no_avatar
                            else (
                                await self._fetch_url_bytes(
                                    effective_webhook_avatar_url
                                )
                                if effective_webhook_avatar_url
                                else discord.utils.MISSING
                            )
                        ),
                    )
                except discord.HTTPException as err:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "Failed to update webhook profile: "
                            f"{err.__class__.__name__}: {err.text or err}"
                        )
                    )

            try:
                edit_kwargs = dict(
                    content=final_content,
                    embeds=final_embeds,
                    attachments=final_attachments,
                    allowed_mentions=final_allowed_mentions,
                )
                if resolved_thread is not None:
                    edit_kwargs["thread"] = resolved_thread
                await resolved_webhook.edit_message(message.id, **edit_kwargs)  # type: ignore
            except discord.HTTPException as err:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Failed to edit message via webhook: "
                        f"{err.__class__.__name__}: {err.text or err}"
                    )
                )
            return

        await message.edit(
            content=final_content,
            embeds=final_embeds,
            attachments=final_attachments,
            allowed_mentions=final_allowed_mentions,
        )

    @commands.group(
        invoke_without_command=True,
        aliases=["msg"],
        usage="[attachments 'upload files < 8 MiB']... [message_src: Message] "
        "[content_src: Message] [content: Text[2000]] "
        "[attachments_src: Message] [attachment_src: Message Number]... "
        "[embeds_src: Message] [embed_src: Message Number]... [embeds: CodeBlock...] "
        "[to: Channel] [reply_to: Message] "
        "[webhook_name: Text[80]] [webhook_url: Text] "
        "[webhook_username: Text[80]] [webhook_avatar_url: Text] "
        "[webhook_no_avatar: yes|no] "
        "[delete_after: Number/TimeDelta] [mention_all: yes|no] "
        "[mention_everyone: yes|no] [mention_users: yes|no] "
        "[mention_these_users: User...] [mention_roles: yes|no] "
        "[mention_these_roles: Role...] [mention_replied_user: yes|no]",
    )
    @flagconverter_kwargs()
    async def message(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String[2000] | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        to: tuple[MessageableGuildChannel, ...] = (),
        reply_to: discord.PartialMessage | None = None,
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
        delete_after: float | TimeDelta | None = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: bool = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool = False,
    ):
        """Send a message to the invocation channel or a custom destination.

        __**Parameters:**__

        **`[attachments (upload files < (25 MiB))]...`**
        > One or more attachments to add to the message.

        **`[message_src: Message]`**
        > A flag for using content, embeds, and attachments from another message.
        > Explicit flags override the corresponding parts from this source.

        **`[content_src: Message]`**
        > A flag for using the text content from another message.
        > The source message must contain text content.

        **`[content: Text[2000]]`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[attachments_src: Message]`**
        > A flag for using all attachments from another message.
        > The source message must contain attachments.

        **`[attachment_src: Message Number]...`**
        > A flag for using one attachment from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds_src: Message]`**
        > A flag for using all embeds from another message.
        > The source message must contain embeds.

        **`[embed_src: Message Number]...`**
        > A flag for using one embed from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds: CodeBlock...]`**
        > A flag for the embeds to add to the message, as 1-10 code blocks containing embed data as a JSON object/Python dictionary.

        **`[to: Channel]`**
        > A flag for the destination channel of The URL of the message to send.
        > Defaults to the command invocation channel.

        **`[reply_to: Message]`**
        > A flag for The URL of the message to use as a reference.

        **`[webhook_name: Text[80]]`**
        > A flag for enabling webhook mode with an internal webhook in each target channel.
        > If webhook mode is enabled and `webhook_url:` is omitted, `{bot_name} Messaging` is used.

        **`[webhook_url: Text]`**
        > A flag for enabling webhook mode with a pre-existing webhook URL.

        **`[webhook_username: Text[80]]`**
        > A flag for overriding the displayed sender name for webhook-delivered messages.

        **`[webhook_avatar_url: Text]`**
        > A flag for overriding the displayed sender avatar for webhook-delivered messages.

        **`[webhook_no_avatar: yes|no]`**
        > A flag for disabling webhook avatars.
        > This overrides `webhook_avatar_url:` when set to 'yes'.

        **`[delete_after: Number/TimeDelta]`**
        > A flag to set a deletion timeout for the message upon its creation.

        **`[mention_all: yes|no]`**
        > A flag for whether all mentionable targets in the message text content (users, roles, user being replied to) should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_everyone: yes|no]`**
        > A flag for whether @everyone should be mentioned.

        **`[mention_users: yes|no]`**
        > A flag for whether any mentioned users in the message text content should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_these_users: User...]`**
        > A flag for a sequence of users in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_users:` flag.

        **`[mention_roles: yes|no]`**
        > A flag for whether any mentioned roles in the message text content should receive a mention ping.
        > Can be either 'yes' or 'no', or a sequence of roles to ping.
        > Defaults to 'no'.

        **`[mention_these_roles: Role...]`**
        > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        return await self.message_send_func(
            ctx,
            attachments,
            message_src=message_src,
            content_src=content_src,
            content=content,
            attachments_src=attachments_src,
            attachment_src=attachment_src,
            embeds_src=embeds_src,
            embed_src=embed_src,
            embeds=embeds,
            to=to,
            reply_to=reply_to,
            webhook_name=webhook_name,
            webhook_url=webhook_url,
            webhook_username=webhook_username,
            webhook_avatar_url=webhook_avatar_url,
            webhook_no_avatar=webhook_no_avatar,
            delete_after=delete_after,
            mention_all=mention_all,
            mention_everyone=mention_everyone,
            mention_users=mention_users,
            mention_these_users=mention_these_users,
            mention_roles=mention_roles,
            mention_these_roles=mention_these_roles,
            mention_replied_user=mention_replied_user,
        )

    @message.command(
        name="send",
        aliases=["create"],
        usage=message.usage,
        help=message.help,
        extras=dict(delete_invocation=True),
    )
    @flagconverter_kwargs()
    async def message_send(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String[2000] | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        to: tuple[MessageableGuildChannel, ...] = (),
        reply_to: discord.PartialMessage | None = None,
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
        delete_after: float | TimeDelta | None = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: bool = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool = False,
    ):
        return await self.message_send_func(
            ctx,
            attachments,
            message_src=message_src,
            content_src=content_src,
            content=content,
            attachments_src=attachments_src,
            attachment_src=attachment_src,
            embeds_src=embeds_src,
            embed_src=embed_src,
            embeds=embeds,
            to=to,
            reply_to=reply_to,
            webhook_name=webhook_name,
            webhook_url=webhook_url,
            webhook_username=webhook_username,
            webhook_avatar_url=webhook_avatar_url,
            webhook_no_avatar=webhook_no_avatar,
            delete_after=delete_after,
            mention_all=mention_all,
            mention_everyone=mention_everyone,
            mention_users=mention_users,
            mention_these_users=mention_these_users,
            mention_roles=mention_roles,
            mention_these_roles=mention_these_roles,
            mention_replied_user=mention_replied_user,
        )

    @message.command(
        name="post",
        aliases=["thread"],
        usage="[attachments 'upload files < 8 MiB']... <to: ForumChannel> "
        "<name|title: Text[100]> [message_src: Message] "
        "[content_src: Message] [content: Text[2000]] "
        "[attachments_src: Message] [attachment_src: Message Number]... "
        "[embeds_src: Message] [embed_src: Message Number]... [embeds: CodeBlock...] "
        "[tags: String[20]...] [auto_hide_duration: 1h|24h|1d|3d|1w] "
        "[slowmode_delay: TimeDelta] [trim_h1: yes|no] "
        "[webhook_name: Text[80]] [webhook_url: Text] "
        "[webhook_username: Text[80]] [webhook_avatar_url: Text] "
        "[webhook_no_avatar: yes|no] "
        "[mention_all: yes|no] [mention_everyone: yes|no] [mention_users: yes|no] "
        "[mention_these_users: User...] [mention_roles: yes|no] "
        "[mention_these_roles: Role...] [mention_replied_user: yes|no]",
        extras=dict(delete_invocation=True),
    )
    @flagconverter_kwargs()
    async def message_post(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        to: tuple[discord.ForumChannel, ...],
        name: String[100] = commands.flag(name="name", aliases=["title"]),
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String[2000] | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        tags: tuple[str, ...] = (),
        trim_h1: bool = False,
        auto_hide_duration: (
            Literal["1h", "24h", "1d", "3d", "1w"] | None
        ) = commands.flag(aliases=["auto_archive_duration"], default=None),
        slowmode_delay: TimeDelta = datetime.timedelta(),
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: bool = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
    ):
        """Create a post in the specified forum channel(s).

        __**Parameters:**__

        **`[attachments (upload files < (25 MiB))]...`**
        > One or more attachments to add to the message.

        **`<to: ForumChannel...>`**
        > A flag for the destination channels to send the post to.
        > If forum tags are specified, only one destination will be accepted.

        **`<name|title: Text[100]>`**
        > A flag for the thread or forum post name/title.
        > It must not exceed 100 characters in length.

        **`[message_src: Message]`**
        > A flag for using content, embeds, and attachments from another message.
        > Explicit flags override the corresponding parts from this source.

        **`[content_src: Message]`**
        > A flag for using the text content from another message.
        > The source message must contain text content.

        **`[content: Text[2000]]`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[attachments_src: Message]`**
        > A flag for using all attachments from another message.
        > The source message must contain attachments.

        **`[attachment_src: Message Number]...`**
        > A flag for using one attachment from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds_src: Message]`**
        > A flag for using all embeds from another message.
        > The source message must contain embeds.

        **`[embed_src: Message Number]...`**
        > A flag for using one embed from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds: CodeBlock...]`**
        > A flag for the embeds to add to the message, as 1-10 code blocks containing embed data as a JSON object/Python dictionary.

        **`[tags: String[20]...]`**
        > The tags to apply to a post, if they exist.

        **`[auto_hide_duration: 1h|24h|1d|3d|1w]`**
        > The duration after which to hide threads or posts from the channel sidebar.
        > Omission leads to the default parent channel value being used.

        **`[slowmode_delay: TimeDelta]`**
        > The slowmode delay to use. Omission disables slowmode.

        **`[trim_h1: yes|no]`**
        > A flag for removing a leading markdown H1 line ("# ...") from the final message content.
        > Defaults to 'no'.

        **`[webhook_name: Text[80]]`**
        > A flag for enabling webhook mode for forum post creation.
        > If set and `webhook_url:` is omitted, an internal `{bot_name} Messaging` webhook is resolved/created.

        **`[webhook_url: Text]`**
        > A flag for enabling webhook mode with a pre-existing webhook URL.

        **`[webhook_username: Text[80]]`**
        > A flag for overriding the displayed sender name for webhook-delivered posts.

        **`[webhook_avatar_url: Text]`**
        > A flag for overriding the displayed sender avatar for webhook-delivered posts.

        **`[webhook_no_avatar: yes|no]`**
        > A flag for disabling webhook avatars.
        > This overrides `webhook_avatar_url:` when set to 'yes'.

        **`[mention_all: yes|no]`**
        > A flag for whether all mentionable targets in the message text content (users, roles, user being replied to) should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_everyone: yes|no]`**
        > A flag for whether @everyone should be mentioned.

        **`[mention_users: yes|no]`**
        > A flag for whether any mentioned users in the message text content should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_these_users: User...]`**
        > A flag for a sequence of users in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_users:` flag.

        **`[mention_roles: yes|no]`**
        > A flag for whether any mentioned roles in the message text content should receive a mention ping.
        > Can be either 'yes' or 'no', or a sequence of roles to ping.
        > Defaults to 'no'.

        **`[mention_these_roles: Role...]`**
        > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not (
            content
            or attachments
            or embeds
            or content_src
            or embed_src
            or attachments_src
            or attachment_src
            or embeds_src
            or message_src
        ):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        destinations = to or (ctx.channel,)

        if len(destinations) > 1 and tags:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You cannot specify multiple channels for flag `to:` if flag "
                    "`tags:` is specified."
                )
            )

        tag_names = tuple(tag_name.casefold() for tag_name in tags)

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author, destinations, "view_channel"
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    "target channel(s) "
                    f"({', '.join(f'<#{dest.id}>' for dest in destinations)})."
                )
            )

        resolved_content = None
        if content is not None:
            resolved_content = content
        elif content_src is not None:
            if not content_src.content:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Message specified for `content_src` has no content to use."
                    )
                )
            resolved_content = content_src.content
        elif message_src is not None and message_src.content:
            resolved_content = message_src.content

        parsed_embeds = await self._resolve_embeds(
            embeds=embeds,
            embed_src=embed_src,
            embeds_src=embeds_src,
            message_src=message_src,
        )
        files = await self._resolve_send_files(
            attachments,
            attachment_src=attachment_src,
            attachments_src=attachments_src,
            message_src=message_src,
            size_limit=2**20 * 25,
        )
        allowed_mentions = self._build_allowed_mentions(
            mention_all,
            mention_everyone,
            mention_users,
            mention_these_users,
            mention_roles,
            mention_these_roles,
        )

        AUTO_ARCHIVE = {"1h": 60, "24h": 1440, "3d": 4320, "1w": 10080}
        auto_archive_duration = (
            AUTO_ARCHIVE[auto_hide_duration]
            if auto_hide_duration
            else discord.utils.MISSING
        )

        explicit_webhook_flags = bool(
            webhook_name
            or webhook_url
            or webhook_username
            or webhook_avatar_url
            or webhook_no_avatar
        )
        effective_webhook_avatar_url = self._resolve_webhook_avatar_url(
            webhook_avatar_url=(webhook_avatar_url or None),
            webhook_no_avatar=webhook_no_avatar,
        )

        final_content = str(resolved_content) if resolved_content is not None else None
        if trim_h1 and final_content:
            final_content = trim_markdown_h1_prefix(final_content)

        for dest in destinations:
            assert isinstance(dest, discord.ForumChannel)
            applied_tags = [
                tag for tag in dest.available_tags if tag.name.casefold() in tag_names
            ]

            if explicit_webhook_flags:
                webhook, _ = await self._resolve_messaging_webhook(
                    dest,
                    webhook_name=webhook_name,
                    webhook_url=webhook_url,
                    webhook_avatar_url=(webhook_avatar_url or None),
                    webhook_no_avatar=webhook_no_avatar,
                )
                try:
                    msg = await webhook.send(
                        content=final_content if final_content is not None else "",
                        embeds=parsed_embeds,
                        files=files,
                        allowed_mentions=allowed_mentions,
                        username=(
                            str(webhook_username)
                            if webhook_username
                            else discord.utils.MISSING
                        ),
                        avatar_url=(
                            effective_webhook_avatar_url
                            if effective_webhook_avatar_url
                            else discord.utils.MISSING
                        ),
                        thread_name=str(name),
                        applied_tags=(applied_tags or discord.utils.MISSING),
                        wait=True,
                    )  # type: ignore
                except discord.HTTPException as err:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "Failed to create forum post via webhook: "
                            f"{err.__class__.__name__}: {err.text or err}"
                        )
                    )

                if isinstance(msg.channel, discord.Thread):
                    await msg.channel.edit(
                        auto_archive_duration=auto_archive_duration,  # type: ignore
                        slowmode_delay=(
                            slowmode_delay.seconds
                            if slowmode_delay
                            else discord.utils.MISSING
                        ),
                    )
                continue

            await dest.create_thread(
                name=name,
                content=final_content,
                embeds=parsed_embeds,
                files=files,
                allowed_mentions=allowed_mentions,
                auto_archive_duration=auto_archive_duration,  # type: ignore
                slowmode_delay=slowmode_delay.seconds if slowmode_delay else None,
                applied_tags=(applied_tags or discord.utils.MISSING),
            )

    @commands.guild_only()
    @message.command(
        name="sendcontent",
        aliases=["createcontent", "sendtext", "createtext"],
        extras=dict(delete_invocation=True),
        usage="<content Text[2000]> [to: Channel] [reply_to: Message] "
        "[delete_after: Number/TimeDelta] [mention_all: yes|no] "
        "[mention_everyone: yes|no] [mention_users: yes|no] "
        "[mention_these_users: User...] [mention_roles: yes|no] "
        "[mention_these_roles: Role...] [mention_replied_user: yes|no]",
    )
    @flagconverter_kwargs()
    async def message_sendcontent(
        self,
        ctx: commands.Context[BotT],
        content: str,
        *,
        to: tuple[MessageableGuildChannel, ...] = (),
        reply_to: discord.PartialMessage | None = None,
        delete_after: float | TimeDelta | None = None,
        mention_all: bool = False,
        mention_everyone: bool = False,
        mention_users: bool = False,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool = False,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool = False,
    ):
        """Send a message with the specified text content to the invocation channel or a custom destination.

        __**Parameters:**__

        **`<content Text[2000]>`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[to: Channel]`**
        > A flag for the destination channel of The URL of the message to send.
        > Defaults to the command invocation channel.

        **`[reply_to: Message]`**
        > A flag for The URL of the message to use as a reference.

        **`[delete_after: Number/TimeDelta]`**
        > A flag to set a deletion timeout for the message upon its creation.

        **`[mention_all: yes|no]`**
        > A flag for whether all mentionable targets in the message text content (users, roles, user being replied to) should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_everyone: yes|no]`**
        > A flag for whether @everyone should be mentioned.

        **`[mention_users: yes|no]`**
        > A flag for whether any mentioned users in the message text content should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_these_users: User...]`**
        > A flag for a sequence of users in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_users:` flag.

        **`[mention_roles: yes|no]`**
        > A flag for whether any mentioned roles in the message text content should receive a mention ping.
        > Can be either 'yes' or 'no', or a sequence of roles to ping.
        > Defaults to 'no'.

        **`[mention_these_roles: Role...]`**
        > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        destinations = to or (ctx.channel,)

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author, destinations, "view_channel"
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    "target channel(s) "
                    f"({', '.join(f'<#{dest.id}>' for dest in destinations)})."
                )
            )

        allowed_mentions = self._build_allowed_mentions(
            mention_all,
            mention_everyone,
            mention_users,
            mention_these_users,
            mention_roles,
            mention_these_roles,
            mention_replied_user,
        )
        delete_after_seconds = (
            delete_after.total_seconds()
            if isinstance(delete_after, datetime.timedelta)
            else delete_after
        )

        for dest in destinations:
            msg = await (
                reply_to.reply(content=content, allowed_mentions=allowed_mentions)
                if reply_to
                else dest.send(content=content, allowed_mentions=allowed_mentions)
            )
            if delete_after_seconds:
                await msg.delete(delay=delete_after_seconds)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="edit",
        usage="[attachments 'upload files < 8 MiB']... <message Message> "
        "[message_src: Message] [content_src: Message] [content: Text[2000]] "
        "[attachments_src: Message] [attachment_src: Message Number]... "
        "[embeds_src: Message] [embed_src: Message Number]... "
        "[embeds: CodeBlock/Message/( Message Integer ) ... ] "
        "[tags: String[20]...] "
        "[auto_hide_duration: 1h|24h|1d|3d|1w] [slowmode_delay: TimeDelta] "
        "[webhook_name: Text[80]] [webhook_url: Text] "
        "[webhook_username: Text[80]] [webhook_avatar_url: Text] "
        "[webhook_no_avatar: yes|no] "
        "[mention_everyone: yes|no] [mention_users: yes|no] "
        "[mention_these_users: User...] [mention_roles: yes|no] "
        "[mention_these_roles: Role...] [mention_replied_user: yes|no]",
        extras=dict(delete_invocation=True),
    )
    @flagconverter_kwargs()
    async def message_edit(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message | ReferencedMessage,
        attachments: commands.Greedy[discord.Attachment],
        *,
        name: String[100]
        | None = commands.flag(name="name", aliases=["title"], default=None),
        message_src: discord.Message | ReferencedMessage | None = None,
        content_src: discord.Message | ReferencedMessage | None = None,
        content: String | None = None,
        attachments_src: discord.Message | ReferencedMessage | None = None,
        attachment_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds_src: discord.Message | ReferencedMessage | None = None,
        embed_src: list[tuple[discord.Message | ReferencedMessage, int]] = [],
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        tags: tuple[str, ...] = (),
        auto_hide_duration: (
            Literal["1h", "24h", "1d", "3d", "1w"] | None
        ) = commands.flag(aliases=["auto_archive_duration"], default=None),
        slowmode_delay: TimeDelta = datetime.timedelta(),
        remove_content: bool = False,
        remove_embeds: bool = False,
        remove_all_attachments: bool = False,
        remove_old_attachments: bool = False,
        webhook_name: String[80] | None = None,
        webhook_url: StringExpr[HTTP_URL] | None = None,
        webhook_username: String[80] | None = None,
        webhook_avatar_url: StringExpr[HTTP_URL] | None = None,
        webhook_no_avatar: bool = False,
        mention_all: bool | None = None,
        mention_everyone: bool | None = None,
        mention_users: bool | None = None,
        mention_these_users: tuple[discord.User, ...] = (),
        mention_roles: bool | None = None,
        mention_these_roles: tuple[discord.Role, ...] = (),
        mention_replied_user: bool | None = None,
    ):
        """Edit a previously sent message.

        __**Parameters:**__

        **`<message Message>`**
        > The URL of the message to edit.

        **`[attachments 'upload files < 8 MiB']...`**
        > One or more new attachments to add to the message.
        > They must not exceed 8 MiB in size.

        **`<name|title: Text[100]>`**
        > A flag for the thread or forum post name/title.
        > It must not exceed 100 characters in length.

        **`[message_src: Message]`**
        > A flag for using content, embeds, and attachments from another message.
        > Explicit flags override the corresponding parts from this source.

        **`[content_src: Message]`**
        > A flag for using the text content from another message.
        > The source message must contain text content.

        **`[content: Text[2000]]`**
        > A flag for the text content the edited message should contain.
        > It must not exceed 2000 characters in length.

        **`[attachments_src: Message]`**
        > A flag for using all attachments from another message.
        > The source message must contain attachments.

        **`[attachment_src: Message Number]...`**
        > A flag for using one attachment from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds_src: Message]`**
        > A flag for using all embeds from another message.
        > The source message must contain embeds.

        **`[embed_src: Message Number]...`**
        > A flag for using one embed from a message by 0-based index.
        > Can be specified multiple times.

        **`[embeds: CodeBlock/Message/( Message Integer ) ... ]`**
        > A flag for the embeds to add to the message, as 1-10 of these:
        > • Code blocks containing embed data as a JSON object/Python dictionary
        > • A message containing embed data as a JSON object/Python dictionary in its first attachment
        > • A parenthesized pair containing a message containing embed data as a JSON object/Python dictionary in its first attachment, followed by an index (0-9) representing the attachment position.
        >
        > If any of these arguments evaluate to an empty dictionary/JSON object ( `{}` ), the preexisting embeds at their position will be preserved.

        **`[tags: String[20]...]`**
        > The tags to apply to the message's post, if applicable and they exist.

        **`[auto_hide_duration: 1h|24h|1d|3d|1w]`**
        > The duration after which to hide threads or posts from the channel sidebar.
        > Omission leads to the default parent channel value being used.

        **`[slowmode_delay: TimeDelta]`**
        > The slowmode delay to use. Omission disables slowmode.

        **`[remove_content: yes|no]`**
        > A flag for whether to clear the message's text content.

        **`[webhook_name: Text[80]]`**
        > A flag for enabling webhook mode when editing messages.
        > If webhook mode is enabled and `webhook_url:` is omitted, `{bot_name} Messaging` is used.

        **`[webhook_url: Text]`**
        > A flag for enabling webhook mode with a pre-existing webhook URL for edits.

        **`[webhook_username: Text[80]]`**
        > A flag for updating the webhook display name before editing the message.

        **`[webhook_avatar_url: Text]`**
        > A flag for updating the webhook display avatar before editing the message.

        **`[webhook_no_avatar: yes|no]`**
        > A flag for disabling webhook avatars while editing.
        > This overrides `webhook_avatar_url:` when set to 'yes'.

        **`[mention_all: yes|no]`**
        > A flag for whether all mentionable targets in the message text content (users, roles, user being replied to) should receive a mention ping.
        > Defaults to 'no'.

        **`[mention_everyone: yes|no]`**
        > A flag for whether @everyone should be marked as mentioned.

        **`[mention_users: yes|no]`**
        > A flag for whether any mentioned users in the message text content should receive a mention ping.

        **`[mention_these_users: User...]`**
        > A flag for a sequence of users in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_users:` flag.

        **`[mention_roles: yes|no]`**
        > A flag for whether any mentioned roles in the message text content should receive a mention ping.

        **`[mention_these_roles: Role...]`**
        > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        return await self.message_edit_func(
            ctx,
            message,
            attachments,
            name=name,
            message_src=message_src,
            content_src=content_src,
            content=content,
            attachments_src=attachments_src,
            attachment_src=attachment_src,
            embeds_src=embeds_src,
            embed_src=embed_src,
            embeds=embeds,
            tags=tags,
            auto_hide_duration=auto_hide_duration,
            slowmode_delay=slowmode_delay,
            remove_content=remove_content,
            remove_embeds=remove_embeds,
            remove_all_attachments=remove_all_attachments,
            remove_old_attachments=remove_old_attachments,
            webhook_name=webhook_name,
            webhook_url=webhook_url,
            webhook_username=webhook_username,
            webhook_avatar_url=webhook_avatar_url,
            webhook_no_avatar=webhook_no_avatar,
            mention_all=mention_all,
            mention_everyone=mention_everyone,
            mention_users=mention_users,
            mention_these_users=mention_these_users,
            mention_roles=mention_roles,
            mention_these_roles=mention_these_roles,
            mention_replied_user=mention_replied_user,
        )

    @commands.guild_only()
    @message.command(
        name="editcontent",
        aliases=["edittext"],
        usage="<message> <content (Text[2000])>",
        extras=dict(delete_invocation=True),
    )
    async def message_editcontent(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message | ReferencedMessage,
        content: String[2000],
    ):
        """Edit an existing message with new text content.

        __**Parameters:**__

        **`<message>`**
        > The URL of the message to edit.

        **`<content (Text[2000])>`**
        > The text content to edit the message with.
        > It must not exceed 2000 characters in length.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not message:
            raise commands.CommandInvokeError(
                commands.BadArgument(
                    "'message' is a required argument that is missing."
                )
            )
        elif not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            raise commands.CommandInvokeError(
                commands.BadArgument("Can only edit messages within a guild.")
            )

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            message.channel,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"target channel(s) (<#{message.channel.id}>)."
                )
            )

        await message.edit(content=content)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="extract",
        usage="<message Message>... [to: Channel] [content: yes|no] "
        "[content_attachment: yes|no] [attachments: yes|no] [embeds: yes|no] "
        "[info: yes|no] [author_info: yes|no]",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_extract(
        self,
        ctx: commands.Context[BotT],
        *message: discord.Message | ReferencedMessage,
        to: MessageableGuildChannel | None = None,
        content: bool = True,
        content_attachment: bool = False,
        attachments: bool = True,
        embeds: bool = True,
        info: bool = False,
        author_info: bool = True,
    ):
        """Extract the parts of a Discord message and send them in an accessible form.
        Message components in action rows are ignored.

        __**Parameters:**__

        **`<message Message>...`**
        > The messages to extract parts from.

        **`[to: Channel]`**
        > A flag for the channel to send the extracted parts to.
        > Defaults to the invocation channel.

        **`[content: yes|no]`**
        > A flag for whether to extract message content, in the form of an embed containing a code block.
        > Defaults to 'yes'.

        **`[content_attachment: yes|no]`**
        > A flag for whether to extract message content, in the form of a text attachment.
        > This flag overrides the `content:` flag if set to 'yes'.
        > Defaults to 'no'.

        **`[attachments: yes|no]`**
        > A flag for whether to extract message attachments.
        > Defaults to 'yes'.

        **`[embeds: yes|no]`**
        > A flag for whether to extract message embeds as JSON files.
        > Defaults to 'yes'.

        **`[info: yes|no]`**
        > A flag for whether to send an informational embed containing details about a message.
        > If set to 'no', this flag will supress the `author_info:` flag.
        > Defaults to 'no'.

        **`[author_info: yes|no]`**
        > A flag for whether to send an informational embed containing details about a message author.
        > Defaults to 'yes'.

        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        messages = message
        destination = to or ctx.channel

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            (ctx.channel, destination),
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"specified destination(s) (<#{ctx.channel.id}>, "
                    f"<#{destination.id}>).",
                )
            )

        checked_channels = set()
        for i, msg in enumerate(messages):
            if msg and msg.channel not in checked_channels:
                if not snakecore.utils.have_permissions_in_channels(
                    ctx.author,
                    msg.channel,  # type: ignore
                    "view_channel",
                ):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "You do not have enough permissions to run this command on the "
                            f"target channel(s) (<#{msg.channel.id}>)."
                        )
                    )
                else:
                    checked_channels.add(msg.channel)

            if not i % 50:
                await asyncio.sleep(0)

        if not all(messages):
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )

        for i, msg in enumerate(messages):
            assert msg
            escaped_msg_content = msg.content.replace("```", "\\`\\`\\`")
            attached_files = None
            if attachments:
                filesize_limit = 2**20 * 8  # 8 MiB
                with io.BytesIO(
                    "This file could not be duplicated due to the "
                    "message file limit of 8 MiB being exceeded.".encode("utf-8")
                ) as bytesio:
                    cum_size = 0
                    attached_files = [
                        (
                            await a.to_file(spoiler=a.is_spoiler())
                            if (cum_size := cum_size + a.size) <= filesize_limit
                            else discord.File(
                                bytesio, f"filetoolarge - {a.filename}.txt"
                            )
                        )
                        for a in msg.attachments
                    ]

            if info:
                info_embed = get_msg_info_embed(msg, author_info)
                info_embed.author.name = "Message data & info"
                info_embed.title = ""
                info_embed.color = int(self.theme_color)

                info_embed.description = "".join(
                    (
                        "__Text"
                        + (" (Shortened)" if len(escaped_msg_content) > 2000 else "")
                        + "__:",
                        (
                            f"\n\n ```\n{escaped_msg_content[:2001]}\n\n[...]\n```"
                            + "\n\u200b"
                            if len(escaped_msg_content) > 2000
                            else "\n\u200b"
                        ),
                    )
                )

                content_file = None
                if content_attachment or len(msg.content) > 2000:
                    with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                        content_file = discord.File(bytesio, "messagedata.txt")

                    await destination.send(embed=info_embed, file=content_file)
                else:
                    await destination.send(embed=info_embed)

            elif content_attachment and msg.content:
                with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                    await destination.send(
                        file=discord.File(bytesio, "messagedata.txt"),
                        embed=discord.Embed.from_dict(
                            dict(
                                author=dict(name="Message Data"),
                                color=int(self.theme_color),
                                description=f"**[View original message]({msg.jump_url})**",
                            )
                        ),
                    )
            elif content:
                if len(msg.content) > 2000 or len(escaped_msg_content) > 2000:
                    with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                        await destination.send(
                            file=discord.File(bytesio, "messagedata.txt"),
                            embed=discord.Embed.from_dict(
                                dict(
                                    author=dict(name="Message Data"),
                                    color=int(self.theme_color),
                                    description=f"**[View original message]({msg.jump_url})**",
                                )
                            ),
                        )
                elif escaped_msg_content:
                    await destination.send(
                        embed=discord.Embed.from_dict(
                            dict(
                                author=dict(name="Message Data"),
                                description="```\n{0}```".format(escaped_msg_content),
                                fields=[
                                    dict(
                                        name="\u200b",
                                        value=f"**[View original message]({msg.jump_url})**",
                                        inline=False,
                                    ),  # type: ignore
                                ],
                            )
                        )
                    )

            if attached_files:
                for i in range(len(attached_files)):
                    await ctx.send(
                        content=f"**Message attachments** ({i + 1}):",
                        files=attached_files,
                    )

            if embeds and msg.embeds:
                embed_data_bytesios = []
                for embed in msg.embeds:
                    embed_data_bytesio = io.BytesIO(
                        json.dumps(embed.to_dict(), indent=4).encode("utf-8")
                    )
                    embed_data_bytesio.seek(0)
                    embed_data_bytesios.append(embed_data_bytesio)

                await ctx.send(
                    content=f"**Message embeds** ({len(embed_data_bytesios)}):",
                    files=[
                        discord.File(bytesio, filename=f"embeddata{i}.json")
                        for i, bytesio in enumerate(embed_data_bytesios)
                    ],
                )

                for embed_data_bytesio in embed_data_bytesios:
                    embed_data_bytesio.close()

            await asyncio.sleep(0)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="clone",
        usage="<message Message>... [to: Channel] [embeds: yes|no] [attachments: yes|no] "
        "[as_spoiler: yes|no] [info: yes|no] [author_info: yes|no] [skip_empty: yes|no]",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_clone(
        self,
        ctx: commands.Context[BotT],
        *message: discord.Message | ReferencedMessage,
        to: tuple[MessageableGuildChannel, ...] = (),
        content: bool = True,
        embeds: bool = True,
        attachments: bool = True,
        as_spoiler: bool | None = None,
        info: bool = False,
        author_info: bool = True,
        skip_empty: bool = True,
    ):
        """Clone the specified messages with all or some of their parts included.
        Message components in action rows are ignored.

        __**Parameters:**__

        **`<message Message>...`**
        > The messages to clone.

        **`[to: Channel]`**
        > A flag for the channel to send the cloned messages to.
        > Defaults to the invocation channel.

        **`[content: yes|no]`**
        > A flag for whether to include message content in the cloned messages.
        > Defaults to 'yes'.

        **`[attachments: yes|no]`**
        > A flag for whether to incude message attachments in the cloned messages.
        > Defaults to 'yes'.

        **`[embeds: yes|no]`**
        > A flag for whether to include message embeds in the cloned messages.
        > Defaults to 'yes'.

        **`[info: yes|no]`**
        > A flag for whether to send an informational embed containing details about a message.
        > If set to 'no', this flag will supress the `author_info:` flag.
        > Defaults to 'no'.

        **`[author_info: yes|no]`**
        > A flag for whether to send an informational embed containing details about a message author.
        > Defaults to 'yes'.

        **`[skip_empty: yes|no]`**
        > A flag for whether to automatically ignore messages without content, embeds or attachments.
        > Defaults to 'yes'.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        messages = message
        destinations = to or (ctx.channel,)

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            destinations,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    "target channel(s) "
                    f"({', '.join(f'<#{dest.id}>' for dest in destinations)})."
                )
            )

        checked_channels = set()
        for i, msg in enumerate(messages):
            if msg.channel not in checked_channels:
                if not snakecore.utils.have_permissions_in_channels(
                    ctx.author,
                    msg.channel,  # type: ignore
                    "view_channel",
                ):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "You do not have enough permissions to run this command on the "
                            f"target channel(s) (<#{msg.channel.id}>)."
                        )
                    )
                else:
                    checked_channels.add(msg.channel)

            if not i % 50:
                await asyncio.sleep(0)

        if not messages:
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )

        no_mentions = discord.AllowedMentions.none()
        first_cloned_msg = None
        for i, msg in enumerate(messages):
            attached_files = []
            if msg.attachments and attachments:
                filesize_limit = 2**20 * 8  # 8 MiB
                with io.BytesIO(
                    b"This file could not be duplicated due to the "
                    b"message file limit of 8 MiB being exceeded."
                ) as bytesio:
                    cum_size = 0
                    attached_files = [
                        (
                            await a.to_file(
                                spoiler=(
                                    as_spoiler
                                    if as_spoiler is not None
                                    else a.is_spoiler()
                                )
                            )
                            if (cum_size := cum_size + a.size) <= filesize_limit
                            else discord.File(
                                bytesio, f"filetoolarge - {a.filename}.txt"
                            )
                        )
                        for a in msg.attachments
                    ]
            for destination in destinations:
                if (content or embeds or attachments) and (
                    msg.content or msg.embeds or attached_files
                ):
                    if len(msg.content) > 2000:
                        start_idx = 0
                        stop_idx = 0
                        for i in range(len(msg.content) // 2000):
                            start_idx = 2000 * i
                            stop_idx = 2000 + 2000 * i

                            if not i:
                                first_cloned_msg = await destination.send(
                                    content=msg.content[start_idx:stop_idx],
                                    allowed_mentions=no_mentions,
                                )
                            else:
                                await destination.send(
                                    content=msg.content[start_idx:stop_idx],
                                    allowed_mentions=no_mentions,
                                )

                        with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                            await destination.send(
                                content=msg.content[stop_idx:],
                                embed=discord.Embed.from_dict(
                                    dict(
                                        color=int(self.theme_color),
                                        footer=dict(text="Full message data"),
                                    )
                                ),
                                file=discord.File(bytesio, filename="messagedata.txt"),
                                allowed_mentions=no_mentions,
                            )
                        await destination.send(
                            content=msg.content if content else None,
                            embeds=msg.embeds if embeds else None,  # type: ignore
                            files=attached_files if attachments else None,  # type: ignore
                        )
                    else:
                        first_cloned_msg = await destination.send(
                            content=msg.content if content else None,
                            embeds=msg.embeds if embeds else None,  # type: ignore
                            files=attached_files if attachments else None,  # type: ignore
                            allowed_mentions=no_mentions,
                        )

                elif (
                    not (msg.content or msg.embeds or attached_files) and not skip_empty
                ):
                    raise commands.CommandInvokeError(
                        commands.CommandError("Cannot clone an empty message")
                    )

                if info:
                    info_embed = get_msg_info_embed(msg, author=author_info)
                    info_embed.color = int(self.theme_color)

                    if first_cloned_msg:
                        await ctx.send(
                            embed=info_embed,
                            reference=first_cloned_msg,
                        )
                    else:
                        await ctx.send(embed=info_embed)

                await asyncio.sleep(0)

    @commands.guild_only()
    @message.command(name="archive", extras=dict(response_deletion_with_reaction=True))
    @flagconverter_kwargs()
    async def message_archive(
        self,
        ctx: commands.Context[BotT],
        origin: MessageableGuildChannel,
        quantity: int | None = None,
        *,
        mode: int = 0,
        to: MessageableGuildChannel | None = None,
        before: discord.PartialMessage | datetime.datetime | None = None,
        after: discord.PartialMessage | datetime.datetime | None = None,
        around: discord.PartialMessage | datetime.datetime | None = None,
        raw: bool = False,
        show_header: bool = True,
        show_author: bool = True,
        divider: String = "-" * 56,  # type: ignore
        group_by_author: bool = True,
        group_by_author_timedelta: float = 600.0,
        message_links: bool = True,
        oldest_first: bool = True,
        same_channel: bool = False,
    ):
        """Archive messages from a channel in an accessible format."""
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        destination = to or ctx.channel

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            (origin, destination),
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"specified destination(s) (<#{origin.id}>, "
                    f"<#{destination.id}>).",
                )
            )

        archive_header_msg = None
        archive_header_msg_embed = None

        if origin.id == destination.id and not same_channel:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Cannot execute command:",
                    "Origin and destination channels are same",
                )
            )

        divider_str = divider

        if (
            isinstance(before, discord.PartialMessage)
            and before.channel.id != origin.id
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "`before` has to be an ID to a message from the origin channel",
                )
            )

        if isinstance(after, discord.PartialMessage) and after.channel.id != origin.id:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "`after` has to be an ID to a message from the origin channel",
                )
            )

        if (
            isinstance(around, discord.PartialMessage)
            and around.channel.id != origin.id
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "`around` has to be an ID to a message from the origin channel",
                )
            )

        quantity = quantity or 0

        if quantity <= 0:
            if quantity == 0 and not after:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "`quantity` must be above 0 when `after` is not specified.",
                    )
                )
            elif quantity != 0:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "`quantity` has to be a positive integer (or `0` when `after` is specified).",
                    )
                )

        await destination.typing()
        messages = [
            msg
            async for msg in origin.history(
                limit=quantity if quantity != 0 else None,
                before=before,
                after=after,
                around=around,
            )
        ]

        message_id_cache = {}

        if not messages:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Invalid time range",
                    "No messages were found for the specified timestamps.",
                )
            )

        if not after and oldest_first:
            messages.reverse()

        if show_header and not raw:
            start_date = messages[0].created_at
            end_date = messages[-1].created_at

            if start_date == end_date:
                header_fields = (
                    {
                        "name": f"On: {snakecore.utils.create_markdown_timestamp(start_date)}",
                        "value": "\u200b",
                        "inline": True,
                    },
                )
            else:
                header_fields = (
                    {
                        "name": f"From: {snakecore.utils.create_markdown_timestamp(start_date)}",
                        "value": "\u200b",
                        "inline": True,
                    },
                    {
                        "name": f"To: {snakecore.utils.create_markdown_timestamp(end_date)}",
                        "value": "\u200b",
                        "inline": True,
                    },
                )

            archive_header_msg_embed = discord.Embed.from_dict(
                dict(
                    title=f"__Archive of `#{origin.name}`__",
                    description=f"\nAn archive of **{origin.mention}**"
                    f"({len(messages)} message(s))\n\u200b",
                    fields=header_fields,  # type: ignore
                    color=0xFFFFFF,
                    footer=dict(text="Status: Incomplete"),
                )
            )
            archive_header_msg = await destination.send(embed=archive_header_msg_embed)

        no_mentions = discord.AllowedMentions.none()

        load_embed = discord.Embed.from_dict(
            dict(
                title="Your command is being processed:",
                color=int(self.theme_color),
                fields=[dict(name="\u200b", value="`...`", inline=False)],
            )
        )
        message_count = len(messages)
        with io.BytesIO(b"This file was too large to be archived.") as bytesio:
            msg: discord.Message
            for i, msg in enumerate(
                reversed(messages) if not oldest_first else messages
            ):
                if message_count > 2 and not i % 2:
                    await self.send_or_edit_response(
                        ctx,
                        embed=load_embed.set_field_at(
                            0,
                            name="Archiving Messages",
                            value=f"`{i}/{message_count}` messages archived\n"
                            f"{(i / message_count) * 100:.01f}% | "
                            + snakecore.utils.progress_bar(
                                i / message_count, divisions=30
                            ),
                        ),
                    )

                author = msg.author
                msg_reference_id = None
                if msg.reference and not isinstance(
                    msg.reference, discord.DeletedReferencedMessage
                ):
                    msg_reference_id = message_id_cache.get(msg.reference.message_id)

                await destination.typing()

                bytesio.seek(0)

                filesize_limit = 2**20 * 8  # 8 MiB

                cum_size = 0
                attached_files = [
                    (
                        await a.to_file(spoiler=a.is_spoiler())
                        if (cum_size := cum_size + a.size) <= filesize_limit
                        else discord.File(bytesio, f"filetoolarge - {a.filename}.txt")
                    )
                    for a in msg.attachments
                ]

                if not raw:
                    author_embed = None
                    current_divider_str = divider_str
                    if show_author or divider_str:
                        if (
                            group_by_author
                            and i > 0
                            and messages[i - 1].author == author
                            and (
                                msg.created_at - messages[i - 1].created_at
                            ).total_seconds()
                            < group_by_author_timedelta
                        ):
                            # no author info or divider for messages next to
                            # each other sharing an author
                            current_divider_str = None
                        else:
                            shorten = i > 0 and messages[i - 1].author == author
                            if shorten:
                                shorten_style = (
                                    "t"
                                    if messages[i - 1].created_at.day
                                    == msg.created_at.day
                                    else "f"
                                )
                                description_str = (
                                    f"{snakecore.utils.create_markdown_timestamp(msg.created_at, tformat=shorten_style)}"
                                    + (
                                        f" [View]({msg.jump_url})"
                                        if message_links
                                        else ""
                                    )
                                )
                            else:
                                description_str = (
                                    f"{author.mention}"
                                    f" {snakecore.utils.create_markdown_timestamp(msg.created_at)}"
                                    + (
                                        f" [View]({msg.jump_url})"
                                        if message_links
                                        else ""
                                    )
                                )

                            author_embed = discord.Embed.from_dict(
                                dict(
                                    description=description_str,
                                    color=0x36393F,
                                    author=dict(
                                        name=f"{author.name}#{author.discriminator}",
                                        icon_url=author.display_avatar.url,
                                    ),
                                )
                            )

                        if author_embed or current_divider_str:
                            await destination.send(
                                content=current_divider_str,
                                embed=author_embed,  # type: ignore
                                allowed_mentions=no_mentions,
                            )

                if not mode:
                    if msg.content or msg.embeds or attached_files:
                        msg_embeds = [
                            embed
                            for embed in msg.embeds
                            if embed.to_dict().get("type") != "gifv"
                        ]
                        if len(msg.content) > 2000:
                            start_idx = 0
                            stop_idx = 0
                            for i in range(len(msg.content) // 2000):
                                start_idx = 2000 * i
                                stop_idx = 2000 + 2000 * i

                                if not i:
                                    message_id_cache[msg.id] = await destination.send(
                                        content=msg.content[start_idx:stop_idx],
                                        allowed_mentions=no_mentions,
                                        reference=msg_reference_id,  # type: ignore
                                    )
                                else:
                                    await destination.send(
                                        content=msg.content[start_idx:stop_idx],
                                        allowed_mentions=no_mentions,
                                    )

                            with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                                await destination.send(
                                    content=msg.content[stop_idx:],
                                    embed=discord.Embed.from_dict(
                                        dict(
                                            color=int(self.theme_color),
                                            footer=dict(text="Full message data"),
                                        )
                                    ),
                                    file=discord.File(
                                        bytesio, filename="messagedata.txt"
                                    ),
                                    allowed_mentions=no_mentions,
                                )

                            await destination.send(
                                embeds=msg_embeds,
                                files=attached_files,
                            )
                        else:
                            message_id_cache[msg.id] = await destination.send(
                                content=msg.content,
                                embeds=msg_embeds,
                                files=attached_files,
                                allowed_mentions=no_mentions,
                                reference=msg_reference_id,  # type: ignore
                            )

                    elif msg.type != discord.MessageType.default:
                        await destination.send(
                            embed=discord.Embed(
                                description=msg.system_content, color=0x36393F
                            )
                        )

                    if len(attached_files) > 1:
                        for i in range(1, len(attached_files)):
                            await destination.send(
                                content=f"**Message attachment** ({i + 1}):",
                                file=attached_files[i],
                            )

                    for i in range(1, len(msg.embeds)):
                        if not i % 3:
                            await destination.typing()
                        await destination.send(embed=msg.embeds[i])

                elif mode in (1, 2):
                    if mode == 1:
                        if msg.content:
                            escaped_msg_content = msg.content.replace(
                                "```", "\\`\\`\\`"
                            )
                            if (
                                len(msg.content) > 2000
                                or len(escaped_msg_content) + 7 > 2000
                            ):
                                with io.BytesIO(msg.content.encode("utf-8")) as bytesio:
                                    message_id_cache[msg.id] = await destination.send(
                                        file=discord.File(bytesio, "messagedata.txt"),
                                        reference=msg_reference_id,  # type: ignore
                                    )
                            else:
                                message_id_cache[msg.id] = await destination.send(
                                    embed=discord.Embed(
                                        description=f"```\n{escaped_msg_content}```",
                                        color=0x36393F,
                                    ),
                                    reference=msg_reference_id,  # type: ignore
                                )

                        if attached_files:
                            for i in range(len(attached_files)):
                                await destination.send(
                                    content=f"**Message attachment** ({i + 1}):",
                                    file=attached_files[i],
                                )
                    else:
                        if msg.content:
                            with io.BytesIO(msg.content.encode("utf-8")) as bytesio2:
                                message_id_cache[msg.id] = await destination.send(
                                    file=discord.File(
                                        bytesio2,
                                        filename="messagedata.txt",
                                    ),
                                    allowed_mentions=no_mentions,
                                    reference=msg_reference_id,  # type: ignore
                                )

                        if attached_files:
                            for i in range(len(attached_files)):
                                await destination.send(
                                    content=f"**Message attachment** ({i + 1}):",
                                    file=attached_files[i],
                                )

                    if msg.embeds:
                        embed_data_bytesios: list[io.BytesIO] = []
                        for embed in msg.embeds:
                            embed_data_bytesio = io.BytesIO(
                                json.dumps(embed.to_dict()).encode("utf-8")
                            )
                            embed_data_bytesio.seek(0)
                            embed_data_bytesios.append(embed_data_bytesio)

                        await destination.send(
                            content=f"**Message embeds** ({i + 1}):",
                            files=[
                                discord.File(bytesio, filename=f"embeddata{i}.json")
                                for bytesio in embed_data_bytesios
                            ],
                        )

                        for embed_data_bytesio in embed_data_bytesios:
                            embed_data_bytesio.close()

                await asyncio.sleep(0)

        if divider_str and not raw:
            await destination.send(content=divider_str)

        if show_header and not raw:
            archive_header_msg_embed.set_footer(text="Status: Complete")  # type: ignore
            if archive_header_msg is not None:
                await archive_header_msg.edit(embed=archive_header_msg_embed)

        await self.send_or_edit_response(
            ctx,
            embed=load_embed.set_field_at(
                0,
                name=f"Successfully archived {message_count} message(s)",
                value=f"`{message_count}/{message_count}` messages archived\n"
                "100% | " + snakecore.utils.progress_bar(1.0, divisions=30),
            ),
        )

    @commands.guild_only()
    @message.group(
        name="pin",
        usage="<message Message>... [delete_system_message: yes|no] [unpin_last: yes|no]",
        invoke_without_command=True,
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_pin(
        self,
        ctx: commands.Context[BotT],
        *message: discord.PartialMessage | ReferencedMessage,
        delete_system_message: bool = False,
        unpin_last: bool = False,
        _channel: MessageableGuildChannel | None = None,
    ):
        """Pin the specified messages.

        __**Parameters:**__

        **`<message Message>...`**
        > The messages to pin.

        **`[delete_system_message: yes|no]`**
        > A flag for whether any system messages about pinning should be automatically deleted.
        > Defaults to 'no'.

        **`[unpin_last: yes|no]`**
        > Whether to unpin the least recently pinned message(s) if the maximum pin limit of 50 is being approached.
        > Defaults to 'no'.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        messages = message
        channel = _channel or ctx.channel

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            channel,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"target channel(s) (<#{channel.id}>)."  # type: ignore
                )
            )

        if isinstance(channel, discord.VoiceChannel):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Message pinning is not possible within voice channels."
                )
            )

        if not messages:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No message IDs given as input.",
                )
            )
        elif len(messages) > 50:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Cannot pin more than 50 messages in a channel at a time.",
                )
            )

        elif not all(msg.channel.id == channel.id for msg in messages):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "All specified messages must originate from the given channel "
                    f"(<#{channel.id}>).",
                )
            )

        pinned_msgs = await channel.pins()

        unpin_count = max((len(pinned_msgs) + len(messages)) - 50, 0)
        if unpin_count > 0:
            if unpin_last:
                for i in range(unpin_count):
                    await pinned_msgs[i].unpin()
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Cannot pin messages: The maximum pins limit of 50 would be "
                        "reached (specify `unpin_last: yes` to unpin least recently "
                        "pinned messages)"
                    )
                )

        load_embed = discord.Embed.from_dict(
            dict(
                title="Your command is being processed:",
                color=int(self.theme_color),
                fields=[dict(name="\u200b", value="`...`", inline=False)],
            )
        )
        message_count = len(messages)

        def system_message_check(m):
            return m.channel.id == channel.id and m.type == discord.MessageType.pins_add

        for i, msg in enumerate(messages):
            if message_count > 2 and not i % 3:
                await self.send_or_edit_response(
                    ctx,
                    embed=load_embed.set_field_at(
                        0,
                        name="Processing Messages",
                        value=f"`{i}/{message_count}` messages processed\n"
                        f"{(i / message_count) * 100:.01f}% | "
                        + snakecore.utils.progress_bar(i / message_count, divisions=30),
                    ),
                )

            await msg.pin()
            if delete_system_message:
                try:
                    system_message: discord.Message = await ctx.bot.wait_for(
                        "message", check=system_message_check, timeout=0.5
                    )
                except asyncio.TimeoutError:
                    pass
                else:
                    await system_message.delete()

            await asyncio.sleep(0)

        if message_count > 2:
            await self.send_or_edit_response(
                ctx,
                embed=load_embed.set_field_at(
                    0,
                    name=f"Sucessfully pinned {message_count} message(s) ({unpin_count} removed)",
                    value=f"`{message_count}/{message_count}` messages pinned\n"
                    "100% | " + snakecore.utils.progress_bar(1.0, divisions=30),
                ),
            )

    @commands.guild_only()
    @message_pin.command(
        name="in",
        usage="<message Message>... [channel: TextChannel/Thread] [delete_system_message: yes|no] [unpin_last: yes|no]",
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def message_pin_in(
        self,
        ctx: commands.Context[BotT],
        channel: MessageableGuildChannel | None = None,
        *message: discord.PartialMessage,
        delete_system_message: bool = False,
        unpin_last: bool = True,
    ):
        """Pin the specified messages inside the specified channel.

        __**Parameters:**__

        **`<message Message>...`**
        > The messages to pin.

        **`[channel: TextChannel/Thread]`**
        > A flag for the channel the messages are contained in.
        > Defaults to the invocation channel.

        **`[delete_system_message: yes|no]`**
        > A flag for whether any system messages about pinning should be automatically deleted.
        > Defaults to 'no'.

        **`[unpin_last: yes|no]`**
        > Whether to unpin the least recently pinned message(s) if the maximum pin limit of 50 is being approached.
        > Defaults to 'no'.
        """
        await self.message_pin(
            ctx,
            message,  # type: ignore
            delete_system_message=delete_system_message,
            unpin_last=unpin_last,
            _channel=channel,
        )

    @commands.guild_only()
    @message.group(
        name="unpin",
        usage="<message Message>...",
        invoke_without_command=True,
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    async def message_unpin(
        self,
        ctx: commands.Context[BotT],
        *message: discord.PartialMessage | ReferencedMessage,
        _channel: MessageableGuildChannel | None = None,
    ):
        """Unpin the specified messages.

        __**Parameters:**__

        **`<message Message>...`**
        > The messages to unpin.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and ctx.guild.get_member(ctx.bot.user.id)
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        messages = message
        channel = _channel or ctx.channel

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            channel,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"target channel(s) (<#{channel.id}>)."  # type: ignore
                )
            )

        if isinstance(channel, discord.VoiceChannel):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Message unpinning is not possible within voice channels."
                )
            )

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            channel,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the specified channel."
                )
            )

        if not messages:
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )
        elif len(messages) > 50:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No more than 50 messages can be unpinned in a channel at a time."
                )
            )
        elif not all(msg.channel.id == channel.id for msg in messages):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "All specified messages must originate from the given channel "
                    f"(<#{channel.id}>).",
                )
            )

        pinned_msgs = await channel.pins()
        pinned_msg_id_set = set(msg.id for msg in pinned_msgs)

        load_embed = discord.Embed.from_dict(
            dict(
                title="Your command is being processed:",
                color=int(self.theme_color),
                fields=[dict(name="\u200b", value="`...`", inline=False)],
            )
        )

        message_count = len(messages)
        for i, msg in enumerate(messages):
            if message_count > 2 and not i % 3:
                await self.send_or_edit_response(
                    ctx,
                    embed=load_embed.set_field_at(
                        0,
                        name="Processing Messages",
                        value=f"`{i}/{message_count}` messages processed\n"
                        f"{(i / message_count) * 100:.01f}% | "
                        + snakecore.utils.progress_bar(i / message_count, divisions=30),
                    ),
                )

            if msg.id in pinned_msg_id_set:
                await msg.unpin()

            await asyncio.sleep(0)

        if message_count > 2:
            await self.send_or_edit_response(
                ctx,
                embed=load_embed.set_field_at(
                    0,
                    name=f"Succesfully unpinned {message_count} message(s)",
                    value=f"`{message_count}/{message_count}` messages processed\n"
                    "100% | " + snakecore.utils.progress_bar(1.0, divisions=30),
                ),
            )

    @commands.guild_only()
    @message_unpin.command(
        name="in",
        usage="<messages Message>... [channel: TextChannel/Thread]",
        extras=dict(response_deletion_with_reaction=True),
    )
    async def message_unpin_in(
        self,
        ctx: commands.Context[BotT],
        channel: MessageableGuildChannel | None = None,
        *messages: discord.PartialMessage,
    ):
        """Unpin the specified messages in the specified channel.

        __**Parameters:**__

        **`<messages Message>...`**
        > The URL of the messages to unpin.

        **`[channel: TextChannel/Thread]`**
        > The channel in which the messages are contained in.
        > Defaults to the invocation channel.
        """
        await self.message_unpin(ctx, *messages, _channel=channel)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: int | discord.Color = 0):
    await bot.add_cog(Messaging(bot, theme_color=color))
