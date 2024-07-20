"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
from collections import OrderedDict

import asyncio
from collections import OrderedDict
from collections.abc import Collection
from typing import TypedDict
import discord
from discord.ext import commands
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


def crosspost_cmp(message: discord.Message, other: discord.Message) -> bool:
    hamming_score = sum(x != y for x, y in zip(message.content, other.content)) / max(
        len(message.content), len(other.content)
    )

    return hamming_score < 0.20 or any(
        att1.url == att2.url or att1.size == att2.size  # check for approximate matches
        for att1, att2 in zip(message.attachments, other.attachments)
    )


class UserCrosspostCache(TypedDict):
    message_groups: list[list[discord.Message]]
    alert_message_ids: set[int]


class AntiCrosspostCog(BaseExtensionCog, name="anti-crosspost"):
    def __init__(
        self,
        bot: BotT,
        channel_ids: Collection[int],
        message_length_threshold: int,
        max_tracked_users: int,
        max_tracked_message_groups_per_user,
        theme_color: int | discord.Color = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.channel_ids = set(channel_ids)
        self.crossposting_cache: OrderedDict[int, UserCrosspostCache] = OrderedDict()

        self.max_tracked_users = max_tracked_users
        self.max_tracked_message_groups_per_user = max_tracked_message_groups_per_user
        self.message_length_threshold = message_length_threshold

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not (
            (
                message.channel.id in self.channel_ids
                or isinstance(message.channel, (discord.abc.GuildChannel))
                and message.channel.category_id in self.channel_ids
                or isinstance(message.channel, discord.Thread)
                and message.channel.parent_id in self.channel_ids
            )
            and message.type == discord.MessageType.default
        ):
            return

        if len(message.content) < self.message_length_threshold:
            return

        if message.author.id not in self.crossposting_cache:
            self.crossposting_cache[message.author.id] = UserCrosspostCache(
                message_groups=[[message]],
                alert_message_ids=set(),
            )
            return

        if (
            len(self.crossposting_cache[message.author.id]["message_groups"])
            > self.max_tracked_message_groups_per_user
        ):
            self.crossposting_cache[message.author.id]["message_groups"].pop(0)

        # To fix the code below from sending an

        for i, messages in enumerate(
            self.crossposting_cache[message.author.id]["message_groups"]
        ):
            break_outer = False
            for j in range(len(messages)):
                if message.channel.id != messages[j].channel.id and crosspost_cmp(
                    message, messages[j]
                ):
                    messages.append(message)

                    self.crossposting_cache[message.author.id]["alert_message_ids"].add(
                        (
                            await message.reply(
                                "This message is a recent crosspost/duplicate of the following messages: "
                                + ", ".join([m.jump_url for m in messages])
                                + ".\n\nPlease delete all duplicate messages."
                            )
                        ).id
                    )
                    break_outer = True
                    break

            if break_outer:
                break
        else:
            self.crossposting_cache[message.author.id]["message_groups"].append(
                [message]
            )
            if (
                len(self.crossposting_cache[message.author.id]["message_groups"])
                > self.max_tracked_message_groups_per_user
            ):
                self.crossposting_cache[message.author.id]["message_groups"].pop(0)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not (
            message.guild
            and (
                message.channel.id in self.channel_ids
                or isinstance(message.channel, discord.abc.GuildChannel)
                and message.channel.category_id in self.channel_ids
                or isinstance(message.channel, discord.Thread)
                and message.channel.parent_id in self.channel_ids
            )
        ):
            return

        if message.author.id not in self.crossposting_cache:
            return

        stale_alert_message_ids: list[int] = []
        for messages in self.crossposting_cache[message.author.id]["message_groups"]:
            for j in reversed(range(len(messages))):
                if message.id == messages[j].id:
                    del messages[j]  # remove the message from the crosspost group
                    for alert_message_id in tuple(
                        self.crossposting_cache[message.author.id]["alert_message_ids"]
                    ):

                        try:
                            alert_message = discord.utils.find(
                                lambda m: m.id == alert_message_id,
                                self.bot.cached_messages,
                            )
                            if not alert_message:
                                alert_message = await message.channel.fetch_message(
                                    alert_message_id
                                )
                        except discord.NotFound:
                            continue

                        if (
                            alert_message.reference
                            and alert_message.reference.message_id == message.id
                        ):
                            self.crossposting_cache[message.author.id][
                                "alert_message_ids"
                            ].remove(alert_message_id)
                            # mark the alert message as stale if it references the deleted message
                            stale_alert_message_ids.append(alert_message_id)
                    break

            if len(messages) == 1:
                # mark all alert messages for this crosspost group as stale
                # as there is only one message left
                stale_alert_message_ids.extend(
                    self.crossposting_cache[message.author.id]["alert_message_ids"]
                )
                self.crossposting_cache[message.author.id]["alert_message_ids"].clear()

        for alert_message_id in stale_alert_message_ids:
            try:
                await discord.PartialMessage(
                    channel=message.channel, id=alert_message_id
                ).delete()
            except (discord.NotFound, discord.Forbidden):
                pass


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    channel_ids: Collection[int],
    max_tracked_users: int = 10,
    max_tracked_message_groups_per_user: int = 10,
    message_length_threshold: int = 64,
    theme_color: int | discord.Color = 0,
):
    await bot.add_cog(
        AntiCrosspostCog(
            bot,
            channel_ids,
            max_tracked_users,
            max_tracked_message_groups_per_user,
            message_length_threshold,
            theme_color,
        )
    )
