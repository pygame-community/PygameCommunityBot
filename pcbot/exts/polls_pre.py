from ast import literal_eval
import asyncio
import datetime
import re
from typing import Any, Optional, Union

import discord
from discord.ext import commands
import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from snakecore.commands.converters import String

from .base import BaseCommandCog

BotT = Union[snakecore.commands.Bot, snakecore.commands.AutoShardedBot]


def parse_text_to_mapping(
    string: str, delimiter: str = ":", separator: str = " | ", eval_values: bool = False
) -> dict[str, Any]:
    mapping = {}
    pair_strings = string.split(sep=separator)

    for pair_str in pair_strings:
        key, _, value = pair_str.strip().partition(delimiter)

        if not value:
            raise ValueError(f"failed to parse mapping pair: '{pair_str}'")

        if eval_values:
            mapping[key] = literal_eval(value)
        else:
            mapping[key] = value

    return mapping


class PollsPre(BaseCommandCog, name="polls-pre"):
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except discord.HTTPException:
                return

        if not (
            (
                isinstance(channel, discord.abc.GuildChannel)
                and isinstance(channel, discord.abc.Messageable)
            )
            or isinstance(channel, discord.Thread)
        ):
            return

        try:
            user = self.bot.get_user(payload.user_id) or await self.bot.fetch_user(
                payload.user_id
            )
            msg: discord.Message = await channel.fetch_message(payload.message_id)
        except discord.HTTPException:
            return

        if user.bot:
            return

        if (
            msg.author.id == self.bot.user.id  # type: ignore
            and msg.embeds
            and (footer_text := msg.embeds[0].footer.text)
        ):
            split_footer = footer_text.split("___\n")  # separator used by poll embeds

            if len(split_footer) == 1:
                return

            try:
                poll_config_map = parse_text_to_mapping(
                    split_footer[1], delimiter=":", separator=" | "
                )
            except (SyntaxError, ValueError):
                raise

            if (
                "by" in poll_config_map
                and "voting-mode" in poll_config_map
                and poll_config_map["voting-mode"] == "single"
            ):
                for reaction in msg.reactions:
                    if not snakecore.utils.is_emoji_equal(
                        payload.emoji, reaction.emoji
                    ):
                        try:
                            await reaction.remove(user)
                        except discord.HTTPException:
                            pass
                        await asyncio.sleep(0.1)

    async def poll_func(
        self,
        ctx: commands.Context[BotT],
        description: str,
        *emojis: tuple[discord.PartialEmoji, str],
        multiple_votes: bool = True,
        _destination: Optional[
            Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]
        ] = None,
        _richpoll_embed_dict: Optional[dict] = None,
    ):
        _richpoll_embed_dict = _richpoll_embed_dict or {}

        destination = ctx.channel if _destination is None else _destination

        base_embed_dict = {
            "title": "Voting in progress",
            "fields": [
                {
                    "name": "🔺",
                    "value": "Agree",
                    "inline": True,
                },
                {
                    "name": "🔻",
                    "value": "Disagree",
                    "inline": True,
                },
            ],
            "author": {
                "name": ctx.author.name,
            },
            "color": 0x34A832,
            "footer": {
                "text": f"This poll was started by {ctx.author.display_name}#{ctx.author.discriminator}.\n"
                + (
                    "\n"
                    if multiple_votes
                    else "You cannot make multiple votes in this poll.\n"
                )
                + "___\n"
                f"by:{ctx.author.id} | voting-mode:"
                + ("multiple" if multiple_votes else "single")
            },
            "timestamp": ctx.message.created_at.isoformat(),
            "description": description,
        }
        base_embed_dict.update(_richpoll_embed_dict)

        # Make into dict because we want to get rid of emoji repetitions
        emojis_dict = {f"{k}".strip(): v.strip() for k, v in emojis}
        if emojis_dict:
            if len(emojis_dict) < 2:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "Please add at least 2 voting options in the poll."
                    ),
                )

            base_embed_dict["fields"] = [
                {"name": k, "value": v, "inline": True} for k, v in emojis_dict.items()
            ]

        final_embed = discord.Embed.from_dict(base_embed_dict)
        poll_msg = await destination.send(embed=final_embed)

        for field in base_embed_dict["fields"]:
            try:
                emoji_id = snakecore.utils.extract_markdown_custom_emoji_id(
                    field["name"].strip()
                )
                emoji = self.bot.get_emoji(emoji_id)
                if emoji is None:
                    raise ValueError()
            except ValueError:
                emoji = field["name"]

            try:
                await poll_msg.add_reaction(emoji)
            except discord.NotFound:
                await poll_msg.clear_reactions()
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        f"The emoji '{emoji}' could not be added as a reaction: "
                        "It could not be obtained for use by this bot application."
                    )
                )

    async def poll_close_func(
        self,
        ctx: commands.Context[BotT],
        msg: discord.Message,
        _color: Optional[discord.Color] = None,
    ):
        assert isinstance(ctx.author, discord.Member)

        if not isinstance(
            msg.channel, (discord.TextChannel, discord.VoiceChannel, discord.Thread)
        ):
            raise commands.CommandError(
                "The target message must be a discord guild/server message."
            )

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,
            msg.channel,  # type: ignore
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command with the specified arguments."
                )
            )

        if not msg.embeds:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The message specified does not contain an ongoing poll.",
                )
            )

        embed = msg.embeds[0]
        if not isinstance(embed.footer.text, str):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The message specified does not contain an ongoing poll.",
                )
            )

        poll_config_map = {}

        # Take the second line remove the parenthesies
        if embed.footer.text and embed.footer.text.count("\n"):
            split_footer = embed.footer.text.split("___\n")

            try:
                poll_config_map = parse_text_to_mapping(
                    split_footer[1], delimiter=":", separator=" | "
                )
            except (SyntaxError, ValueError) as err:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "The specified message's poll embed is malformed.",
                    )
                )

        else:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The message specified does not contain an ongoing poll.",
                )
            )

        if not (
            "by" in poll_config_map
            and poll_config_map["by"].isnumeric()
            and "voting-mode" in poll_config_map
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "The specified message's poll embed is malformed.",
                )
            )

        elif not ctx.channel.permissions_for(
            ctx.author
        ).manage_messages and ctx.author.id != int(poll_config_map["by"]):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You cannot close polls created by others without the 'Manage Messages' permission.",
                )
            )

        title = "Voting has ended"

        msg = await msg.channel.fetch_message(
            msg.id
        )  # force population of msg.reactions

        reaction_counts = {
            str(reaction.emoji): reaction.count for reaction in msg.reactions
        }

        top: list[tuple[int, Any]] = [(0, None)]
        for reaction_emoji_str, count in reaction_counts.items():
            if count - 1 > top[0][0]:
                top = [(count - 1, reaction_emoji_str)]
                continue

            if count - 1 == top[0][0]:
                top.append((count - 1, reaction_emoji_str))

        fields = []
        for field in embed.fields:
            try:
                r_count = reaction_counts[field.name] - 1  # type: ignore
            except KeyError:
                continue

            fields.append(
                dict(
                    name=field.name,
                    value=f"{field.value} ({r_count} votes)",
                    inline=True,
                )
            )
            if field.name == top[0][1]:
                title += (
                    f"\n{field.value}({field.name}) has won with {top[0][0]} votes!"
                )

        if len(top) >= 2:
            title = title.split("\n")[0]
            title += "\nIt's a draw!"

        await msg.edit(
            embed=discord.Embed.from_dict(
                embed.to_dict()
                | dict(
                    color=0xA83232 if not _color else _color.value,
                    title=title,
                    fields=fields,
                    footer=dict(text="This poll has ended."),
                    timestamp=ctx.message.created_at.isoformat(),
                )
            ),
        )

    @commands.group(invoke_without_command=True)
    @flagconverter_kwargs()
    async def poll(
        self,
        ctx: commands.Context[BotT],
        description: String,
        *,
        option: list[tuple[discord.PartialEmoji, String]],
        multiple_votes: bool = True,
    ):
        return await self.poll_func(
            ctx,
            description,
            *option,
            multiple_votes=multiple_votes,
        )

    @poll.command(name="close", extras=dict(inject_reference_as_first_argument=True))
    async def poll_close(
        self,
        ctx: commands.Context[BotT],
        msg: Optional[discord.Message],
    ):
        if not msg:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No message given as input.",
                )
            )

        return await self.poll_close_func(ctx, msg)

    @commands.group(invoke_without_command=True)
    @flagconverter_kwargs()
    async def richpoll(
        self,
        ctx: commands.Context[BotT],
        description: String,
        *,
        option: list[tuple[discord.PartialEmoji, String]],
        destination: Optional[
            Union[discord.TextChannel, discord.VoiceChannel, discord.Thread]
        ] = None,
        author: Optional[String] = None,
        color: Optional[discord.Color] = None,
        url: Optional[String] = None,
        image_url: Optional[String] = None,
        thumbnail: Optional[String] = None,
        multiple_votes: bool = True,
    ):
        if not isinstance(
            destination, (discord.TextChannel, discord.VoiceChannel, discord.Thread)
        ):
            destination = ctx.channel  # type: ignore

        if not snakecore.utils.have_permissions_in_channels(
            ctx.author,  # type: ignore
            destination,  # type: ignore
            "view_channel",
        ):
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "You do not have enough permissions to run this command with the specified destination."
                )
            )

        embed_dict = {}
        if author:
            embed_dict["author"] = {"name": author}

        if color:
            embed_dict["color"] = int(color)

        if url:
            embed_dict["url"] = url

        if image_url:
            embed_dict["image"] = {"url": image_url}

        if thumbnail:
            embed_dict["thumbnail"] = {"url": thumbnail}

        return await self.poll_func(
            ctx,
            description,
            *option,
            multiple_votes=multiple_votes,
            _destination=destination,
            _richpoll_embed_dict=embed_dict,
        )

    @richpoll.command(
        name="close", extras=dict(inject_reference_as_first_argument=True)
    )
    async def richpoll_close(
        self,
        ctx: commands.Context[BotT],
        msg: Optional[discord.Message] = None,
        *,
        color: Optional[discord.Color] = None,
    ):
        if not msg:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "No message given as input.",
                )
            )
        return await self.poll_close_func(ctx, msg, _color=color)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT):
    await bot.add_cog(PollsPre(bot))