"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from ast import literal_eval
import asyncio
import datetime
import io
import json

import discord
from discord.ext import commands
import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import CodeBlock, String, Parens, TimeDelta

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)


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
    async def message_send_func(
        self,
        ctx: commands.Context[BotT],
        attachments: commands.Greedy[discord.Attachment],
        *,
        content: String | None = None,
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
    ):
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not (content or attachments or embeds):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        destinations = to
        if not destinations:
            destinations = (ctx.channel,)

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

        parsed_embeds = []
        files = []

        if embeds:
            for i, code_block_or_msg in enumerate(embeds):
                if isinstance((code_block := code_block_or_msg), CodeBlock):
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
                elif isinstance(
                    (embed_msg := code_block_or_msg), (discord.Message, tuple)
                ):
                    attachment_index = 0
                    if isinstance(embed_msg, tuple):
                        embed_msg, attachment_index = (
                            embed_msg[0],
                            embed_msg[1],
                        )

                    if not (embed_msg_attachments := embed_msg.attachments):
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error with `embeds` argument {i}: Messages "
                                "speficied for flag `embeds` must have at least one "
                                "attachment as `.txt`, `.py` file containing a Python "
                                "dictionary, or a `.json` file containing embed data. "
                                "It must be less than 10KB in size.",
                            )
                        )

                    embed_attachment = embed_msg_attachments[
                        min(attachment_index, len(embed_msg_attachments))
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
                                "speficied for flag `embeds` must have at least one "
                                "attachment as `.txt`, `.py` file containing a Python "
                                "dictionary, or a `.json` file containing embed data. "
                                "It must be less than 10KB in size.",
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
                        except Exception as jerr:
                            raise commands.CommandInvokeError(
                                commands.CommandError(
                                    "Error while parsing embed JSON from attachment: "
                                    f"{i}: {jerr.__class__.__name__}: {jerr.args[0]}"
                                )
                            )
                    else:
                        try:
                            embed_dict = literal_eval(embed_data)
                        except Exception as perr:
                            raise commands.CommandInvokeError(
                                commands.CommandError(
                                    "Error while parsing Python embed dict from attachment: "
                                    f"{i}: {perr.__class__.__name__}: {perr.args[0]}"
                                )
                            )
                else:
                    continue

                parsed_embeds.append(discord.Embed.from_dict(embed_dict))

        if attachments:
            for i, att in enumerate(attachments):
                if att.size > 2**20 * 25:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Attachment {i} is too large to be resent (> 25MiB)"
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
                            users=(
                                mention_these_users
                                if mention_these_users
                                else mention_users
                            ),
                            roles=(
                                mention_these_roles
                                if mention_these_roles
                                else mention_roles
                            ),
                            replied_user=mention_replied_user,
                        )
                    ),
                    delete_after=(
                        delete_after.total_seconds()
                        if isinstance(delete_after, datetime.timedelta)
                        else delete_after
                    ),  # type: ignore
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
                            users=(
                                mention_these_users
                                if mention_these_users
                                else mention_users
                            ),
                            roles=(
                                mention_these_roles
                                if mention_these_roles
                                else mention_roles
                            ),
                            replied_user=mention_replied_user,
                        )
                    ),
                    delete_after=(
                        delete_after.total_seconds()
                        if isinstance(delete_after, datetime.timedelta)
                        else delete_after
                    ),  # type: ignore
                )
            )

    @commands.group(
        invoke_without_command=True,
        aliases=["msg"],
        usage="[attachments (upload files < 8 MiB)]... [content: Text[2000]] "
        "[embeds: CodeBlock...] [to: Channel] [reply_to: Message] "
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
        content: String[2000] | None = None,
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
    ):
        """Send a message to the invocation channel or a custom destination.

        __**Parameters:**__

        **`[attachments (upload files < (25 MiB))]...`**
        > One or more attachments to add to the message.

        **`[content: Text[2000]]`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[embeds: CodeBlock...]`**
        > A flag for the embeds to add to the message, as 1-10 code blocks containing embed data as a JSON object/Python dictionary.

        **`[to: Channel]`**
        > A flag for the destination channel of the message to send.
        > Defaults to the command invocation channel.

        **`[reply_to: Message]`**
        > A flag for the message to use as a reference.

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
        > > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        return await self.message_send_func(
            ctx,
            attachments,
            content=content,
            embeds=embeds,
            to=to,
            reply_to=reply_to,
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
        content: String[2000] | None = None,
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
    ):
        return await self.message_send_func(
            ctx,
            attachments,
            content=content,
            embeds=embeds,
            to=to,
            reply_to=reply_to,
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
        usage="[attachments (upload files < 8 MiB)]... <to: ForumChannel> "
        "<name|title: Text[100]> [content: Text[2000]] "
        "[embeds: CodeBlock...] [tags: String[20]...] [reply_to: Message] "
        "[delete_after: Number/TimeDelta] [mention_all: yes|no] "
        "[mention_everyone: yes|no] [mention_users: yes|no] "
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
        content: String[2000] | None = None,
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        tags: tuple[str, ...] = (),
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
        > A flag for the forum post name/title.
        > It must not exceed 100 characters in length.

        **`[content: Text[2000]]`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[embeds: CodeBlock...]`**
        > A flag for the embeds to add to the message, as 1-10 code blocks containing embed data as a JSON object/Python dictionary.

        **`[tags: String[20]...]`**
        > The tags to apply to the post, if they exist.

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
        > > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not (content or attachments or embeds):
            raise commands.CommandInvokeError(
                commands.CommandError("Not enough arguments given as input.")
            )

        destinations = to
        if not destinations:
            destinations = (ctx.channel,)

        elif len(destinations) > 1 and tags:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You cannot specify multiple channels for flag `to:` if flag "
                    "`tags:` is specified."
                )
            )

        tag_names = tuple(tag_name.casefold() for tag_name in tags)

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

        parsed_embeds = []
        files = []

        if embeds:
            for i, code_block_or_msg in enumerate(embeds):
                if isinstance((code_block := code_block_or_msg), CodeBlock):
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
                elif isinstance(
                    (embed_msg := code_block_or_msg), (discord.Message, tuple)
                ):
                    attachment_index = 0
                    if isinstance(embed_msg, tuple):
                        embed_msg, attachment_index = (
                            embed_msg[0],
                            embed_msg[1],
                        )

                    if not (embed_msg_attachments := embed_msg.attachments):
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                f"Error with `embeds` argument {i}: Messages "
                                "speficied for flag `embeds` must have at least one "
                                "attachment as `.txt`, `.py` file containing a Python "
                                "dictionary, or a `.json` file containing embed data. "
                                "It must be less than 10KB in size.",
                            )
                        )

                    embed_attachment = embed_msg_attachments[
                        min(attachment_index, len(embed_msg_attachments))
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
                                "speficied for flag `embeds` must have at least one "
                                "attachment as `.txt`, `.py` file containing a Python "
                                "dictionary, or a `.json` file containing embed data. "
                                "It must be less than 10KB in size.",
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
                        except Exception as jerr:
                            raise commands.CommandInvokeError(
                                commands.CommandError(
                                    "Error while parsing embed JSON from attachment: "
                                    f"{i}: {jerr.__class__.__name__}: {jerr.args[0]}"
                                )
                            )
                    else:
                        try:
                            embed_dict = literal_eval(embed_data)
                        except Exception as perr:
                            raise commands.CommandInvokeError(
                                commands.CommandError(
                                    "Error while parsing Python embed dict from attachment: "
                                    f"{i}: {perr.__class__.__name__}: {perr.args[0]}"
                                )
                            )
                else:
                    continue

                parsed_embeds.append(discord.Embed.from_dict(embed_dict))

        if attachments:
            for i, att in enumerate(attachments):
                if att.size > 2**20 * 25:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Attachment {i} is too large to be resent (> 25MiB)"
                        )
                    )
                files.append(await att.to_file(use_cached=True))

        for dest in destinations:
            assert isinstance(dest, discord.ForumChannel)
            msg = await dest.create_thread(
                name=name,
                content=content,
                embeds=parsed_embeds,
                files=files,
                allowed_mentions=(
                    discord.AllowedMentions.all()
                    if mention_all
                    else discord.AllowedMentions(
                        everyone=mention_everyone,
                        users=(
                            mention_these_users
                            if mention_these_users
                            else mention_users
                        ),
                        roles=(
                            mention_these_roles
                            if mention_these_roles
                            else mention_roles
                        ),
                    )
                ),
                applied_tags=[
                    tag
                    for tag in dest.available_tags
                    if tag.name.casefold() in tag_names
                ]
                or discord.utils.MISSING,
            )

    @commands.guild_only()
    @message.command(
        name="sendcontent",
        aliases=["createcontent", "sendtext", "createtext"],
        extras=dict(delete_invocation=True),
        usage="<content (Text[2000])> [to: Channel] [reply_to: Message] "
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

        **`<content (Text[2000])>`**
        > A flag for the text content the message should contain.
        > It must not exceed 2000 characters in length.

        **`[to: Channel]`**
        > A flag for the destination channel of the message to send.
        > Defaults to the command invocation channel.

        **`[reply_to: Message]`**
        > A flag for the message to use as a reference.

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
        > > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )
        destinations = to
        if not destinations:
            destinations = (ctx.channel,)

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

        for dest in destinations:
            msg = await (
                reply_to.reply(
                    content=content,
                    allowed_mentions=(
                        discord.AllowedMentions.all()
                        if mention_all
                        else discord.AllowedMentions(
                            everyone=mention_everyone,
                            users=(
                                mention_these_users
                                if mention_these_users
                                else mention_users
                            ),
                            roles=(
                                mention_these_roles
                                if mention_these_roles
                                else mention_roles
                            ),
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
                            users=(
                                mention_these_users
                                if mention_these_users
                                else mention_users
                            ),
                            roles=(
                                mention_these_roles
                                if mention_these_roles
                                else mention_roles
                            ),
                            replied_user=mention_replied_user,
                        )
                    ),
                )
            )
            if delete_after:
                await msg.delete(
                    delay=(
                        delete_after.total_seconds()
                        if isinstance(delete_after, datetime.timedelta)
                        else delete_after
                    )
                )

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="edit",
        usage="[attachments (upload files < 8 MiB)]... <message> [content: Text[2000]] "
        "[embeds: CodeBlock/Message/( Message Integer ) ... ] [tags: String[20]...] "
        "[mention_everyone: yes|no] [mention_users: yes|no] "
        "[mention_these_users: User...] [mention_roles: yes|no] "
        "[mention_these_roles: Role...] [mention_replied_user: yes|no]",
        extras=dict(inject_reference_as_first_argument=True, delete_invocation=True),
    )
    @flagconverter_kwargs()
    async def message_edit(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message | None,
        attachments: commands.Greedy[discord.Attachment],
        *,
        name: String[100] | None = commands.flag(
            name="name", aliases=["title"], default=None
        ),
        content: String | None = None,
        embeds: tuple[
            Parens[discord.Message, int] | discord.Message | CodeBlock, ...
        ] = (),
        tags: tuple[str, ...] = (),
        remove_content: bool = False,
        remove_embeds: bool = False,
        remove_all_attachments: bool = False,
        remove_old_attachments: bool = False,
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

        **`<message: Message>...`**
        > The message to edit.

        **`[attachments (upload files < 8 MiB)]...`**
        > One or more new attachments to add to the message.
        > They must not exceed 8 MiB in size.

        **`[name|title: Text[100]]`**
        > A flag for the message's forum post or thread name/title, if applicable.
        > It must not exceed 100 characters in length.

        **`[content: Text[2000]]`**
        > A flag for the text content the edited message should contain.
        > It must not exceed 2000 characters in length.

        **`[embeds: CodeBlock/Message/( Message Integer ) ... ]`**
        > A flag for the embeds to add to the message, as 1-10 of these:
        > • Code blocks containing embed data as a JSON object/Python dictionary
        > • A message containing embed data as a JSON object/Python dictionary in its first attachment
        > • A parenthesized pair containing a message containing embed data as a JSON object/Python dictionary in its first attachment, followed by an index (0-9) representing the attachment position.
        >
        > If any of these arguments evaluate to an empty dictionary/JSON object ( `{}` ), the preexisting embeds at their position will be preserved.

        **`[tags: String[20]...]`**
        > The tags to apply to the message's post, if applicable and they exist.

        **`[remove_content: yes|no]`**
        > A flag for whether all mentionable targets in the message text content (users, roles, user being replied to) should receive a mention ping.

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
        > > A flag for a sequence of roles in the message text content that should receive a mention ping.
        > This overrides the settings of the `mention_roles:` flag.

        **`[mention_replied_user: yes|no]`**
        > A flag for whether a user being replied to should be pinged.
        > Defaults to 'no'.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                MessageableGuildChannel.__args__,
            )
            and isinstance(ctx.author, discord.Member)
        )

        if not message:
            raise commands.CommandInvokeError(
                commands.BadArgument(
                    "'message' is a required argument that is missing."
                )
            )

        if not (content or attachments or embeds):
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

        if name and not (isinstance(message.channel, discord.Thread)):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Flag 'name:' or 'title:' can only be specified if targeting the starter message of a thread."
                )
            )

        elif tags and not (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent
            and isinstance(message.channel.parent, discord.ForumChannel)
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Flag 'tags:' can only be specified if targeting the starter message of a forum channel post."
                )
            )

        elif (name or tags) and isinstance(message.channel, discord.Thread):
            is_thread_starter_msg = True

        tag_names = tuple(tag_name.casefold() for tag_name in tags)

        former_embeds = message.embeds
        parsed_embeds = []
        files = []
        old_attachments = [] if remove_old_attachments else message.attachments

        for i, code_block_or_msg in enumerate(embeds):
            if isinstance((code_block := code_block_or_msg), CodeBlock):
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
            elif isinstance((embed_msg := code_block_or_msg), (discord.Message, tuple)):
                attachment_index = 0
                if isinstance(embed_msg, tuple):
                    embed_msg, attachment_index = (
                        embed_msg[0],
                        embed_msg[1],
                    )

                if not (embed_msg_attachments := embed_msg.attachments):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Error with `embeds` argument {i}: Messages "
                            "speficied for flag `embeds` must have at least one "
                            "attachment as `.txt`, `.py` file containing a Python "
                            "dictionary, or a `.json` file containing embed data. "
                            "It must be less than 10KB in size.",
                        )
                    )

                embed_attachment = embed_msg_attachments[
                    min(attachment_index, len(embed_msg_attachments))
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
                            "speficied for flag `embeds` must have at least one "
                            "attachment as `.txt`, `.py` file containing a Python "
                            "dictionary, or a `.json` file containing embed data. "
                            "It must be less than 10KB in size.",
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
                    except Exception as jerr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing embed JSON from attachment: "
                                f"{i}: {jerr.__class__.__name__}: {jerr.args[0]}"
                            )
                        )
                else:
                    try:
                        embed_dict = literal_eval(embed_data)
                    except Exception as perr:
                        raise commands.CommandInvokeError(
                            commands.CommandError(
                                "Error while parsing Python embed dict from attachment: "
                                f"{i}: {perr.__class__.__name__}: {perr.args[0]}"
                            )
                        )
            else:
                continue

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

        parsed_embeds = [
            embed or former_embeds[i]
            for i, embed in enumerate(parsed_embeds)
            if embed or i < len(former_embeds)
        ]
        # filter out empty embeds, which can act as placeholders for former embeds

        final_attachments = discord.utils.MISSING
        if files or old_attachments:
            final_attachments = (old_attachments + files)[
                max(-10, -(len(old_attachments) + len(files))) :
            ]  # only keep the 10 newest entries
        elif remove_all_attachments:
            final_attachments = []

        allowed_mentions_kwargs = {}
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

        if is_thread_starter_msg:
            await message.channel.edit(
                name=name or discord.utils.MISSING,  # type: ignore
                applied_tags=[
                    tag
                    for tag in (message.channel.parent.available_tags)  # type: ignore
                    if tag.name.casefold() in tag_names
                ]
                or discord.utils.MISSING,
            )

        await message.edit(
            content=(
                content
                if content
                else None if remove_content else discord.utils.MISSING
            ),
            embeds=(
                parsed_embeds
                if parsed_embeds
                else [] if remove_embeds else discord.utils.MISSING
            ),
            attachments=final_attachments,
            allowed_mentions=(
                discord.AllowedMentions.all()
                if mention_all
                else (
                    discord.AllowedMentions(
                        **allowed_mentions_kwargs,
                    )
                    if allowed_mentions_kwargs
                    else discord.utils.MISSING
                )
            ),
        )

    @commands.guild_only()
    @message.command(
        name="editcontent",
        aliases=["edittext"],
        usage="<message> <content (Text[2000])>",
        extras=dict(inject_reference_as_first_argument=True, delete_invocation=True),
    )
    async def message_editcontent(
        self,
        ctx: commands.Context[BotT],
        message: (
            discord.Message | None
        ),  # required for injecting reference messages to work
        content: String[2000],
    ):
        """Edit an existing message with new text content.

        __**Parameters:**__

        **`<message>`**
        > The message to edit.

        **`<content (Text[2000])>`**
        > The text content to edit the message with.
        > It must not exceed 2000 characters in length.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
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
        await message.edit(
            content=content,
        )

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="extract",
        usage="<messages>... [to: Channel] [content: yes|no] "
        "[content_attachment: yes|no] [attachments: yes|no] [embeds: yes|no] "
        "[info: yes|no] [author_info: yes|no]",
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_extract(
        self,
        ctx: commands.Context[BotT],
        *messages: discord.Message,
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

        **`<messages>...`**
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
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

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
                ) as strio:
                    cum_size = 0
                    attached_files = [
                        (
                            await a.to_file(spoiler=a.is_spoiler())
                            if (cum_size := cum_size + a.size) <= filesize_limit
                            else discord.File(strio, f"filetoolarge - {a.filename}.txt")
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
                    with io.BytesIO(msg.content.encode("utf-8")) as strio:
                        content_file = discord.File(strio, "messagedata.txt")

                await destination.send(embed=info_embed, file=content_file)  # type: ignore

            elif content_attachment and msg.content:
                with io.BytesIO(msg.content.encode("utf-8")) as strio:
                    await destination.send(
                        file=discord.File(strio, "messagedata.txt"),
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
                    with io.BytesIO(msg.content.encode("utf-8")) as strio:
                        await destination.send(
                            file=discord.File(strio, "messagedata.txt"),
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
                        content=f"**Message attachments** ({i+1}):",
                        files=attached_files,
                    )

            if embeds and msg.embeds:
                embed_data_strios = []
                for embed in msg.embeds:
                    embed_data_strio = io.StringIO(
                        json.dumps(embed.to_dict(), indent=4)
                    )
                    embed_data_strio.seek(0)
                    embed_data_strios.append(embed_data_strio)

                await ctx.send(
                    content=f"**Message embeds** ({len(embed_data_strios)}):",
                    files=[
                        discord.File(strio, filename=f"embeddata{i}.json")
                        for i, strio in enumerate(embed_data_strios)
                    ],
                )

                for embed_data_strio in embed_data_strios:
                    embed_data_strio.close()

            await asyncio.sleep(0)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="clone",
        usage="<messages>.. [to: Channel] [embeds: yes|no] [attachments: yes|no] "
        "[as_spoiler: yes|no] [info: yes|no] [author_info: yes|no] [skip_empty: yes|no]",
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_clone(
        self,
        ctx: commands.Context[BotT],
        *messages: discord.Message,
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

        **`<messages>...`**
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
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

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
        for i, msg in enumerate(messages):
            attached_files = []
            if msg.attachments and attachments:
                filesize_limit = 2**20 * 8  # 8 MiB
                with io.StringIO(
                    "This file could not be duplicated due to the "
                    "message file limit of 8 MiB being exceeded."
                ) as strio:
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
                            else discord.File(strio, f"filetoolarge - {a.filename}.txt")  # type: ignore
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

                        with io.StringIO(msg.content) as strio:
                            await destination.send(
                                content=msg.content[stop_idx:],
                                embed=discord.Embed.from_dict(
                                    dict(
                                        color=int(self.theme_color),
                                        footer=dict(text="Full message data"),
                                    )
                                ),
                                file=discord.File(strio, filename="messagedata.txt"),  # type: ignore
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
                    await ctx.send(
                        embed=info_embed,
                        reference=first_cloned_msg,  # type: ignore
                    )

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
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
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
        with io.StringIO("This file was too large to be archived.") as strio:
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

                strio.seek(0)

                filesize_limit = 2**20 * 8  # 8 MiB

                cum_size = 0
                attached_files = [
                    (
                        await a.to_file(spoiler=a.is_spoiler())
                        if (cum_size := cum_size + a.size) <= filesize_limit
                        else discord.File(strio, f"filetoolarge - {a.filename}.txt")  # type: ignore
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

                            with io.StringIO(msg.content) as strio:
                                await destination.send(
                                    content=msg.content[stop_idx:],
                                    embed=discord.Embed.from_dict(
                                        dict(
                                            color=int(self.theme_color),
                                            footer=dict(text="Full message data"),
                                        )
                                    ),
                                    file=discord.File(strio, filename="messagedata.txt"),  # type: ignore
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
                                with io.StringIO(msg.content) as strio:
                                    message_id_cache[msg.id] = await destination.send(
                                        file=discord.File(strio, "messagedata.txt"),  # type: ignore
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
                            with io.StringIO(msg.content) as strio2:
                                message_id_cache[msg.id] = await destination.send(
                                    file=discord.File(
                                        strio2, filename="messagedata.txt"  # type: ignore
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
                        embed_data_strios = []
                        for embed in msg.embeds:
                            embed_data_strio = io.StringIO()
                            json.dump(embed.to_dict(), embed_data_strio, indent=4)
                            embed_data_strio.seek(0)
                            embed_data_strios.append(embed_data_strio)

                        await destination.send(
                            content=f"**Message embeds** ({i + 1}):",
                            files=[
                                discord.File(strio, filename=f"embeddata{i}.json")
                                for strio in embed_data_strios
                            ],
                        )

                        for embed_data_strio in embed_data_strios:
                            embed_data_strio.close()

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
        usage="<messages>... [delete_system_message: yes|no] [unpin_last: yes|no]",
        invoke_without_command=True,
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_pin(
        self,
        ctx: commands.Context[BotT],
        *messages: discord.PartialMessage,
        delete_system_message: bool = False,
        unpin_last: bool = False,
        _channel: MessageableGuildChannel | None = None,
    ):
        """Pin the specified messages.

        __**Parameters:**__

        **`<messages>...`**
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
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

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
        system_message_check = (
            lambda m: m.channel.id == channel.id  # type: ignore
            and m.type == discord.MessageType.pins_add
        )
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
        usage="<messages>... [channel: TextChannel/Thread] [delete_system_message: yes|no] [unpin_last: yes|no]",
        invoke_without_command=True,
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def message_pin_in(
        self,
        ctx: commands.Context[BotT],
        channel: MessageableGuildChannel | None = None,
        *messages: discord.PartialMessage,
        delete_system_message: bool = False,
        unpin_last: bool = True,
    ):
        """Pin the specified messages inside the specified channel.

        __**Parameters:**__

        **`<messages>...`**
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
            *messages,
            delete_system_message=delete_system_message,
            unpin_last=unpin_last,
            _channel=channel,
        )

    @commands.guild_only()
    @message.group(
        name="unpin",
        usage="<messages>...",
        invoke_without_command=True,
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    async def message_unpin(
        self,
        ctx: commands.Context[BotT],
        *messages: discord.PartialMessage,
        _channel: MessageableGuildChannel | None = None,
    ):
        """Unpin the specified messages.

        __**Parameters:**__

        **`<messages>...`**
        > The messages to unpin.
        """
        assert (
            ctx.guild
            and ctx.bot.user
            and (bot_member := ctx.guild.get_member(ctx.bot.user.id))
            and isinstance(
                ctx.channel,
                (discord.TextChannel, discord.VoiceChannel, discord.Thread),
            )
            and isinstance(ctx.author, discord.Member)
        )

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
        usage="<messages>... [channel: TextChannel/Thread]",
        invoke_without_command=True,
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

        **`<messages>...`**
        > The messages to unpin.

        **`[channel: TextChannel/Thread]`**
        > The channel in which the messages are contained in.
        > Defaults to the invocation channel.
        """
        await self.message_unpin(ctx, *messages, _channel=channel)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: int | discord.Color = 0):
    await bot.add_cog(Messaging(bot, theme_color=color))
