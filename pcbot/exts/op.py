"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import snakecore
from snakecore.commands import flagconverter_kwargs
from snakecore.commands import ReferencedMessage

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)


class OPCog(BaseExtensionCog, name="op"):
    """Commands related to being an OP (original poster) in a forum post or thread."""

    @commands.guild_only()
    @commands.hybrid_group()
    async def op(self, ctx: commands.Context[BotT]):
        pass

    @commands.guild_only()
    @op.command(
        name="pin",
        usage="<message: Message> [delete_system_message: yes|no] [unpin_last: yes|no]",
        description="Pin the specified message.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @app_commands.describe(
        message="The message to pin.",
        unpin_last="Whether to unpin the least recently pinned message(s) if the "
        "maximum pin limit of 50 would be reached.",
        delete_system_message="whether any pin system messages should be automatically"
        " deleted. Defaults to False.",
    )
    @flagconverter_kwargs()
    async def op_pin(
        self,
        ctx: commands.Context[BotT],
        *,
        message: discord.PartialMessage | ReferencedMessage,
        unpin_last: bool = False,
        delete_system_message: bool = False,
    ):
        """Pin the specified message.

        In threads, forum posts, or text channels with "OP: <@{user_id}> ..." within their description, people will always be able to use this command to
        pin messages as the OP (original poster).

        __**Parameters:**__

        **`<message: Message>`**
        > The message to pin.

        **`[delete_system_message: yes|no]`**
        > A flag for whether any system messages about pinning should be automatically
        > deleted if possible.
        > Defaults to 'no'.

        **`[unpin_last: yes|no]`**
        > A flag for whether to unpin the least recently pinned message(s) if the maximum pin
        > limit of 50 would be reached.
        > Defaults to 'no'.
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

        channel = ctx.channel

        if not isinstance(channel, discord.Thread):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "This command does not work outside of threads and posts."  # type: ignore
                )
            )

        elif not (
            (channel.owner_id == ctx.author.id)
            or snakecore.utils.have_permissions_in_channels(
                ctx.author,
                channel,
                "view_channel",
                "manage_messages",
            )
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command in this "
                    f"channel (<#{channel.id}>)."  # type: ignore
                )
            )

        elif not message.id == channel.id:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The specified message must originate from this channel "
                    f"(<#{channel.id}>).",
                )
            )

        if message.pinned:
            raise commands.CommandInvokeError(
                commands.CommandError(f"Message {message.jump_url} is already pinned.")
            )

        to_unpin = None

        if unpin_last:
            if len((pins := await channel.pins())) == 50:
                to_unpin = pins[0]
                await to_unpin.unpin()

        await message.pin()

        if delete_system_message:
            try:
                system_message: discord.Message = await ctx.bot.wait_for(
                    "message",
                    check=(
                        lambda m: m.channel.id == channel.id  # type: ignore
                        and m.type == discord.MessageType.pins_add
                    ),
                    timeout=2,
                )
            except asyncio.TimeoutError:
                pass
            else:
                await system_message.delete()

        success_embed = discord.Embed(
            description=f"Successfully pinned {message.jump_url}."
            + (f"\n{to_unpin.jump_url} was unpinned." if to_unpin else ""),
            color=self.theme_color,
        )

        if ctx.interaction:
            await ctx.interaction.response.send_message(
                embed=success_embed, ephemeral=True
            )
        else:
            await self.send_or_edit_response(
                ctx,
                embed=success_embed,
            )

    @commands.guild_only()
    @op.command(
        name="unpin",
        usage="<message: Message>",
        description="Unpin the specified message.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @app_commands.describe(
        message="The message to unpin.",
    )
    @flagconverter_kwargs()
    async def op_unpin(
        self,
        ctx: commands.Context[BotT],
        *,
        message: discord.Message | ReferencedMessage,
    ):
        """Unpin the specified message.

        In threads, forum posts, or text channels with "OP: <@{user_id}> ..." people will always be able to use this command to
        pin messages as the OP (original poster).

        __**Parameters:**__

        **`<message: Message>`**
        > The message to unpin.
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

        channel = ctx.channel

        if not isinstance(channel, discord.Thread):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "This command does not work outside of threads and posts."  # type: ignore
                )
            )

        elif not (
            (channel.owner_id == ctx.author.id)
            or snakecore.utils.have_permissions_in_channels(
                ctx.author,
                channel,
                "view_channel",
                "manage_messages",
            )
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command in this "
                    f"channel (<#{channel.id}>)."  # type: ignore
                )
            )

        elif not message.id == channel.id:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The specified message must originate from this channel "
                    f"(<#{channel.id}>).",
                )
            )

        if not message.pinned:
            raise commands.CommandInvokeError(
                commands.CommandError(f"Message {message.jump_url} is not pinned.")
            )

        await message.unpin()

        success_embed = discord.Embed(
            description=f"Successfully pinned {message.jump_url}.",
            color=self.theme_color,
        )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=success_embed)
        else:
            await self.send_or_edit_response(
                ctx,
                embed=success_embed,
            )

    # add event listeners, commands, state, etc.


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: int | discord.Color = 0,  # add more optional parameters as desired
):
    await bot.add_cog(OPCog(bot, theme_color=color))
