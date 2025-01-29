"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import discord
from discord.ext import commands
import snakecore
from typing import TypedDict, Collection, cast
from collections import OrderedDict
import logging

from ..base import BaseExtensionCog

# Define the type for the bot, supporting both Bot and AutoShardedBot from snakecore
BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)

logger = logging.getLogger(__name__)

fetched_attachments: OrderedDict[int, bytes] = OrderedDict()


def hamming_distance_padded(str1, str2):
    # Pad the shorter string with spaces to match the lengths
    max_len = max(len(str1), len(str2))
    str1 = str1.ljust(max_len)
    str2 = str2.ljust(max_len)

    return sum(c1 != c2 for c1, c2 in zip(str1, str2))


def hamming_similarity_score(str1, str2):
    distance = hamming_distance_padded(str1, str2)
    max_len = max(len(str1), len(str2))
    similarity_ratio = (max_len - distance) / max_len
    return similarity_ratio


async def fetch_attachment(attachment: discord.Attachment, cache: bool = True) -> bytes:
    if cache and attachment.id in fetched_attachments:
        logger.debug(f"Fetched attachment from cache: {attachment.id}")
        return fetched_attachments[attachment.id]
    data = await attachment.read()
    if cache:
        fetched_attachments[attachment.id] = data
    logger.debug(f"Fetched attachment from source: {attachment.id}")

    if len(fetched_attachments) > 100:
        fetched_attachments.popitem(last=False)

    return data


async def crosspost_cmp(message: discord.Message, other: discord.Message) -> bool:
    """
    Compare two messages to determine if they are crossposts or duplicates.

    Parameters
    ----------
    message : discord.Message
        The first message to compare.
    other : discord.Message
        The second message to compare.

    Returns
    -------
    bool
        True if the messages are similar enough to be considered duplicates, otherwise False.
    """

    similarity_score = None
    matching_attachments = None

    have_content = message.content and other.content
    have_attachments = message.attachments and other.attachments

    logger.debug(
        f"Comparing messages {message.jump_url} and {other.jump_url} from {message.author.name}"
    )

    if have_content:
        similarity_score = hamming_similarity_score(message.content, other.content)
        logger.debug(f"Computed similarity score for content: {similarity_score}")
    else:
        similarity_score = 0

    if have_attachments:
        try:
            matching_attachments = all(
                [
                    att1.filename == att2.filename
                    and att1.size == att2.size
                    and att1.size < 2**20 * 8
                    and att2.size < 2**20 * 8
                    and att1.content_type == att2.content_type
                    and (await fetch_attachment(att1) == await fetch_attachment(att2))
                    for att1, att2 in zip(
                        sorted(message.attachments, key=lambda x: (x.filename, x.size)),
                        sorted(other.attachments, key=lambda x: (x.filename, x.size)),
                    )
                ]
            )
            logger.debug(f"Attachment comparison result: {matching_attachments}")
        except discord.HTTPException as e:
            logger.debug(f"HTTPException during attachment comparison: {e}")
            matching_attachments = False
    else:
        matching_attachments = False

    if not have_content and (message.content or other.content):
        return False
    elif not have_attachments and (message.attachments or other.attachments):
        return False
    elif have_content and have_attachments:
        return similarity_score > 0.80 and matching_attachments
    elif have_content:
        return similarity_score > 0.80
    elif have_attachments:
        return matching_attachments

    return False


class UserCrosspostCache(TypedDict):
    """
    A TypedDict for caching user messages and alert message IDs.
    """

    message_groups: list[list[discord.Message]]
    message_to_alert_map: dict[int, int]  # Mapping from message ID to alert message ID


