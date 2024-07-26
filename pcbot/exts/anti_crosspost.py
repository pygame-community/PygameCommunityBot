"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import discord
from discord.ext import commands
import snakecore
from typing import TypedDict, Collection
from collections import OrderedDict

from ..base import BaseExtensionCog

# Define the type for the bot, supporting both Bot and AutoShardedBot from snakecore
BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


def crosspost_cmp(message: discord.Message, other: discord.Message) -> bool:
    """
    Compare two messages to determine if they are crossposts or duplicates.

    Args:
        message (discord.Message): The first message to compare.
        other (discord.Message): The second message to compare.

    Returns:
        bool: True if the messages are similar enough to be considered 
        duplicates, otherwise False.
    """
    if not message.content or not other.content:
        return False

    hamming_score = sum(x != y for x, y in zip(message.content, other.content)) / max(
        len(message.content), len(other.content)
    )

    return hamming_score < 0.20 or any(
        att1.filename == att2.filename and att1.size == att2.size
        for att1, att2 in zip(message.attachments, other.attachments)
    )


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
            message_length_threshold (int): Minimum length of a message to be considered.
            max_tracked_users (int): Maximum number of users to track.
            max_tracked_message_groups_per_user (int): Maximum number of message
                groups to track per user.
            theme_color (int | discord.Color): Theme color for the bot's responses.
        """
        super().__init__(bot, theme_color)
        self.channel_ids = set(channel_ids)
        self.crossposting_cache: OrderedDict[int, UserCrosspostCache] = OrderedDict()

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
            or not self._is_valid_channel(message.channel) # type: ignore
            or message.type != discord.MessageType.default
            or (
                len(message.content) < self.message_length_threshold
                and not message.attachments
            )
        ):
            return

        # Initialize cache for new users
        if message.author.id not in self.crossposting_cache:
            self.crossposting_cache[message.author.id] = UserCrosspostCache(
                message_groups=[[message]],
                message_to_alert={},
            )
        else:
            # Remove oldest user if the limit is exceeded
            if len(self.crossposting_cache) > self.max_tracked_users:
                self.crossposting_cache.popitem(last=False)

        user_cache = self.crossposting_cache[message.author.id]

        # Remove old message groups if limit is exceeded and the oldest group is too small
        if (
            len(user_cache["message_groups"]) > self.max_tracked_message_groups_per_user
            and len(user_cache["message_groups"][0]) < 2
        ):
            user_cache["message_groups"].pop(0)

        # Check for crossposts or duplicates in existing message groups
        for messages in user_cache["message_groups"]:
            for existing_message in messages:
                if message.channel.id != existing_message.channel.id and crosspost_cmp(
                    message, existing_message
                ):
                    messages.append(message)

                    # Send an alert message and add its ID to the alert list
                    try:
                        alert_message = await message.reply(
                            "This message is a recent crosspost/duplicate of the following messages: "
                            + ", ".join([m.jump_url for m in messages])
                            + ".\n\nPlease delete all duplicate messages."
                        )
                        user_cache["message_to_alert"][message.id] = alert_message.id
                    except discord.HTTPException:
                        # Silently handle errors
                        pass
                    break
            else:
                continue
            break
        else:
            # Add new message group if no crosspost is found
            user_cache["message_groups"].append([message])
            if (
                len(user_cache["message_groups"])
                > self.max_tracked_message_groups_per_user
            ):
                user_cache["message_groups"].pop(0)

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
            for j in reversed(range(len(messages))):
                if message.id == messages[j].id:
                    del messages[j]
                    if message.id in user_cache["message_to_alert"]:
                        stale_alert_message_ids.append(
                            user_cache["message_to_alert"].pop(message.id)
                        )
                    break

            if len(messages) == 1:
                # Mark all alert messages for this crosspost group as stale
                stale_alert_message_ids.extend(user_cache["message_to_alert"].values())
                user_cache["message_to_alert"].clear()

        # Delete stale alert messages
        for alert_message_id in stale_alert_message_ids:
            try:
                await discord.PartialMessage(
                    channel=message.channel, id=alert_message_id
                ).delete()
            except (discord.NotFound, discord.Forbidden):
                # Silently handle errors
                pass

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
        message_length_threshold (int): Minimum length of a message to be considered.
        theme_color (int | discord.Color): Theme color for the bot's responses.
    """
    await bot.add_cog(
        AntiCrosspostCog(
            bot,
            channel_ids,
            message_length_threshold,
            max_tracked_users,
            max_tracked_message_groups_per_user,
            theme_color,
        )
    )
