"""This file is a part of the source code for PygameCommunityBot.

Copyright (c) 2022-present pygame-community

Bot extension for Discord channel management. 
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

import snakecore
from snakecore.commands.decorators import flagconverter_kwargs

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)


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
            await asyncio.sleep(0.1)

    return new_category


class ChannelManagerCog(BaseExtensionCog, name="channels"):
    """Channel management commands."""

    @commands.hybrid_group()
    async def channel(self, ctx: commands.Context[BotT]):
        pass

    @channel.command(
        name="clone",
        usage="<channel: Channel> [new_name: Text[100]] [deeply_clone_category: yes|no]",
        description="Clone the specified channel. More reliable than Discord's built-in channel cloning system.",
        extras=dict(response_deletion_with_reaction=True),
    )
    @app_commands.describe(
        channel="The channel to clone.",
        new_name="The new name of the cloned channel. Must not exceed 100 characters.",
        deeply_clone_category="Whether to clone all channels within a specified "
        "category channel. Defaults to 'no'.",
    )
    @flagconverter_kwargs()
    async def channel_clone(
        self,
        ctx: commands.Context[BotT],
        *,
        channel: (
            discord.TextChannel
            | discord.VoiceChannel
            | discord.ForumChannel
            | discord.StageChannel
            | discord.CategoryChannel
        ),
        new_name: str | None = None,
        deeply_clone_category: bool = False,
    ):
        """Clone the specified channel. More reliable than Discord's built-in channel cloning system.

        __**Parameters:**__

        **`<channel: Channel>`**
        > The channel to clone.

        **`[new_name: Text[100]]`**
        > Flag for the new name of the cloned channel. Must not exceed 100 characters.

        **`[deeply_clone_category: yes|no]`**
        > Whether to clone all channels within a specified category channel.
        > Defaults to 'no'.
        """

        load_embed = discord.Embed.from_dict(
            dict(
                title="Your command is being processed:",
                color=int(self.theme_color),
                fields=[dict(name="\u200b", value="`...`", inline=False)],
            )
        )

        cloned_sub_channel_count = 0
        interaction_followup_message = None

        if isinstance(channel, discord.CategoryChannel):
            if deeply_clone_category and ctx.interaction:
                await ctx.interaction.response.defer(ephemeral=True)

            clone = await channel.clone(
                name=new_name,
                reason=f"Channel #{channel.name} ({channel.mention}) cloned "
                + ("deeply " if deeply_clone_category else "")
                + f"upon request by {ctx.author.name} ({ctx.author.mention})",
            )

            await clone.move(after=channel)

            if deeply_clone_category:
                sub_channel_count = len(channel.channels)
                for i, sub_channel in enumerate(channel.channels):
                    if isinstance(sub_channel, discord.ForumChannel):
                        channel_clone = await clone_forum(
                            sub_channel,
                            new_name=new_name,
                            reason="Channel created as clone of "
                            f"#{channel.name} ({channel.mention})",
                        )
                    else:
                        channel_clone = await sub_channel.clone(
                            reason="Channel created as clone of "
                            f"#{channel.name} ({channel.mention})"
                        )

                    await channel_clone.move(
                        category=clone,
                        end=True,
                        reason="Channel "
                        f"moved into #{clone.name} ({clone.mention}) "
                        "as part of a bulk cloning process.",
                    )  # type: ignore
                    await asyncio.sleep(0.1)

                    if sub_channel_count > 2 and not i % 3:
                        load_embed = load_embed.set_field_at(
                            0,
                            name=f"Cloning channels from {channel} to clone {clone}",
                            value=f"`{i}/{sub_channel_count}` channels cloned\n"
                            f"{(i / sub_channel_count) * 100:.01f}% | "
                            + snakecore.utils.progress_bar(
                                i / sub_channel_count, divisions=30
                            ),
                        )

                        if ctx.interaction:
                            if not interaction_followup_message:
                                interaction_followup_message = (
                                    await ctx.interaction.followup.send(
                                        embed=load_embed, wait=True
                                    )
                                )
                            else:
                                await interaction_followup_message.edit(
                                    embed=load_embed
                                )
                        else:
                            await self.send_or_edit_response(
                                ctx, reference=ctx.message, embed=load_embed
                            )

                    cloned_sub_channel_count = i + 1

        elif isinstance(channel, discord.ForumChannel):
            clone = await clone_forum(
                channel,
                new_name=new_name,
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

        success_embed = discord.Embed(
            description=f"Successfully cloned {channel.mention} "
            + (
                "deeply "
                if isinstance(channel, discord.CategoryChannel)
                and deeply_clone_category
                else ""
            )
            + f" as {clone.mention}",
            color=self.theme_color,
        )

        if deeply_clone_category:
            success_embed = load_embed.set_field_at(
                0,
                name=f"Successfully cloned {cloned_sub_channel_count} "
                f"channels from {channel} to clone {clone}",
                value=f"`{cloned_sub_channel_count}/{cloned_sub_channel_count}` channels cloned\n"
                "100% | " + snakecore.utils.progress_bar(1.0, divisions=30),
            )
            if interaction_followup_message:
                await interaction_followup_message.edit(
                    embed=success_embed,
                )
            else:
                await self.send_or_edit_response(
                    ctx, reference=ctx.message, embed=success_embed, silent=True
                )
        else:
            if ctx.interaction:
                await (
                    ctx.interaction.followup.send
                    if deeply_clone_category
                    else ctx.interaction.response.send_message
                )(
                    embed=success_embed,
                    ephemeral=True,
                )

            else:
                await self.send_or_edit_response(
                    ctx, reference=ctx.message, embed=success_embed, silent=True
                )


async def setup(bot: BotT, color: int | discord.Color = 0):
    await bot.add_cog(ChannelManagerCog(bot, theme_color=color))
