"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import discord
from discord.ext import commands
import snakecore
from typing import TypedDict, Collection
from collections import OrderedDict
import logging

from ..base import BaseExtensionCog

# Define the type for the bot, supporting both Bot and AutoShardedBot from snakecore
BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot

logger = logging.getLogger(__name__)

fetched_attachments: dict[int, bytes] = {}


async def fetch_attachment(attachment: discord.Attachment, cache: bool = True) -> bytes:
    if cache and attachment.id in fetched_attachments:
        logger.debug(f"Fetched attachment from cache: {attachment.id}")
        return fetched_attachments[attachment.id]
    data = await attachment.read()
    if cache:
        fetched_attachments[attachment.id] = data
    logger.debug(f"Fetched attachment from source: {attachment.id}")
    return data


async def crosspost_cmp(message: discord.Message, other: discord.Message) -> bool:
    """
    Compare two messages to determine if they are crossposts or duplicates.

    Args:
        message (discord.Message): The first message to compare.
        other (discord.Message): The second message to compare.

    Returns:
        bool: True if the messages are similar enough to be considered
        duplicates, otherwise False.
    """

    similarity_score = None
    matching_attachments = None

    have_content = message.content and other.content
    have_attachments = message.attachments and other.attachments

    logger.debug(
        f"Comparing messages {message.jump_url} and {other.jump_url} from {message.author.name}"
    )

    if have_content:
        hamming_score = sum(
            x != y for x, y in zip(message.content, other.content)
        ) / max(len(message.content), len(other.content))
        similarity_score = min(max(0, 1 - hamming_score), 1)
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
    message_to_alert: dict[int, int]  # Mapping from message ID to alert message ID