class AntiCrosspostCog(BaseExtensionCog, name="anti-crosspost"):
    def __init__(
        self,
        bot: BotT,
        channel_ids: Collection[int],
        exclude_alert_channel_ids: Collection[int] | None,
        crosspost_timedelta_threshold: int,
        same_channel_message_length_threshold: int,
        cross_channel_message_length_threshold: int,
        max_tracked_users: int,
        max_tracked_message_groups_per_user: int,
        theme_color: int | discord.Color = 0,
    ) -> None:
        """
        Initialize the AntiCrosspostCog.

        Parameters
        ----------
        bot : BotT
            The bot instance.
        channel_ids : Collection[int]
            Collection of channel IDs to watch.
        exclude_alert_channel_ids : Collection[int] or None
            Collection of channel IDs to exclude from alerting.
        crosspost_timedelta_threshold : int
            Minimum time difference between messages to not be considered crossposts.
        same_channel_message_length_threshold : int
            Minimum length of a text-only message to be considered if the messages are in the same channel.
        cross_channel_message_length_threshold : int
            Minimum length of a text-only message to be considered if the messages are in different channels.
        max_tracked_users : int
            Maximum number of users to track.
        max_tracked_message_groups_per_user : int
            Maximum number of message groups to track per user.
        theme_color : int or discord.Color, optional
            Theme color for the bot's responses, by default 0.
        """
        super().__init__(bot, theme_color)
        self.channel_ids = set(channel_ids)
        self.exclude_alert_channel_ids = set(exclude_alert_channel_ids or ())
        self.crossposting_cache: OrderedDict[int, UserCrosspostCache] = OrderedDict()

        self.crosspost_timedelta_threshold = crosspost_timedelta_threshold
        self.max_tracked_users = max_tracked_users
        self.max_tracked_message_groups_per_user = max_tracked_message_groups_per_user
        self.same_channel_message_length_threshold = (
            same_channel_message_length_threshold
        )
        self.cross_channel_message_length_threshold = (
            cross_channel_message_length_threshold
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.author.bot
            or not await self._check_channel(message.channel, self.channel_ids)  # type: ignore
            or message.type != discord.MessageType.default
            or (
                message.content
                and not message.attachments
                and (
                    len(message.content)
                    < min(
                        self.same_channel_message_length_threshold,
                        self.cross_channel_message_length_threshold,
                    )
                )
            )
        ):
            return

        logger.debug(
            f"Received noteworthy message from {message.author.name}: {message.jump_url}"
        )

        # Attempt to enforce the cache size limit
        for user_id in list(self.crossposting_cache.keys()):
            if len(self.crossposting_cache) <= self.max_tracked_users:
                break

            user_cache = self.crossposting_cache[user_id]
            if not any(len(group) > 1 for group in user_cache["message_groups"]):
                # Remove user from cache if they dont have any crossposts
                self.crossposting_cache.pop(user_id)
                logger.debug(f"Removed user {user_id} from cache to enforce size limit")

        # Initialize cache for new users
        if message.author.id not in self.crossposting_cache:
            self.crossposting_cache[message.author.id] = UserCrosspostCache(
                message_groups=[[message]],
                message_to_alert_map={},
            )
            logger.debug(f"Initialized cache for new user {message.author.name}")
        else:
            user_cache = self.crossposting_cache[message.author.id]
            logger.debug(f"Checking for crossposts for user {message.author.name}")

            # Check for crossposts or duplicates in existing message groups
            for messages in user_cache["message_groups"]:
                for existing_message in messages:
                    if message.content and (
                        (
                            message.channel.id == existing_message.channel.id
                            and len(message.content)
                            < self.same_channel_message_length_threshold
                        )
                        or (
                            message.channel.id != existing_message.channel.id
                            and len(message.content)
                            < self.cross_channel_message_length_threshold
                        )
                    ):
                        # enforce same-channel and cross-channel message length thresholds
                        # required in order for them to be considered crossposts
                        continue

                    elif (
                        await crosspost_cmp(message, existing_message)
                        and message.created_at.timestamp()
                        - existing_message.created_at.timestamp()
                        <= self.crosspost_timedelta_threshold
                    ):
                        messages.append(message)
                        logger.debug(
                            f"Found crosspost for user {message.author.name}, message URL {message.jump_url}!!!!!!!!!!"
                        )
                        alert_channel = cast(MessageableGuildChannel, message.channel)
                        if (
                            self.exclude_alert_channel_ids
                            and not await self._check_channel(
                                alert_channel, deny=self.exclude_alert_channel_ids
                            )
                        ):
                            # Attempt to find the next best channel to alert in
                            print([msg.content for msg in messages[:-1]])
                            for message in reversed(messages[:-1]):
                                alert_channel = cast(
                                    MessageableGuildChannel, message.channel
                                )
                                if await self._check_channel(
                                    alert_channel, deny=self.exclude_alert_channel_ids
                                ):
                                    break
                            else:
                                logger.debug(
                                    f"No allowed alerting channel for user {message.author.name} found"
                                )
                                break  # Don't issue an alert if not possible

                        if message.id in user_cache["message_to_alert_map"]:
                            logger.debug(
                                f"Message {message.id} is already being alerted for user {message.author.name}"
                            )
                            break  # Don't issue an alert if already alerted

                        try:
                            alert_message = await alert_channel.send(
                                "This message is a recent crosspost/duplicate among the following messages: "
                                + ", ".join([m.jump_url for m in messages])
                                + ".\n\nPlease delete all duplicate messages.",
                                reference=message,
                            )
                            user_cache["message_to_alert_map"][
                                message.id
                            ] = alert_message.id
                            logger.debug(
                                f"Sent alert message for crosspost URL {message.jump_url}"
                            )
                        except discord.HTTPException as e:
                            logger.debug(f"Failed to send alert message: {e}")
                        break
                else:
                    continue
                break
            else:
                user_cache["message_groups"].append([message])
                logger.debug(
                    f"Added message to new group for user {message.author.name}"
                )

                # Remove oldest message groups if limit is exceeded and the group is too small
                if (
                    len(user_cache["message_groups"])
                    > self.max_tracked_message_groups_per_user
                ):
                    for i, messages in reversed(
                        tuple(enumerate(user_cache["message_groups"]))
                    ):
                        if len(messages) < 2:
                            user_cache["message_groups"].pop(i)
                            logger.debug(
                                f"Removed oldest message group for user {message.author.name}"
                            )
                            break

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not await self._check_channel(message.channel, self.channel_ids):  # type: ignore
            return

        if message.author.id not in self.crossposting_cache:
            return

        user_cache = self.crossposting_cache[message.author.id]
        stale_alert_message_ids: list[int] = []

        for messages in user_cache["message_groups"]:
            for j in range(len(messages) - 1, -1, -1):
                if message.id == messages[j].id:
                    del messages[j]
                    if message.id in user_cache["message_to_alert_map"]:
                        stale_alert_message_ids.append(
                            user_cache["message_to_alert_map"].pop(message.id)
                        )
                    logger.debug(
                        f"Removed message {message.jump_url} from user {message.author.name}'s cache due to deletion"
                    )
                    break

            # Mark last alert message for this crosspost group as stale if the group
            # has only one message
            if (
                len(messages) == 1
                and messages[0].id in user_cache["message_to_alert_map"]
            ):
                stale_alert_message_ids.append(
                    user_cache["message_to_alert_map"].pop(messages[0].id)
                )

        # Delete stale alert messages
        for alert_message_id in stale_alert_message_ids:
            try:
                await discord.PartialMessage(
                    channel=message.channel, id=alert_message_id
                ).delete()
                logger.debug(f"Deleted stale alert message ID {alert_message_id}")
            except (discord.NotFound, discord.Forbidden) as e:
                logger.debug(
                    f"Failed to delete alert message ID {alert_message_id}: {e}"
                )

    @staticmethod
    async def _check_channel(
        channel: discord.abc.GuildChannel | discord.Thread,
        allow: Collection[int] = (),
        deny: Collection[int] = (),
    ) -> bool:
        """
        Check if a guild channel or thread is allowed or denied for something based on the provided allow and deny lists.

        Parameters
        ----------
        channel : discord.abc.GuildChannel | discord.Thread
            The channel to check.
        allow : Collection[int], optional
            Collection of channel IDs to allow, by default ()
        deny : Collection[int], optional
            Collection of channel IDs to deny, by default ()

        Returns
        -------
            bool: True if the channel is allowed, False if it is denied, and None if neither is allowed.
        """

        if not (allow or deny):
            raise ValueError("Either 'allow' or 'deny' must be provided")

        result = False

        if isinstance(channel, discord.abc.GuildChannel):
            # Check if the channel ID or category ID is in the monitored channel IDs
            result = (
                bool(allow) and (channel.id in allow or channel.category_id in allow)
            ) or not (
                bool(deny) and (channel.id in deny or channel.category_id in deny)
            )

        # If the channel is a thread, check if the parent or the parent's category ID is in the monitored channel IDs
        elif isinstance(channel, discord.Thread):
            if not (
                result := (bool(allow) and channel.parent_id in allow)
                or not (bool(deny) and channel.parent_id in deny)
            ):
                try:
                    parent = (
                        channel.parent
                        or channel.guild.get_channel(channel.parent_id)
                        or await channel.guild.fetch_channel(channel.parent_id)
                    )
                except discord.NotFound:
                    pass
                else:
                    result = (bool(allow) and parent.category_id in allow) or not (
                        bool(deny) and parent.category_id in deny
                    )

        return result


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    channel_ids: Collection[int],
    exclude_alert_channel_ids: Collection[int] | None = None,
    max_tracked_users: int = 10,
    max_tracked_message_groups_per_user: int = 10,
    crosspost_timedelta_threshold: int = 86400,
    same_channel_message_length_threshold: int = 64,
    cross_channel_message_length_threshold: int = 16,
    theme_color: int | discord.Color = 0,
):
    """
    Setup function to add the AntiCrosspostCog to the bot.

    Parameters
    ----------
    bot : BotT
        The bot instance.
    channel_ids : Collection[int]
        Collection of channel IDs to watch.
    exclude_alert_channel_ids : Collection[int] or None, optional
        Collection of channel IDs to exclude from alerting, by default None
    max_tracked_users : int, optional
        Maximum number of users to track, by default 10
    max_tracked_message_groups_per_user : int, optional
        Maximum number of message groups to track per user, by default 10
    crosspost_timedelta_threshold : int, optional
        Minimum time difference between messages to not be considered crossposts, by default 86400
    same_channel_message_length_threshold : int, optional
        Minimum length of a text-only message to be considered if the messages are in the same channel, by default 64
    cross_channel_message_length_threshold : int, optional
        Minimum length of a text-only message to be considered if the messages are in different channels, by default 16
    """
    await bot.add_cog(
        AntiCrosspostCog(
            bot,
            channel_ids,
            exclude_alert_channel_ids,
            crosspost_timedelta_threshold,
            same_channel_message_length_threshold,
            cross_channel_message_length_threshold,
            max_tracked_users,
            max_tracked_message_groups_per_user,
            theme_color,
        )
    )
