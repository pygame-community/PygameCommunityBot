from ast import literal_eval
import asyncio
import datetime
import io
import json
from typing import Optional, Union

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


def get_markdown_member_info(member: Union[discord.Member, discord.User]):
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
    member: Union[discord.Member, discord.User] = msg.author

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
                        f"\n {msg.content[:2001]}" + "\n\n[...]"
                        if len(msg.content) > 2000
                        else msg.content,
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
                    f"\n {msg.content[:2001]}" + "\n[...]"
                    if len(msg.content) > 2000
                    else msg.content,
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
                commands.BadArgument("No message given as input.")
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

        content = c or text or content

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

        content = c or text or content

        if not message:
            raise commands.CommandInvokeError(
                commands.BadArgument("No message given as input.")
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

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="extract",
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_extract(
        self,
        ctx: commands.Context[BotT],
        *msgs: discord.Message,
        to: Optional[MessageableGuildChannel] = None,
        as_attachment: bool = False,
        attachments: bool = True,
        embeds: bool = True,
        info: bool = False,
        author_info: bool = True,
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
        for i, msg in enumerate(msgs):
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

        if not all(msgs):
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )

        for i, msg in enumerate(msgs):
            assert msg
            escaped_msg_content = msg.content.replace("```", "\\`\\`\\`")
            attached_files = None
            if attachments:
                filesize_limit = 2**20 * 8  # 8 MiB
                with io.BytesIO(
                    "This file could not be duplicated due to the "
                    "message file limit of 8 MiB being exceeded.".encode("utf-8")
                ) as fobj:
                    cum_size = 0
                    attached_files = [
                        (
                            await a.to_file(spoiler=a.is_spoiler())
                            if (cum_size := cum_size + a.size) <= filesize_limit
                            else discord.File(fobj, f"filetoolarge - {a.filename}.txt")
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
                        f"\n\n ```\n{escaped_msg_content[:2001]}\n\n[...]\n```"
                        + "\n\u200b"
                        if len(escaped_msg_content) > 2000
                        else "\n\u200b",
                    )
                )

                content_file = None
                if as_attachment or len(msg.content) > 2000:
                    with io.BytesIO(msg.content.encode("utf-8")) as fobj:
                        content_file = discord.File(fobj, "messagedata.txt")

                await destination.send(embed=info_embed, file=content_file)  # type: ignore

            elif as_attachment:
                with io.BytesIO(msg.content.encode("utf-8")) as fobj:
                    await destination.send(
                        file=discord.File(fobj, "messagedata.txt"),
                        embed=discord.Embed.from_dict(
                            dict(
                                author=dict(name="Message Data"),
                                color=int(self.theme_color),
                                description=f"**[View original message]({msg.jump_url})**",
                            )
                        ),
                    )
            else:
                if len(msg.content) > 2000 or len(escaped_msg_content) > 2000:
                    with io.BytesIO(msg.content.encode("utf-8")) as fobj:
                        await destination.send(
                            file=discord.File(fobj, "messagedata.txt"),
                            embed=discord.Embed.from_dict(
                                dict(
                                    author=dict(name="Message Data"),
                                    color=int(self.theme_color),
                                    description=f"**[View original message]({msg.jump_url})**",
                                )
                            ),
                        )
                else:
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
                embed_data_fobjs = []
                for embed in msg.embeds:
                    embed_data_fobj = io.StringIO()
                    snakecore.utils.embeds.export_embed_data(
                        embed.to_dict(),  # type: ignore
                        fp=embed_data_fobj,
                        indent=4,
                        as_json=True,
                    )
                    embed_data_fobj.seek(0)
                    embed_data_fobjs.append(embed_data_fobj)

                await ctx.send(
                    content=f"**Message embeds** ({len(embed_data_fobjs)}):",
                    files=[
                        discord.File(fobj, filename=f"embeddata{i}.json")
                        for i, fobj in enumerate(embed_data_fobjs)
                    ],
                )

                for embed_data_fobj in embed_data_fobjs:
                    embed_data_fobj.close()

            await asyncio.sleep(0)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.default, wait=True)
    @message.command(
        name="clone",
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def message_clone(
        self,
        ctx: commands.Context[BotT],
        *msgs: discord.Message,
        to: Optional[tuple[MessageableGuildChannel, ...]] = None,
        embeds: bool = True,
        attachments: bool = True,
        as_spoiler: Optional[bool] = None,
        info: bool = False,
        author_info: bool = True,
        skip_empty: bool = True,
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
        for i, msg in enumerate(msgs):
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

        if not msgs:
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )

        no_mentions = discord.AllowedMentions.none()
        for i, msg in enumerate(msgs):
            attached_files = []
            if msg.attachments and attachments:
                filesize_limit = 2**20 * 8  # 8 MiB
                with io.StringIO(
                    "This file could not be duplicated due to the "
                    "message file limit of 8 MiB being exceeded."
                ) as fobj:
                    cum_size = 0
                    attached_files = [
                        (
                            await a.to_file(
                                spoiler=as_spoiler
                                if as_spoiler is not None
                                else a.is_spoiler()
                            )
                            if (cum_size := cum_size + a.size) <= filesize_limit
                            else discord.File(fobj, f"filetoolarge - {a.filename}.txt")  # type: ignore
                        )
                        for a in msg.attachments
                    ]
            for destination in destinations:
                if msg.content or msg.embeds or attached_files:
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

                        with io.StringIO(msg.content) as fobj:
                            await destination.send(
                                content=msg.content[stop_idx:],
                                embed=discord.Embed.from_dict(
                                    dict(
                                        color=int(self.theme_color),
                                        footer=dict(text="Full message data"),
                                    )
                                ),
                                file=discord.File(fobj, filename="messagedata.txt"),  # type: ignore
                                allowed_mentions=no_mentions,
                            )
                        await destination.send(
                            embeds=msg.embeds if embeds else None,  # type: ignore
                            files=attached_files if attachments else None,  # type: ignore
                        )
                    else:
                        first_cloned_msg = await destination.send(
                            content=msg.content,
                            embeds=msg.embeds if embeds else None,  # type: ignore
                            files=attached_files if attachments else None,  # type: ignore
                            allowed_mentions=no_mentions,
                        )
                elif not skip_empty:
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
        quantity: Optional[int] = None,
        *,
        mode: int = 0,
        to: Optional[MessageableGuildChannel] = None,
        before: Optional[Union[discord.PartialMessage, datetime.datetime]] = None,
        after: Optional[Union[discord.PartialMessage, datetime.datetime]] = None,
        around: Optional[Union[discord.PartialMessage, datetime.datetime]] = None,
        raw: bool = False,
        show_header: bool = True,
        show_author: bool = True,
        divider: String = "-" * 56,
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

        if snakecore.utils.have_permissions_in_channels(
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
        with io.StringIO("This file was too large to be archived.") as fobj:
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

                fobj.seek(0)

                filesize_limit = 2**20 * 8  # 8 MiB

                cum_size = 0
                attached_files = [
                    (
                        await a.to_file(spoiler=a.is_spoiler())
                        if (cum_size := cum_size + a.size) <= filesize_limit
                        else discord.File(fobj, f"filetoolarge - {a.filename}.txt")  # type: ignore
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

                            with io.StringIO(msg.content) as fobj:
                                await destination.send(
                                    content=msg.content[stop_idx:],
                                    embed=discord.Embed.from_dict(
                                        dict(
                                            color=int(self.theme_color),
                                            footer=dict(text="Full message data"),
                                        )
                                    ),
                                    file=discord.File(fobj, filename="messagedata.txt"),  # type: ignore
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
                                with io.StringIO(msg.content) as fobj:
                                    message_id_cache[msg.id] = await destination.send(
                                        file=discord.File(fobj, "messagedata.txt"),  # type: ignore
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
                            with io.StringIO(msg.content) as fobj2:
                                message_id_cache[msg.id] = await destination.send(
                                    file=discord.File(
                                        fobj2, filename="messagedata.txt"  # type: ignore
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
                        embed_data_fobjs = []
                        for embed in msg.embeds:
                            embed_data_fobj = io.StringIO()
                            snakecore.utils.embeds.export_embed_data(
                                embed.to_dict(),  # type: ignore
                                fp=embed_data_fobj,
                                indent=4,
                                as_json=True,
                            )
                            embed_data_fobj.seek(0)
                            embed_data_fobjs.append(embed_data_fobj)

                        await destination.send(
                            content=f"**Message embeds** ({i + 1}):",
                            files=[
                                discord.File(fobj, filename=f"embeddata{i}.json")
                                for fobj in embed_data_fobjs
                            ],
                        )

                        for embed_data_fobj in embed_data_fobjs:
                            embed_data_fobj.close()

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
        *msgs: discord.PartialMessage,
        delete_system_message: bool = False,
        unpin_last: bool = True,
        _channel: Optional[MessageableGuildChannel] = None,
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

        if not msgs:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No message IDs given as input.",
                )
            )
        elif len(msgs) > 50:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "Cannot pin more than 50 messages in a channel at a time.",
                )
            )

        elif not all(msg.channel.id == channel.id for msg in msgs):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "All specified messages must originate from the given channel "
                    f"(<#{channel.id}>).",
                )
            )

        pinned_msgs = await channel.pins()

        unpin_count = max((len(pinned_msgs) + len(msgs)) - 50, 0)
        if unpin_count > 0:
            if unpin_last:
                for i in range(unpin_count):
                    await pinned_msgs[i].unpin()
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Maximum pins limit of 50 reached (specify `unpin_last: yes` to migitate this)"
                    )
                )

        load_embed = discord.Embed.from_dict(
            dict(
                title="Your command is being processed:",
                color=int(self.theme_color),
                fields=[dict(name="\u200b", value="`...`", inline=False)],
            )
        )
        message_count = len(msgs)
        system_message_check = (
            lambda m: m.channel.id == channel.id  # type: ignore
            and m.type == discord.MessageType.pins_add
        )
        for i, msg in enumerate(msgs):
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
        invoke_without_command=True,
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def message_pin_in(
        self,
        ctx: commands.Context[BotT],
        channel: Optional[MessageableGuildChannel] = None,
        *msgs: discord.PartialMessage,
        delete_system_message: bool = False,
        unpin_last: bool = True,
    ):
        await self.message_pin(
            ctx,
            *msgs,
            delete_system_message=delete_system_message,
            unpin_last=unpin_last,
            _channel=channel,
        )

    @commands.guild_only()
    @message.group(
        name="unpin",
        invoke_without_command=True,
        extras=dict(
            inject_reference_as_first_argument=True,
            response_deletion_with_reaction=True,
        ),
    )
    async def message_unpin(
        self,
        ctx: commands.Context[BotT],
        *msgs: discord.PartialMessage,
        _channel: Optional[MessageableGuildChannel] = None,
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

        if not msgs:
            raise commands.CommandInvokeError(
                commands.CommandError("No messages given as input.")
            )
        elif len(msgs) > 50:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No more than 50 messages can be unpinned in a channel at a time."
                )
            )
        elif not all(msg.channel.id == channel.id for msg in msgs):
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

        message_count = len(msgs)
        for i, msg in enumerate(msgs):
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
        invoke_without_command=True,
        extras=dict(response_deletion_with_reaction=True),
    )
    async def message_unpin_in(
        self,
        ctx: commands.Context[BotT],
        channel: Optional[MessageableGuildChannel] = None,
        *msgs: discord.PartialMessage,
    ):
        await self.message_unpin(ctx, *msgs, _channel=channel)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: Union[int, discord.Color] = 0):
    await bot.add_cog(Messaging(bot, theme_color=color))