class AntiCrosspostCog(BaseExtensionCog, name="anti-crosspost"):
    def __init__(
        self,
        bot: BotT,
        channel_ids: Collection[int],
        crosspost_timedelta_threshold: int,
        message_length_threshold: int,
        max_tracked_users: int,
        max_tracked_message_groups_per_user: int,
        theme_color: int | discord.Color = 0,
    ) -> None:
        """
        Initialize the AntiCrosspostCog.

        Args:
            bot (BotT): The bot instance.
            channel_ids (Collection[int]): Collection of channel IDs to monitor.
            crosspost_timedelta_threshold (int): Minimum time difference between messages to not be considered crossposts.
            message_length_threshold (int): Minimum length of a text-only message to be considered.
            max_tracked_users (int): Maximum number of users to track.
            max_tracked_message_groups_per_user (int): Maximum number of message
                groups to track per user.
            theme_color (int | discord.Color): Theme color for the bot's responses.
        """
        super().__init__(bot, theme_color)
        self.channel_ids = set(channel_ids)
        self.crossposting_cache: OrderedDict[int, UserCrosspostCache] = OrderedDict()

        self.crosspost_timedelta_threshold = crosspost_timedelta_threshold
        self.max_tracked_users = max_tracked_users
        self.max_tracked_message_groups_per_user = max_tracked_message_groups_per_user
        self.message_length_threshold = message_length_threshold

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Event listener for new messages.

        Args:
            message (discord.Message): The message object.
        """
        if (
            message.author.bot
            or not self._is_valid_channel(message.channel)  # type: ignore
            or message.type != discord.MessageType.default
            or (
                message.content
                and not message.attachments
                and len(message.content) < self.message_length_threshold
            )
        ):
            return

        logger.debug(f"Received message from {message.author.name}: {message.jump_url}")

        # Attempt to enforce the cache size limit
        for user_id in list(self.crossposting_cache.keys()):
            if len(self.crossposting_cache) <= self.max_tracked_users:
                break

            user_cache = self.crossposting_cache[user_id]
            if not any(len(group) > 1 for group in user_cache["message_groups"]):
                self.crossposting_cache.pop(user_id)
                logger.debug(f"Removed user {user_id} from cache to enforce size limit")

        # Initialize cache for new users
        if message.author.id not in self.crossposting_cache:
            self.crossposting_cache[message.author.id] = UserCrosspostCache(
                message_groups=[[message]],
                message_to_alert={},
            )
            logger.debug(f"Initialized cache for new user {message.author.name}")
        else:
            user_cache = self.crossposting_cache[message.author.id]
            logger.debug(f"Checking for crossposts for user {message.author.name}")

            # Check for crossposts or duplicates in existing message groups
            for messages in user_cache["message_groups"]:
                for existing_message in messages:
                    if (
                        await crosspost_cmp(message, existing_message)
                        and message.created_at.timestamp()
                        - existing_message.created_at.timestamp()
                        <= self.crosspost_timedelta_threshold
                    ):
                        messages.append(message)
                        logger.debug(
                            f"Found crosspost for user {message.author.name}, message URL {message.jump_url}!!!!!!!!!!"
                        )

                        try:
                            alert_message = await message.reply(
                                "This message is a recent crosspost/duplicate among the following messages: "
                                + ", ".join([m.jump_url for m in messages])
                                + ".\n\nPlease delete all duplicate messages."
                            )
                            user_cache["message_to_alert"][
                                message.id
                            ] = alert_message.id
                            logger.debug(f"Sent alert message for crosspost URL {message.jump_url}")
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
        """
        Event listener for deleted messages.

        Args:
            message (discord.Message): The message object.
        """
        if not self._is_valid_channel(message.channel):  # type: ignore
            return

        if message.author.id not in self.crossposting_cache:
            return

        user_cache = self.crossposting_cache[message.author.id]
        stale_alert_message_ids: list[int] = []

        for messages in user_cache["message_groups"]:
            for j in range(len(messages) - 1, -1, -1):
                if message.id == messages[j].id:
                    del messages[j]
                    if message.id in user_cache["message_to_alert"]:
                        stale_alert_message_ids.append(
                            user_cache["message_to_alert"].pop(message.id)
                        )
                    logger.debug(
                        f"Removed message {message.jump_url} from user {message.author.name}'s cache due to deletion"
                    )
                    break

            # Mark last alert message for this crosspost group as stale if the group
            # has only one message
            if len(messages) == 1 and messages[0].id in user_cache["message_to_alert"]:
                stale_alert_message_ids.append(
                    user_cache["message_to_alert"].pop(messages[0].id)
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

    def _is_valid_channel(self, channel: discord.abc.GuildChannel) -> bool:
        """
        Check if a channel is valid based on the configured channel IDs.

        Args:
            channel (discord.abc.GuildChannel): The channel to check.

        Returns:
            bool: True if the channel is valid, otherwise False.
        """
        if isinstance(channel, discord.abc.GuildChannel):
            # Check if the channel ID or category ID is in the monitored channel IDs
            if (
                channel.id in self.channel_ids
                or channel.category_id in self.channel_ids
            ):
                return True

            # If the channel is a thread, check if the parent or the parent's category ID is in the monitored channel IDs
            if isinstance(channel, discord.Thread):
                if channel.parent_id in self.channel_ids:
                    return True
                if channel.parent and channel.parent.category_id in self.channel_ids:
                    return True

        return False


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    channel_ids: Collection[int],
    max_tracked_users: int = 10,
    max_tracked_message_groups_per_user: int = 10,
    crosspost_timedelta_threshold: int = 86400,
    message_length_threshold: int = 64,
    theme_color: int | discord.Color = 0,
):
    """
    Setup function to add the AntiCrosspostCog to the bot.

    Args:
        bot (BotT): The bot instance.
        channel_ids (Collection[int]): Collection of channel IDs to monitor.
        max_tracked_users (int): Maximum number of users to track.
        max_tracked_message_groups_per_user (int): Maximum number of message groups to track per user.
        crosspost_timedelta_threshold (int): Minimum time difference between messages to not be considered crossposts.
        message_length_threshold (int): Minimum length of a text-only message to be considered.
        theme_color (int | discord.Color): Theme color for the bot's responses.
    """
    await bot.add_cog(
        AntiCrosspostCog(
            bot,
            channel_ids,
            crosspost_timedelta_threshold,
            message_length_threshold,
            max_tracked_users,
            max_tracked_message_groups_per_user,
            theme_color,
        )
    )
