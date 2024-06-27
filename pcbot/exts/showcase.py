"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import datetime
import re
import time


import discord
from discord.ext import commands
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class Showcase(BaseExtensionCog, name="showcase"):
    def __init__(
        self, bot: BotT, showcase_channel_id: int, theme_color: int | discord.Color = 0
    ) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.showcase_channel_id = showcase_channel_id
        self.entry_post_deletion_dict: dict[int, tuple[asyncio.Task[None], int]] = {}

    @staticmethod
    async def delete_bad_thread(thread: discord.Thread, delay: float = 0.0):
        """A function to pardon a bad thread with a grace period. If this coroutine is not cancelled during the
        grace period specified in `delay` in seconds, it will delete `thread`, if possible.
        """
        try:
            await asyncio.sleep(delay)  # allow cancelling during delay
        except asyncio.CancelledError:
            return

        else:
            try:
                await thread.delete()
            except discord.NotFound:
                # don't error here if post was already deleted
                pass

    @staticmethod
    def starter_message_validity_check(
        message: discord.Message, min_chars=32, max_chars=float("inf")
    ):
        """Checks if a thread's starter message has the right format.

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
            return

        if not self.starter_message_validity_check(message):
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=5)
            warn_msg = await message.reply(
                "Your post must contain an attachment or text and safe links to be valid.\n\n"
                "- Attachment-only entries must be in reference to a previous post of yours.\n"
                "- Text-only posts must contain at least 32 characters (including links, but not links alone).\n\n"
                " If no changes are made, your post will be"
                f" deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
            )
            self.entry_post_deletion_dict[thread.id] = (
                asyncio.create_task(self.delete_bad_thread(thread, delay=300)),
                warn_msg.id,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message):
        if not (
            isinstance(new.channel, discord.Thread)
            and new.channel.parent_id == self.showcase_channel_id
            and (
                new.content != old.content
                or new.embeds != old.embeds
                or new.attachments != old.attachments
            )
        ):
            return

        thread = new.channel

        if not self.starter_message_validity_check(new):
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
                        ) + datetime.timedelta(minutes=5)
                        await warn_msg.edit(
                            content=(
                                "I noticed your edit. However:\n\n"
                                "Your post must contain an attachment or text and safe "
                                "links to be valid.\n\n"
                                "- Attachment-only entries must be in reference to a "
                                "previous post of yours.\n"
                                "- Text-only posts must contain at least 32 "
                                "characters (including links, but not links alone).\n\n"
                                " If no changes are made, your post will be"
                                f" deleted "
                                + snakecore.utils.create_markdown_timestamp(
                                    deletion_datetime, "R"
                                )
                                + "."
                            )
                        )
                        self.entry_post_deletion_dict[thread.id] = (
                            asyncio.create_task(
                                self.delete_bad_thread(thread, delay=300)
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
                ) + datetime.timedelta(minutes=5)
                warn_msg = await new.reply(
                    "Your post must contain an attachment or text and safe links "
                    "to be valid.\n\n"
                    "- Attachment-only entries must be in reference to a previous "
                    "post of yours.\n"
                    "- Text-only posts must contain at least 32 characters "
                    "(including links, but not links alone).\n\n"
                    " If no changes are made, your post will be"
                    f" deleted "
                    + snakecore.utils.create_markdown_timestamp(deletion_datetime, "R")
                    + "."
                )

                self.entry_post_deletion_dict[thread.id] = (
                    asyncio.create_task(self.delete_bad_thread(thread, delay=300)),
                    warn_msg.id,
                )
            return

        elif (
            self.starter_message_validity_check(new)
            and thread.id in self.entry_post_deletion_dict
        ):  # an invalid entry was corrected
            deletion_data_tuple = self.entry_post_deletion_dict[thread.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():  # too late to do anything
                try:
                    deletion_task.cancel()  # try to cancel deletion after noticing valid edit by sender
                    await discord.PartialMessage(
                        channel=thread, id=deletion_data_tuple[1]
                    ).delete()
                except (
                    discord.NotFound
                ):  # cancelling didn't work, warning was already deleted
                    pass

            if thread.id in self.entry_post_deletion_dict:
                del self.entry_post_deletion_dict[thread.id]

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == self.showcase_channel_id
            and message.channel.id == message.id  # is starter message
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
                    await discord.PartialMessage(
                        channel=thread, id=deletion_data_tuple[1]
                    ).delete()
                except discord.NotFound:
                    # warning and post were already deleted
                    pass

            del self.entry_post_deletion_dict[thread.id]

        alert_msg = await thread.send(
            embed=discord.Embed.from_dict(
                dict(
                    title="Post scheduled for deletion",
                    description=(
                        "This post is scheduled for deletion:\n\n"
                        "The OP has deleted their starter message."
                        + "\n\nIt will be deleted "
                        f"**<t:{int(time.time()+300)}:R>**."
                    ),
                    color=0x551111,
                    footer=dict(text="React with ❌ to cancel the deletion."),
                )
            )
        )

        await alert_msg.add_reaction("❌")

        try:
            await self.bot.wait_for(
                "raw_reaction_add",
                check=lambda event: event.message_id == alert_msg.id
                and (
                    event.user_id == thread.owner_id
                    or (
                        event.member
                        and not event.member.bot
                        and (
                            (
                                perms := thread.permissions_for(event.member)
                            ).administrator
                            or perms.manage_messages
                        )
                    )
                )
                and snakecore.utils.is_emoji_equal(event.emoji, "❌"),
                timeout=300,
            )
        except asyncio.TimeoutError:
            try:
                await thread.delete()
            except discord.NotFound:
                pass
        else:
            try:
                await alert_msg.delete()
            except discord.NotFound:
                pass

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent):
        if (
            payload.parent_id != self.showcase_channel_id
            or payload.thread_id not in self.entry_post_deletion_dict
        ):
            return

        deletion_data_tuple = self.entry_post_deletion_dict[payload.thread_id]
        deletion_task = deletion_data_tuple[0]
        if not deletion_task.done():
            deletion_task.cancel()

        del self.entry_post_deletion_dict[payload.thread_id]


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT, showcase_channel_id: int, theme_color: int | discord.Color = 0
):
    await bot.add_cog(Showcase(bot, showcase_channel_id, theme_color))
