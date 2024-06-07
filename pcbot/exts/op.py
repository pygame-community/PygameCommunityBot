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
from snakecore.commands import ReferencedMessage, Message

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
MessageableGuildChannel = (
    discord.TextChannel | discord.VoiceChannel | discord.StageChannel | discord.Thread
)


invocation_error = lambda ctx, *args: (
    app_commands.CommandInvokeError(
        ctx.interaction.command, app_commands.AppCommandError(*args)
    )
    if ctx.interaction
    else commands.CommandInvokeError(commands.CommandError(*args))
)


class OPCog(BaseExtensionCog, name="op"):
    """Commands related to being an OP (original poster) in a forum post or thread."""

    @commands.guild_only()
    @commands.group(invoke_without_command=True)
    async def op(self, ctx: commands.Context[BotT]):
        pass

    op_app_cmd_group = app_commands.Group(
        name="op",
        description="Commands related to being an OP (original poster) in a forum post or thread.",
        guild_only=True,
    )

    async def op_pin_func(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message,
        unpin_last: bool = False,
        delete_system_message: bool = False,
    ):
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
            raise (
                invocation_error(
                    ctx,
                    "This command does not work outside of threads and posts.",  # type: ignore
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
            raise (
                invocation_error(
                    ctx,
                    "You do not have enough permissions to run this command in this "
                    f"channel (<#{channel.id}>).",  # type: ignore
                )
            )

        elif not message.channel.id == channel.id:
            raise (
                invocation_error(
                    ctx,
                    "The specified message must originate from this channel "
                    f"(<#{channel.id}>).",
                )
            )

        if message.pinned:
            raise (
                invocation_error(ctx, f"Message {message.jump_url} is already pinned.")
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
                        lambda m: m.channel.id == channel.id
                        and m.type == discord.MessageType.pins_add
                    ),
                    timeout=2,
                )
                print("HERE")
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

    @op.command(
        name="pin",
        usage="<message: Message> [delete_system_message: yes|no] [unpin_last: yes|no]",
        description="Pin the specified message.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def op_pin(
        self,
        ctx: commands.Context[BotT],
        message_: ReferencedMessage | discord.Message,
        *,
        message: discord.Message | None = None,
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

        if not (message := message_ or message):
            raise commands.CommandInvokeError(
                commands.BadArgument(
                    "'message' is a required argument that is missing."
                )
            )

        return await self.op_pin_func(
            ctx,
            message=message,
            unpin_last=unpin_last,
            delete_system_message=delete_system_message,
        )

    @op_app_cmd_group.command(
        name="pin",
        description="Pin the specified message.",
    )
    @app_commands.describe(
        message="The message to pin.",
        unpin_last="Whether to unpin the least recently pinned message(s) if the "
        "maximum pin limit of 50 would be reached.",
        delete_system_message="whether any pin system messages should be automatically"
        " deleted. Defaults to False.",
    )
    async def op_pin_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
        message: Message,
        unpin_last: bool = False,
        delete_system_message: bool = False,
    ):
        return await self.op_pin_func(
            await commands.Context[BotT].from_interaction(interaction),
            message=await message.channel.fetch_message(message.id),
            unpin_last=unpin_last,
            delete_system_message=delete_system_message,
        )

    async def op_unpin_func(
        self,
        ctx: commands.Context[BotT],
        message: discord.Message,
    ):
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
            raise (
                invocation_error(
                    ctx,
                    "This command does not work outside of threads and posts.",
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
            raise (
                invocation_error(
                    ctx,
                    "You do not have enough permissions to run this command in this "
                    f"channel (<#{channel.id}>).",
                )
            )

        elif not message.channel.id == channel.id:
            raise (
                invocation_error(
                    ctx,
                    "The specified message must originate from this channel "
                    f"(<#{channel.id}>).",
                )
            )

        if not message.pinned:
            raise (invocation_error(ctx, f"Message {message.jump_url} is not pinned."))

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

    @commands.guild_only()
    @op.command(
        name="unpin",
        usage="<message: Message>",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    @flagconverter_kwargs()
    async def op_unpin(
        self,
        ctx: commands.Context[BotT],
        message_: discord.Message | ReferencedMessage | None,
        *,
        message: discord.Message | None = None,
    ):
        """Unpin the specified message.

        In threads, forum posts, or text channels with "OP: <@{user_id}> ..." people will always be able to use this command to
        pin messages as the OP (original poster).

        __**Parameters:**__

        **`<message: Message>`**
        > The message to unpin.
        """

        if not (message := message_ or message):
            raise commands.CommandInvokeError(
                commands.BadArgument(
                    "'message' is a required argument that is missing."
                )
            )
        return await self.op_unpin_func(ctx, message=message)

    @op_app_cmd_group.command(
        name="unpin",
        description="Unpin the specified message.",
    )
    @app_commands.describe(
        message="The message to unpin.",
    )
    async def op_unpin_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
        message: Message,
    ):
        return await self.op_unpin_func(
            await commands.Context[BotT].from_interaction(interaction), message=message
        )

    op_unpin_app_cmd.callback.__doc__ = op_unpin.usage


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: int | discord.Color = 0,  # add more optional parameters as desired
):
    await bot.add_cog(OPCog(bot, theme_color=color))
