"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import abc
import asyncio
from collections.abc import Collection
import datetime
import enum
import itertools
import re
import time
from typing import Any, Callable, Literal, NotRequired, Protocol, TypedDict

import discord
from discord.ext import commands
import snakecore
from snakecore.commands import flagconverter_kwargs
from snakecore.commands import UnicodeEmoji
from snakecore.commands.converters import DateTime

from .utils import ShowcaseChannelConfig, validate_message

from ...base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class Showcasing(BaseExtensionCog, name="showcasing"):
    """A cog for managing showcase forum/threaded channels."""

    def __init__(
        self,
        bot: BotT,
        showcase_channels_config: Collection[ShowcaseChannelConfig],
        theme_color: int | discord.Color = 0,
    ) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.showcase_channels_config: dict[int, ShowcaseChannelConfig] = {
            showcase_channel_config["channel_id"]: showcase_channel_config
            for showcase_channel_config in showcase_channels_config
        }
        self.entry_message_deletion_dict: dict[int, tuple[asyncio.Task[None], int]] = {}

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=True)
    @commands.group(
        invoke_without_command=True,
    )
    async def showcase(self, ctx: commands.Context[BotT]):
        pass

    @showcase.command(
        name="rank",
        usage="<forum> <amount: Number> [tags: Text...] [include_tags: Text...] "
        "[exclude_tags: Text...] [before: Thread/DateTime] "
        "[after: Thread/DateTime] [rank_emoji: Emoji]",
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def showcase_rank(
        self,
        ctx: commands.Context[BotT],
        forum: discord.ForumChannel,
        *,
        amount: commands.Range[int, 0],
        include_tags: tuple[str, ...] = commands.flag(aliases=["tags"], default=()),
        exclude_tags: tuple[str, ...] = (),
        before: discord.Thread | DateTime | None = None,
        after: discord.Thread | DateTime | None = None,
        rank_emoji: UnicodeEmoji | discord.PartialEmoji | str | None = None,
    ):
        """Rank the specified showcase forum channel's posts by the number of reactions they have.

        __**Parameters:**__

        **`<forum>`**
        > The forum channel to rank.

        **`<amount>`**
        > The amount of posts to rank.

        **`[include_tags: Text...]`**
        **`[tags: Text...]`**
        > A flag for specifying the inclusionary tags to filter posts by.
        > Cannot be used with `exclude_tags`.

        **`[exclude_tags: Text...]`**
        > A flag for specifying the exlcusary tags to filter posts by.
        > Cannot be used with `include_tags`.

        **`[before: Thread/DateTime]`**
        > A flag for specifying the thread to start the ranking from.

        **`[after: Thread/DateTime]`**
        > A flag for specifying the thread to end the ranking at.

        **`[rank_emoji: Emoji]`**
        > A flag for specifying the reaction emoji to use for ranking. In omitted,
        > all used reaction emojis will be counted and summed up to calculate the rank.
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

        channel = forum

        if isinstance(rank_emoji, str):
            rank_emoji = discord.PartialEmoji(name=rank_emoji)

        if include_tags and exclude_tags:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You cannot specify both `include_tags:` and `exclude_tags:` at the same time."
                )
            )

        tags = [tag.name.lower() for tag in channel.available_tags]

        if include_tags:
            include_tags = tuple(tag.lower() for tag in include_tags)
            tags = [tag for tag in tags if tag in include_tags]

        if exclude_tags:
            exclude_tags = tuple(tag.lower() for tag in exclude_tags)
            tags = [tag for tag in tags if tag not in exclude_tags]

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            channel,
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command on the "
                    f"specified destination (<#{channel.id}>."
                )
            )

        if isinstance(before, discord.Thread) and before.parent_id != channel.id:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "`before` has to be an ID of a thread from the specified channel",
                )
            )

        if isinstance(after, discord.Thread) and after.parent_id != channel.id:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "`after` has to be an ID of a thread from the specified channel",
                )
            )

        before_ts = (
            before.replace(tzinfo=datetime.timezone.utc)
            if isinstance(before, datetime.datetime)
            else (
                discord.utils.snowflake_time(before.id)
                if isinstance(before, discord.Thread)
                else None
            )
        )

        after_ts = (
            after.replace(tzinfo=datetime.timezone.utc)
            if isinstance(after, datetime.datetime)
            else (
                discord.utils.snowflake_time(after.id)
                if isinstance(after, discord.Thread)
                else None
            )
        )

        async def count_unique_thread_reactions(
            thread: discord.Thread, starter_message: discord.Message
        ):
            if rank_emoji:
                return sum(
                    reaction.count
                    for reaction in starter_message.reactions
                    if snakecore.utils.is_emoji_equal(rank_emoji, reaction.emoji)
                )

            user_ids_by_reaction: dict[tuple[str, int], list[int]] = {}

            for i, reaction in enumerate(starter_message.reactions):
                user_ids_by_reaction[str(reaction.emoji), i] = [
                    user.id async for user in reaction.users()
                ]

            return len(
                set(itertools.chain.from_iterable(user_ids_by_reaction.values()))
            )

        async def thread_triple(thread: discord.Thread):
            try:
                starter_message = thread.starter_message or await thread.fetch_message(
                    thread.id
                )
            except discord.NotFound:
                return None

            return (
                thread,
                starter_message,
                await count_unique_thread_reactions(thread, starter_message),
            )

        max_archived_threads = max(
            amount - len(channel.threads), 0
        )  # subtract active threads

        thread_triples = sorted(  # sort triples by reaction count
            (
                sorted_thread_triples := [
                    # retrieve threads as
                    # (thread, message, reaction_count) tuples within time range
                    # in descending order
                    triple
                    for thread in itertools.chain(
                        sorted(channel.threads, key=lambda t: t.id, reverse=True),
                        (
                            [
                                thread
                                async for thread in channel.archived_threads(
                                    limit=max_archived_threads,
                                )
                            ]
                            if max_archived_threads
                            else (())
                        ),
                    )
                    if (
                        before_ts is None
                        or discord.utils.snowflake_time(thread.id) < before_ts
                    )
                    and (
                        after_ts is None
                        or discord.utils.snowflake_time(thread.id) > after_ts
                    )
                    and (triple := (await thread_triple(thread)))
                    and any(tag.name.lower() in tags for tag in triple[0].applied_tags)
                ][:amount]
            ),
            key=lambda tup: tup[2],
            reverse=True,
        )

        if not thread_triples:
            raise commands.CommandInvokeError(
                commands.CommandError("No threads found in the specified channel.")
            )

        embed_dict = {
            "title": f"Showcase Rankings for {channel.mention} Posts by Emoji\n"
            f"({len(thread_triples)} selected, from "
            "<t:"
            + str(
                int(
                    discord.utils.snowflake_time(
                        sorted_thread_triples[-1][0].id
                    ).timestamp()
                )
            )
            + "> "
            f"to <t:"
            + str(
                int(
                    discord.utils.snowflake_time(
                        sorted_thread_triples[0][0].id
                    ).timestamp()
                )
            )
            + ">, based on unique reactions)",
            "color": self.theme_color.value,
            "fields": [],
        }

        for i, triple in enumerate(thread_triples):
            thread, starter_message, thread_reactions_count = triple
            if thread_reactions_count:
                embed_dict["fields"].append(
                    dict(
                        name=(
                            f"{i + 1}. "
                            + (
                                f"{rank_emoji}: {thread_reactions_count}"
                                if rank_emoji
                                else f"{thread_reactions_count}: Unique | "
                                + ", ".join(
                                    f"{reaction.emoji}: {reaction.count}"
                                    for reaction in starter_message.reactions
                                )
                            )
                        ),
                        value=f"{thread.jump_url}",
                        inline=False,
                    )
                )

        # divide embed dict into lists of multiple embed dicts if necessary
        response_embed_dict_lists = [
            snakecore.utils.embeds.split_embed_dict(embed_dict)
        ]

        # group those lists based on the total character count of the embeds
        for i in range(len(response_embed_dict_lists)):
            response_embed_dicts_list = response_embed_dict_lists[i]
            total_char_count = 0
            for j in range(len(response_embed_dicts_list)):
                response_embed_dict = response_embed_dicts_list[j]
                if (
                    total_char_count
                    + snakecore.utils.embeds.check_embed_dict_char_count(
                        response_embed_dict
                    )
                ) > snakecore.utils.embeds.EMBED_TOTAL_CHAR_LIMIT:
                    response_embed_dict_lists.insert(
                        # slice up the response embed dict list to fit the character
                        # limit per message
                        i + 1,
                        response_embed_dicts_list[j : j + 1],
                    )
                    response_embed_dict_lists[i] = response_embed_dicts_list[:j]
                else:
                    total_char_count += (
                        snakecore.utils.embeds.check_embed_dict_char_count(
                            response_embed_dict
                        )
                    )

        for response_embed_dicts_list in response_embed_dict_lists:
            await ctx.send(
                embeds=[
                    discord.Embed.from_dict(embed_dict)
                    for embed_dict in response_embed_dicts_list
                ]
            )

    @staticmethod
    async def delete_bad_message_with_thread(
        message: discord.Message, delay: float = 0.0
    ):
        """A function to pardon a bad message and its post/thread (if present) with a grace period. If this coroutine is not cancelled during the
        grace period specified in `delay` in seconds, it will delete `thread`, if possible.
        """
        try:
            await asyncio.sleep(delay)  # allow cancelling during delay
        except asyncio.CancelledError:
            return

        else:
            try:
                if isinstance(message.channel, discord.Thread):
                    await message.channel.delete()

                await message.delete()
            except discord.NotFound:
                # don't error here if thread and/or message were already deleted
                pass

    def showcase_message_validity_check(
        self,
        message: discord.Message,
    ) -> tuple[bool, str | None]:
        """Checks if a showcase message has the right format.

        Returns
        -------
        tuple[bool, str | None]:
            A tuple containing a boolean indicating whether the message is valid or not, and a string describing the reason why it is invalid if it is not valid.
        """
        return validate_message(
            message,
            self.showcase_channels_config[message.channel.id]["showcase_message_rules"],
        )

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if not (
            isinstance(thread.parent, discord.ForumChannel)
            and thread.parent_id in self.showcase_channels_config
        ):
            return

        try:
            message = thread.starter_message or await thread.fetch_message(thread.id)
        except discord.NotFound:
            return

        is_valid, reason = self.showcase_message_validity_check(message)

        if not is_valid:
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=5)
            warn_msg = await message.reply(
                "### Invalid showcase message\n\n"
                f"{reason}\n\n"
                " If no changes are made, your message (and its thread/post) will be "
                f"deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
            )
            self.entry_message_deletion_dict[message.id] = (
                asyncio.create_task(
                    self.delete_bad_message_with_thread(message, delay=300)
                ),
                warn_msg.id,
            )

    async def prompt_author_for_feedback_thread(self, message: discord.Message):
        assert (
            message.guild
            and isinstance(message.channel, discord.TextChannel)
            and self.bot.user
            and (bot_member := message.guild.get_member(self.bot.user.id))
        )
        bot_perms = message.channel.permissions_for(bot_member)

        if not bot_perms.create_public_threads:
            return

        deletion_datetime = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(minutes=1)

        alert_msg = await message.reply(
            content=f"Need a feedback thread?\n\n-# This message will be deleted "
            + snakecore.utils.create_markdown_timestamp(deletion_datetime, "R")
            + ".",
        )

        await alert_msg.add_reaction("✅")
        await alert_msg.add_reaction("❌")

        try:
            event = await self.bot.wait_for(
                "raw_reaction_add",
                check=lambda event: event.message_id == alert_msg.id
                and (
                    event.user_id == message.author.id
                    or (
                        event.member
                        and (not event.member.bot)
                        and (
                            (
                                perms := message.channel.permissions_for(event.member)
                            ).administrator
                            or perms.manage_messages
                        )
                    )
                )
                and (
                    snakecore.utils.is_emoji_equal(event.emoji, "✅")
                    or snakecore.utils.is_emoji_equal(event.emoji, "❌")
                ),
                timeout=60,
            )
        except asyncio.TimeoutError:
            try:
                await alert_msg.delete()
            except discord.NotFound:
                pass
        else:
            if snakecore.utils.is_emoji_equal(event.emoji, "✅"):
                try:
                    await message.create_thread(
                        name=(
                            f"Feedback for "
                            + f"@{message.author.name} | {str(message.author.id)[-6:]}"
                        )[:100],
                        auto_archive_duration=(
                            self.showcase_channels_config[message.channel.id].get(
                                "default_auto_archive_duration", 60
                            )
                            if bot_perms.manage_threads
                            else discord.utils.MISSING
                        ),  # type: ignore
                        slowmode_delay=(
                            self.showcase_channels_config[message.channel.id].get(
                                "default_thread_slowmode_delay",
                            )
                            if bot_perms.manage_threads
                            else None
                        ),  # type: ignore
                        reason=f"A '#{message.channel.name}' message "
                        "author requested a feedback thread.",
                    )
                except discord.HTTPException:
                    pass

            try:
                await alert_msg.delete()
            except discord.NotFound:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not (
            (not message.author.bot)
            and (
                isinstance(message.channel, discord.TextChannel)
                and message.channel.id
                in self.showcase_channels_config  # is message in a showcase text channel
            )
        ):
            return

        is_valid, reason = self.showcase_message_validity_check(message)

        if is_valid:
            await self.prompt_author_for_feedback_thread(message)
        else:
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=5)
            warn_msg = await message.reply(
                "### Invalid showcase message\n\n"
                f"{reason}\n\n"
                " If no changes are made, your message (and its thread/post) will be "
                f"deleted {snakecore.utils.create_markdown_timestamp(deletion_datetime, 'R')}."
            )
            self.entry_message_deletion_dict[message.id] = (
                asyncio.create_task(
                    self.delete_bad_message_with_thread(message, delay=300)
                ),
                warn_msg.id,
            )

    @commands.Cog.listener()
    async def on_message_edit(self, old: discord.Message, new: discord.Message):
        if not (
            (not new.author.bot)
            and (
                new.channel.id
                in self.showcase_channels_config  # is message in a showcase text channel
                or (
                    isinstance(new.channel, discord.Thread)
                    and new.channel.parent_id in self.showcase_channels_config
                    and new.id == new.channel.id
                )  # is starter message of a post in a showcase forum
            )
            and (
                new.content != old.content
                or new.embeds != old.embeds
                or new.attachments != old.attachments
            )
        ):
            return

        is_valid, reason = self.showcase_message_validity_check(new)

        if not is_valid:
            if new.id in self.entry_message_deletion_dict:
                deletion_data_tuple = self.entry_message_deletion_dict[new.id]
                deletion_task = deletion_data_tuple[0]
                if deletion_task.done():
                    del self.entry_message_deletion_dict[new.id]
                else:
                    try:
                        deletion_task.cancel()  # try to cancel deletion after noticing edit by sender

                        # fetch warning message from inside a post or refrencing the target message in a text showcase channel
                        warn_msg = await new.channel.fetch_message(
                            deletion_data_tuple[1]
                        )
                        deletion_datetime = datetime.datetime.now(
                            datetime.timezone.utc
                        ) + datetime.timedelta(minutes=5)
                        await warn_msg.edit(
                            content=(
                                "### Invalid showcase message\n\n"
                                "Your edited showcase message is invalid.\n\n"
                                f"{reason}\n\n"
                                " If no changes are made, your post will be "
                                f"deleted "
                                + snakecore.utils.create_markdown_timestamp(
                                    deletion_datetime, "R"
                                )
                                + "."
                            )
                        )
                        self.entry_message_deletion_dict[new.id] = (
                            asyncio.create_task(
                                self.delete_bad_message_with_thread(new, delay=300)
                            ),
                            warn_msg.id,
                        )
                    except (
                        discord.NotFound
                    ):  # cancelling didn't work, warning and post were already deleted
                        if new.id in self.entry_message_deletion_dict:
                            del self.entry_message_deletion_dict[new.id]

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
                    "(including their title and including links, but not links "
                    "alone).\n\nIf no changes are made, your post will be"
                    f" deleted "
                    + snakecore.utils.create_markdown_timestamp(deletion_datetime, "R")
                    + "."
                )

                self.entry_message_deletion_dict[new.id] = (
                    asyncio.create_task(
                        self.delete_bad_message_with_thread(new, delay=300)
                    ),
                    warn_msg.id,
                )

        elif (
            is_valid
        ) and new.id in self.entry_message_deletion_dict:  # an invalid entry was corrected
            deletion_data_tuple = self.entry_message_deletion_dict[new.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():  # too late to do anything
                try:
                    deletion_task.cancel()  # try to cancel deletion after noticing valid edit by sender
                    await discord.PartialMessage(
                        channel=new.channel, id=deletion_data_tuple[1]
                    ).delete()
                except (
                    discord.NotFound
                ):  # cancelling didn't work, warning was already deleted
                    pass

            if new.id in self.entry_message_deletion_dict:
                del self.entry_message_deletion_dict[new.id]

            if isinstance(new.channel, discord.TextChannel):
                try:
                    # check if a feedback thread was previously created for this message
                    _ = new.channel.get_thread(
                        new.id
                    ) or await new.channel.guild.fetch_channel(new.id)
                except discord.NotFound:
                    pass
                else:
                    return

                await self.prompt_author_for_feedback_thread(new)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not (
            (not message.author.bot)
            and (
                message.channel.id
                in self.showcase_channels_config  # is message in a showcase text channel
                or (
                    isinstance(message.channel, discord.Thread)
                    and message.channel.parent_id in self.showcase_channels_config
                    and message.id == message.channel.id
                )  # is starter message of a post in a showcase forum
            )
        ):
            return

        if (
            message.id in self.entry_message_deletion_dict
        ):  # for case where user deletes their bad entry by themselves
            deletion_data_tuple = self.entry_message_deletion_dict[message.id]
            deletion_task = deletion_data_tuple[0]
            if not deletion_task.done():
                deletion_task.cancel()
                try:
                    await discord.PartialMessage(
                        channel=message.channel, id=deletion_data_tuple[1]
                    ).delete()
                except discord.NotFound:
                    # warning message and post were already deleted
                    pass

            del self.entry_message_deletion_dict[message.id]

        alert_destination = message.channel

        if isinstance(message.channel, discord.TextChannel):
            try:
                alert_destination = message.channel.get_thread(
                    message.id
                ) or await message.channel.guild.fetch_channel(message.id)
            except discord.NotFound:
                return

        if not isinstance(alert_destination, discord.Thread):
            return

        alert_msg = await alert_destination.send(
            embed=discord.Embed.from_dict(
                dict(
                    title="Post/Thread scheduled for deletion",
                    description=(
                        "This post/thread is scheduled for deletion:\n\n"
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
                    event.user_id == message.author.id
                    or (
                        event.member
                        and (not event.member.bot)
                        and (
                            (
                                perms := message.channel.permissions_for(event.member)
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
                await alert_destination.delete()
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
            payload.parent_id not in self.showcase_channels_config
            or payload.thread_id not in self.entry_message_deletion_dict
        ):
            return

        deletion_data_tuple = self.entry_message_deletion_dict[payload.thread_id]
        deletion_task = deletion_data_tuple[0]
        if not deletion_task.done():
            deletion_task.cancel()

        del self.entry_message_deletion_dict[payload.thread_id]
