"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import datetime
import re
from typing import Union

import discord
from discord.ext import commands
import snakecore

from .bases import BaseExtCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot

SHOWCASE_ENTRIES_CHANNEL = 772507247540437032
ENTRIES_DISCUSSION_CHANNEL = 780351772514058291


class ShowcasePreCog(BaseExtCog, name="showcase-pre"):
    def __init__(self, bot: BotT, theme_color: int | discord.Color = 0) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.entry_message_deletion_dict: dict[int, tuple[asyncio.Task[None], int]] = {}

    @staticmethod
    async def delete_bad_entry_and_warning(
        entry_msg: discord.Message, warn_msg: discord.Message, delay: float = 0.0
    ):
        """A function to pardon a bad entry message with a grace period. If this coroutine is not cancelled during the
        grace period specified in `delay` in seconds, it will delete both `entry_msg` and `warn_msg`, if possible.
        """
        try:
            await asyncio.sleep(delay)  # allow cancelling during delay
        except asyncio.CancelledError:
            return

        else:
            for msg in (entry_msg, warn_msg):
                # don't error here if messages were already deleted
                try:
                    await msg.delete()
                except discord.NotFound:
                    pass

    @staticmethod
    def format_entries_message(
        msg: discord.Message,
    ) -> tuple[str, list[dict[str, str | bool]]]:
        """
        Formats an entries message to be reposted in discussion channel
        """
        f"New showcase in #\u200b{msg.channel.name}"  # type: ignore
        title = ""

        attachments = ""
        if msg.attachments:
            for i, attachment in enumerate(msg.attachments):
                attachments += f" • [Link {i + 1}]({attachment.url})\n"
        else:
            attachments = "No attachments"

        desc = msg.content if msg.content else "No description provided."

        fields = [
            {"name": "**Posted by**", "value": msg.author.mention, "inline": True},
            {
                "name": "**Original msg.**",
                "value": f"[View]({msg.jump_url})",
                "inline": True,
            },
            {"name": "**Attachments**", "value": attachments, "inline": True},
            {
                "name": "**Description**",
                "value": desc if len(desc) < 1025 else desc[:1022] + "...",
                "inline": True,
            },
        ]
        return title, fields

    @staticmethod
    def entry_message_validity_check(
        message: discord.Message, min_chars=32, max_chars=float("inf")
    ):
        """Checks if a message posted in a showcase channel for projects has the right format.

            Returns
        -------
                bool: True/False
        """
        search_obj = re.search(
            snakecore.utils.regex_patterns.URL, message.content or ""
        )
        link_in_msg = bool(search_obj)
        first_link_str = search_obj.group() if link_in_msg else ""

        if (
            message.content
            and (link_in_msg and len(message.content) > len(first_link_str))
            and min_chars < len(message.content) < max_chars
        ):
            return True

        elif (message.content or message.reference) and message.attachments:
            return True

        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != SHOWCASE_ENTRIES_CHANNEL or message.author.bot:
            return

        assert message.guild
        if not self.entry_message_validity_check(message):
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=2)
            warn_msg = await message.reply(
                "Your entry message must contain an attachment or text and a (Discord recognized) link to be valid."
                " If it doesn't contain any characters but an attachment, it must be a reply to another entry you created."
                f" If no attachments are present, it must contain at least 32 characters (including any links, but not links alone)."
                f" If you meant to comment on another entry, please delete your message and go to <#{ENTRIES_DISCUSSION_CHANNEL}> ."
                " If no changes are made, your entry message will be"
                f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
            )
            self.entry_message_deletion_dict[message.id] = [  # type: ignore
                asyncio.create_task(
                    self.delete_bad_entry_and_warning(message, warn_msg, delay=120)
                ),
                warn_msg.id,
            ]
            return

        color = 0xFF8800
        title, fields = self.format_entries_message(message)

        entries_discussion_channel = message.guild.get_channel(
            ENTRIES_DISCUSSION_CHANNEL
        ) or await message.guild.fetch_channel(ENTRIES_DISCUSSION_CHANNEL)

        await entries_discussion_channel.send(  # type: ignore
            embed=discord.Embed.from_dict(dict(title=title, color=color, fields=fields))
        )

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message):
        if new.channel.id != SHOWCASE_ENTRIES_CHANNEL or new.author.bot:
            return
        embed_repost_edited = False
        if not self.entry_message_validity_check(new):
            if new.id in self.entry_message_deletion_dict:
                deletion_data_tuple = self.entry_message_deletion_dict[new.id]
                deletion_task = deletion_data_tuple[0]
                if deletion_task.done():
                    del self.entry_message_deletion_dict[new.id]
                else:
                    try:
                        deletion_task.cancel()  # try to cancel deletion after noticing edit by sender
                        warn_msg = await new.channel.fetch_message(
                            deletion_data_tuple[1]
                        )
                        deletion_datetime = datetime.datetime.now(
                            datetime.timezone.utc
                        ) + datetime.timedelta(minutes=2)
                        await warn_msg.edit(
                            content=(
                                "I noticed your edit, but: Your entry message must contain an attachment or a (Discord recognized) link to be valid."
                                " If it doesn't contain any characters but an attachment, it must be a reply to another entry you created."
                                f" If no attachments are present, it must contain at least 32 characters (including any links, but not links alone)."
                                f" If you meant to comment on another entry, please delete your message and go to <#{ENTRIES_DISCUSSION_CHANNEL}> ."
                                " If no changes are made, your entry message will be"
                                f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
                            )
                        )
                        self.entry_message_deletion_dict[new.id] = (
                            asyncio.create_task(
                                self.delete_bad_entry_and_warning(
                                    new, warn_msg, delay=120
                                )
                            ),
                            warn_msg.id,
                        )
                    except discord.NotFound:  # cancelling didn't work, warning and entry message were already deleted
                        del self.entry_message_deletion_dict[new.id]

            else:  # an edit led to an invalid entry message from a valid one
                deletion_datetime = datetime.datetime.now(
                    datetime.timezone.utc
                ) + datetime.timedelta(minutes=2)
                warn_msg = await new.reply(
                    "Your entry message must contain an attachment or text and a (Discord recognized) link to be valid."
                    " If it doesn't contain any characters but an attachment, it must be a reply to another entry you created."
                    f" If no attachments are present, it must contain at least 32 characters (including any links, but not links alone)."
                    f" If you meant to comment on another entry, please delete your message and go to <#{ENTRIES_DISCUSSION_CHANNEL}> ."
                    " If no changes are made, your entry message will be"
                    f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
                )

                self.entry_message_deletion_dict[new.id] = (
                    asyncio.create_task(
                        self.delete_bad_entry_and_warning(new, warn_msg, delay=120)
                    ),
                    warn_msg.id,
                )
            return

        elif (
            self.entry_message_validity_check(new)
            and new.id in self.entry_message_deletion_dict
        ):  # an invalid entry was corrected
            deletion_data_tuple = self.entry_message_deletion_dict[new.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():  # too late to do anything
                try:
                    deletion_task.cancel()  # try to cancel deletion after noticing valid edit by sender
                    warn_msg = await new.channel.fetch_message(deletion_data_tuple[1])
                    await warn_msg.delete()
                except discord.NotFound:  # cancelling didn't work, warning and entry message were already deleted
                    pass
            del self.entry_message_deletion_dict[new.id]

        entries_discussion_channel = new.guild.get_channel(  # type: ignore
            ENTRIES_DISCUSSION_CHANNEL
        ) or await new.guild.fetch_channel(  # type: ignore
            ENTRIES_DISCUSSION_CHANNEL
        )

        async for message in entries_discussion_channel.history(  # type: ignore # attempt to find and edit repost
            around=old.created_at, limit=5
        ):
            if not (message.author.id == self.bot.user.id and (embeds := message.embeds)):  # type: ignore
                continue
            try:
                embed = embeds[0]
                if not embed.fields:
                    continue
                link = embed.fields[1].value
                if not isinstance(link, str):
                    continue

                if int(link.split("/")[6][:-1]) == new.id:
                    _, fields = self.format_entries_message(new)
                    await message.edit(
                        embed=discord.Embed.from_dict(
                            embed.to_dict() | {"fields": fields}
                        )
                    )
                    embed_repost_edited = True
                    break
            except (IndexError, AttributeError):
                pass

        if not embed_repost_edited:
            if (
                datetime.datetime.now(datetime.timezone.utc) - old.created_at
            ) < datetime.timedelta(
                minutes=5
            ):  # for new, recently corrected entry messages
                color = 0xFF8800

                title, fields = self.format_entries_message(new)
                await entries_discussion_channel.send(  # type: ignore
                    embed=discord.Embed.from_dict(
                        dict(title=title, color=color, fields=fields)
                    )
                )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if (
            message.channel.id in (SHOWCASE_ENTRIES_CHANNEL, ENTRIES_DISCUSSION_CHANNEL)
            and message.channel
            and message.guild
        ):
            if (
                message.channel.id == SHOWCASE_ENTRIES_CHANNEL
                and message.id in self.entry_message_deletion_dict
            ):  # for case where user deletes their bad entry by themselves
                deletion_data_list = self.entry_message_deletion_dict[message.id]
                deletion_task = deletion_data_list[0]
                if not deletion_task.done():
                    deletion_task.cancel()
                    try:
                        warn_msg = await message.channel.fetch_message(
                            deletion_data_list[1]
                        )  # warning and entry message were already deleted
                        await warn_msg.delete()
                    except discord.NotFound:
                        pass

                del self.entry_message_deletion_dict[message.id]

            entries_discussion_channel = message.guild.get_channel(
                ENTRIES_DISCUSSION_CHANNEL
            ) or await message.guild.fetch_channel(ENTRIES_DISCUSSION_CHANNEL)

            async for message in entries_discussion_channel.history(  # type: ignore
                around=message.created_at, limit=5
            ):
                try:
                    link = message.embeds[0].fields[1].value
                    if not isinstance(link, str):
                        continue

                    if int(link.split("/")[6][:-1]) == message.id:
                        await message.delete()
                        break

                except (IndexError, AttributeError):
                    pass


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT):
    await bot.add_cog(ShowcasePreCog(bot))
