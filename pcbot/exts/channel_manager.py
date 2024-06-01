"""This file is a part of the source code for PygameCommunityBot.

Copyright (c) 2022-present pygame-community

Bot extension for Discord channel management. 
"""

import discord
from discord.ext import commands

import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import CodeBlock, String, Parens, TimeDelta

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot


async def clone_forum(
    forum: discord.ForumChannel, new_name: str | None = None, reason: str | None = None
) -> discord.ForumChannel:
    return await forum.guild.create_forum(
        name=new_name if new_name else forum.name,
        topic=forum.topic or discord.utils.MISSING,
        category=forum.category,
        position=forum.position + 1,
        slowmode_delay=forum.slowmode_delay,
        overwrites=(
            discord.utils.MISSING if forum.permissions_synced else forum.overwrites
        ),  # type: ignore
        default_auto_archive_duration=forum.default_auto_archive_duration,
        default_thread_slowmode_delay=forum.default_thread_slowmode_delay,
        default_sort_order=(
            forum.default_sort_order
            if forum.default_sort_order is not None
            else discord.utils.MISSING
        ),
        default_reaction_emoji=(
            forum.default_reaction_emoji
            if forum.default_reaction_emoji is not None
            else discord.utils.MISSING
        ),
        default_layout=forum.default_layout,
        available_tags=(
            forum.available_tags if forum.available_tags else discord.utils.MISSING
        ),
        reason=reason,
    )


async def clone_category(
    category: discord.CategoryChannel,
    new_name: str | None,
    clone_channels: bool = True,
    reason: str | None = None,
):
    new_category = await category.clone(name=new_name, reason=reason)
    await new_category.move(after=category)

    if clone_channels:
        for channel in category.channels:
            if isinstance(channel, discord.ForumChannel):
                channel_clone = await clone_forum(
                    channel,
                    new_name=new_name,
                    reason="Channel created as clone of "
                    f"#{channel.name} ({channel.mention})",
                )
            else:
                channel_clone = await channel.clone(
                    reason="Channel created as clone of "
                    f"#{channel.name} ({channel.mention})"
                )

            await channel_clone.move(
                category=new_category,
                end=True,
                reason="Channel "
                f"moved into #{new_category.name} ({new_category.mention}) "
                "as part of a bulk cloning process.",
            )  # type: ignore

    return new_category


class ChannelManagerCog(BaseExtensionCog, name="channels"):
    """Channel management commands."""

    @commands.group(invoke_without_command=True)
    async def channel(self, ctx: commands.Context[BotT]):
        pass

    @channel.command(
        name="clone",
        usage="<channel: Channel> [new_name: Text[100]] [deep_clone_category: yes|no]",
    )
    @flagconverter_kwargs()
    async def channel_clone(
        self,
        ctx: commands.Context[BotT],
        channel: (
            discord.TextChannel
            | discord.VoiceChannel
            | discord.ForumChannel
            | discord.StageChannel
            | discord.CategoryChannel
        ),
        *,
        new_name: str | None = None,
        deep_clone_category: bool = False,
    ):
        """Clone the specified channel. More reliable than Discord's built-in channel cloning system.

        __**Parameters:**__

        **`<channel: Channel>`**
        > The channel to clone.

        **`[new_name: Text[100]]`**
        > The new name of the cloned channel. Must not exceed 100 characters.

        **`[deep_clone_category: yes|no]`**
        > Whether to clone all channels within a specified category channel.
        > Defaults to 'no'.
        """
        if isinstance(channel, discord.CategoryChannel):
            await clone_category(
                channel,
                new_name=new_name,
                clone_channels=deep_clone_category,
                reason=f"Channel #{channel.name} ({channel.mention}) cloned "
                + ("deeply " if deep_clone_category else "")
                + f"upon request by {ctx.author.name} ({ctx.author.mention})",
            )
        elif isinstance(channel, discord.ForumChannel):
            await clone_forum(
                channel,
                reason=f"Channel created as clone of #{channel.name} "
                f"({channel.mention}) upon request by {ctx.author.name} "
                f"({ctx.author.mention})",
            )
        else:
            clone = await channel.clone(
                name=new_name,
                reason=f"Channel #{channel.name} ({channel.mention}) cloned "
                f"upon request by {ctx.author.name} ({ctx.author.mention})",
            )


async def setup(bot: BotT, color: int | discord.Color = 0):
    await bot.add_cog(ChannelManagerCog(bot, theme_color=color))
