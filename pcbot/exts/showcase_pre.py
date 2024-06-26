"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import datetime
import re


import discord
from discord.ext import commands
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class ShowcasePreCog(BaseExtensionCog, name="showcase-pre"):
    def __init__(
        self, bot: BotT, showcase_channel_id: int, theme_color: int | discord.Color = 0
    ) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.showcase_channel_id = showcase_channel_id
        self.entry_post_deletion_dict: dict[int, tuple[asyncio.Task[None], int]] = {}

    @staticmethod
    async def delete_bad_entry_and_warning(
        entry_msg: discord.Message, warn_msg: discord.Message, delay: float = 0.0
    ):
        """A function to pardon a bad entry post with a grace period. If this coroutine is not cancelled during the
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
    def entry_message_validity_check(
        message: discord.Message, min_chars=32, max_chars=float("inf")
    ):
        """Checks if a post's starter message posted in a showcase channel has the right format.

        Returns
        -------
        bool:
            True/False
        """
        search_obj = re.search(
            snakecore.utils.regex_patterns.URL, message.content or ""
        )
        link_in_msg = bool(search_obj)
        first_link_str = search_obj.group() if link_in_msg else ""

        if (
            message.content
            and (link_in_msg and len(message.content) > len(first_link_str))
            and min_chars <= len(message.content) < max_chars
        ):
            return True

        elif (message.content or message.reference) and message.attachments:
            return True

        return False

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id != self.showcase_channel_id:
            return

        try:
            message = thread.starter_message or await thread.fetch_message(thread.id)
        except discord.NotFound:
            pass
        else:
            await message.pin()

        if not self.entry_message_validity_check(message):
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=2)
            warn_msg = await message.reply(
                "Your post must contain an attachment or text and safe links to be valid.\n\n"
                "- Attachment-only entries must be replies to a previous entry of yours.\n"
                "- Text-only entries must contain at least 32 characters (including links, but not links alone).\n\n"
                " If no changes are made, your post will be"
                f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
            )
            self.entry_post_deletion_dict[thread.id] = (
                asyncio.create_task(
                    self.delete_bad_entry_and_warning(message, warn_msg, delay=120)
                ),
                warn_msg.id,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message):
        if not (
            isinstance(new.channel, discord.Thread)
            and new.channel.parent_id == self.showcase_channel_id
        ):
            return

        thread = new.channel

        if not self.entry_message_validity_check(new):
            if thread.id in self.entry_post_deletion_dict:
                deletion_data_tuple = self.entry_post_deletion_dict[thread.id]
                deletion_task = deletion_data_tuple[0]
                if deletion_task.done():
                    del self.entry_post_deletion_dict[thread.id]
                else:
                    try:
                        deletion_task.cancel()  # try to cancel deletion after noticing edit by sender
                        warn_msg = await thread.fetch_message(deletion_data_tuple[1])
                        deletion_datetime = datetime.datetime.now(
                            datetime.timezone.utc
                        ) + datetime.timedelta(minutes=2)
                        await warn_msg.edit(
                            content=(
                                "I noticed your edit, but: Your post must contain an attachment or a (Discord recognized) link to be valid."
                                " If it doesn't contain any characters but an attachment, it must be a reply to another entry you created."
                                f" If no attachments are present, it must contain at least 32 characters (including any links, but not links alone)."
                                " If no changes are made, your post will be"
                                f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
                            )
                        )
                        self.entry_post_deletion_dict[thread.id] = (
                            asyncio.create_task(
                                self.delete_bad_entry_and_warning(
                                    new, warn_msg, delay=120
                                )
                            ),
                            warn_msg.id,
                        )
                    except (
                        discord.NotFound
                    ):  # cancelling didn't work, warning and post were already deleted
                        if thread.id in self.entry_post_deletion_dict:
                            del self.entry_post_deletion_dict[thread.id]

            else:  # an edit led to an invalid post from a valid one
                deletion_datetime = datetime.datetime.now(
                    datetime.timezone.utc
                ) + datetime.timedelta(minutes=2)
                warn_msg = await new.reply(
                    "Your post must contain an attachment or text and a (Discord recognized) link to be valid."
                    " If it doesn't contain any characters but an attachment, it must be a reply to another entry you created."
                    f" If no attachments are present, it must contain at least 32 characters (including any links, but not links alone)."
                    " If no changes are made, your post will be"
                    f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
                )

                self.entry_post_deletion_dict[thread.id] = (
                    asyncio.create_task(
                        self.delete_bad_entry_and_warning(new, warn_msg, delay=120)
                    ),
                    warn_msg.id,
                )
            return

        elif (
            self.entry_message_validity_check(new)
            and thread.id in self.entry_post_deletion_dict
        ):  # an invalid entry was corrected
            deletion_data_tuple = self.entry_post_deletion_dict[thread.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():  # too late to do anything
                try:
                    deletion_task.cancel()  # try to cancel deletion after noticing valid edit by sender
                    warn_msg = await thread.fetch_message(deletion_data_tuple[1])
                    await warn_msg.delete()
                except (
                    discord.NotFound
                ):  # cancelling didn't work, warning and post were already deleted
                    pass

            if thread.id in self.entry_post_deletion_dict:
                del self.entry_post_deletion_dict[thread.id]

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):

        if not (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.showcase_channel_id
        ):
            return

        thread = message.channel

        if (
            thread.id in self.entry_post_deletion_dict
        ):  # for case where user deletes their bad entry by themselves
            deletion_data_tuple = self.entry_post_deletion_dict[thread.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():
                deletion_task.cancel()
                try:
                    warn_msg = await message.channel.fetch_message(
                        deletion_data_tuple[1]
                    )  # warning and post were already deleted
                    await warn_msg.delete()
                except discord.NotFound:
                    pass

            if thread.id in self.entry_post_deletion_dict:
                del self.entry_post_deletion_dict[thread.id]


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT, showcase_channel_id: int, theme_color: int | discord.Color = 0
):
    await bot.add_cog(ShowcasePreCog(bot, showcase_channel_id, theme_color))
