"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import datetime
import itertools
import re
import time


import discord
from discord.ext import commands
import snakecore
from snakecore.commands import flagconverter_kwargs
from snakecore.commands import UnicodeEmoji
from snakecore.commands.converters import DateTime

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


class Showcasing(BaseExtensionCog, name="showcasing"):
    """A cog for managing showcase forum channels."""

    def __init__(
        self, bot: BotT, showcase_channel_id: int, theme_color: int | discord.Color = 0
    ) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.showcase_channel_id = showcase_channel_id
        self.entry_post_deletion_dict: dict[int, tuple[asyncio.Task[None], int]] = {}

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

        def count_thread_reactions(
            thread: discord.Thread, starter_message: discord.Message
        ):
            return (
                sum(
                    reaction.count
                    for reaction in starter_message.reactions
                    if snakecore.utils.is_emoji_equal(rank_emoji, reaction.emoji)
                )
                if rank_emoji
                else sum(reaction.count for reaction in starter_message.reactions)
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
                count_thread_reactions(thread, starter_message),
            )

        thread_triples = sorted(
            [
                triple
                for thread in itertools.chain(
                    sorted(channel.threads, key=lambda t: t.id, reverse=True),
                    [
                        thread
                        async for thread in channel.archived_threads(
                            limit=amount
                            - len(channel.threads),  # subtract active threads
                            before=before,
                        )
                    ],
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
            ][:amount],
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
            f"<t:{int(discord.utils.snowflake_time(thread_triples[0][0].id).timestamp())}> "
            f"to <t:{int(discord.utils.snowflake_time(thread_triples[-1][0].id).timestamp())}>)",
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
                                else ", ".join(
                                    f"{reaction.emoji}: {reaction.count}"
                                    for reaction in starter_message.reactions
                                )
                            )
                        ),
                        value=f"{thread.jump_url}",
                        inline=False,
                    )
                )

        response_embed_dict_lists = [
            snakecore.utils.embeds.split_embed_dict(embed_dict)
        ]

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
                    response_embed_dict_lists.insert(  #  slice up the response embed dict list to fit the character limit per message
                        i + 1, response_embed_dicts_list[j : j + 1]
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
    def thread_validity_check(
        thread: discord.Thread, min_chars=32, max_chars=float("inf")
    ):
        """Checks if a thread's starter message has the right format.

        Returns
        -------
        bool:
            True/False
        """

        message = thread.starter_message

        if not message:
            return True

        search_obj = re.search(
            snakecore.utils.regex_patterns.URL, message.content or ""
        )
        link_in_msg = bool(search_obj)
        first_link_str = search_obj.group() if link_in_msg else ""

        char_length = len(message.content) + len(thread.name)

        if (
            message.content
            and (link_in_msg and char_length > len(first_link_str))
            and min_chars <= char_length < max_chars
        ):
            return True

        elif message.content and message.attachments:
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

        if not self.thread_validity_check(thread):
            deletion_datetime = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(minutes=5)
            warn_msg = await message.reply(
                "Your post must contain an attachment or text and safe links to be valid.\n\n"
                "- Attachment-only entries must be in reference to a previous post of yours.\n"
                "- Text-only posts must contain at least 32 characters (including their title "
                "and including links, but not links alone).\n\n"
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

        if not self.thread_validity_check(thread):
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
                                "characters (including their title "
                                "and including links, but not links alone).\n\n"
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
                    "(including their title and including links, but not links "
                    "alone).\n\nIf no changes are made, your post will be"
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
            self.thread_validity_check(thread)
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
    await bot.add_cog(Showcasing(bot, showcase_channel_id, theme_color))
