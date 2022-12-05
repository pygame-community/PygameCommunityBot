import datetime
import time
from typing import Optional, Union

import discord
import snakecore
from discord.ext import commands
from snakecore.commands import converters
from snakecore.commands.decorators import flagconverter_kwargs
from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ... import __version__
from ...bot import PygameCommunityBot
from ..base import BaseCommandCog
from .constants import DB_TABLE_PREFIX, POLL_STATE
from .migrations import MIGRATIONS

BotT = PygameCommunityBot


class _Sentinel:
    def __bool__(self) -> bool:
        return False


SENTINEL = _Sentinel()


class Poll:
    _POLLS = {}

    def __init__(
        self,
        db_engine: AsyncEngine,
        message: discord.Message,
        owner: discord.Member,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        allow_multiple_votes: bool = True,
        state: Optional[POLL_STATE] = None,
    ):
        self.message = message
        self.owner = owner

        self.start_time = start_time
        self.end_time = end_time

        # TODO: figure out jobs
        self._start_job: Optional[object] = None
        self._end_job: Optional[object] = None

        self.allow_multiple_votes = allow_multiple_votes
        self.state = state or POLL_STATE.WAITING_FOR_START

        self.db_engine = db_engine
        self._POLLS[self.message] = self

    async def init(self, /, is_saved=False):
        if self.state == POLL_STATE.WAITING_FOR_START:
            if self.start_time is None:
                await self.open()
                self.state = POLL_STATE.ONGOING
            elif self.start_time.timestamp() > time.time():
                ...  # TODO: create and start job for opening the poll in time
            elif self.start_time.timestamp() < time.time():
                await self.open()

        if self.state == POLL_STATE.ONGOING:
            if self.end_time is not None:
                if self.end_time.timestamp() > time.time():
                    ...  # TODO: create and start job for closing the poll in time
                elif self.end_time.timestamp() <= time.time():
                    await self.close()

        if not is_saved:
            to_save = {
                "guild_id": self.message.guild.id,
                "channel_id": self.message.channel.id,
                "message_id": self.message.id,
                "start_time": self.start_time.isoformat() if self.start_time else None,
                "end_time": self.end_time.isoformat() if self.end_time else None,
                "owner_id": self.owner.id,
                "allow_multiple_votes": self.allow_multiple_votes,
                "state": self.state,
            }
            statement = text(
                f"INSERT INTO '{DB_TABLE_PREFIX}polls'"
                "VALUES (:guild_id, :channel_id, :message_id, :start_time, :end_time,"
                ":owner_id, :allow_multiple_votes, :state)"
            )
            conn: AsyncConnection
            async with self.db_engine.begin() as conn:
                await conn.execute(statement, to_save)

    @classmethod
    async def create_new(
        cls,
        ctx: commands.Context[BotT],
        db_engine: AsyncEngine,
        reaction_dict: dict,
        embed: discord.Embed,
    ) -> "Poll":
        embed.clear_fields()
        for emoji, desc in reaction_dict.items():
            embed.add_field(name=emoji, value=desc)

        message = await ctx.send(embed=embed)

        for emoji in reaction_dict.keys():
            try:
                await message.add_reaction(emoji)
            except (discord.errors.NotFound, discord.errors.HTTPException):
                await message.clear_reactions()
                await message.edit(
                    embed=discord.Embed(
                        color=0xFF0000,
                        title="Invalid emoji",
                    )
                )

        poll = Poll(db_engine, message, ctx.author)
        return poll

    @classmethod
    async def from_message(
        cls, db_engine: AsyncEngine, message: discord.Message
    ) -> "Poll":
        if cls._POLLS.get(message):
            return cls._POLLS[message]

        conn: AsyncConnection
        async with db_engine.begin() as conn:
            result: Result = await conn.execute(
                text(
                    f"SELECT * FROM '{DB_TABLE_PREFIX}polls' AS polls "
                    "WHERE polls.guild_id=:guild_id "
                    "AND polls.channel_id=:channel_id "
                    "AND polls.message_id=:message_id"
                ),
                dict(
                    guild_id=message.guild.id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                ),
            )

            data = result.first()
            if data is None:
                raise ValueError("Message is not a valid poll")

            start_time = (
                datetime.datetime.fromisoformat(data.start_time)
                if data.start_time
                else None
            )
            end_time = (
                datetime.datetime.fromisoformat(data.end_time)
                if data.end_time
                else None
            )

            poll = Poll(
                db_engine,
                message,
                await message.guild.fetch_member(data.owner_id),
                start_time,
                end_time,
                bool(data.allow_multiple_votes),
                POLL_STATE(data.state),
            )
            await poll.init()

        return poll

    async def save(self):
        # TODO: Update start and end jobs (if time changed, update them to the new time)
        to_update = {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "allow_multiple_votes": self.allow_multiple_votes,
            "state": self.state,
        }
        statement = text(
            f"UPDATE '{DB_TABLE_PREFIX}polls'"
            "SET start_time=:start_time, end_time=:end_time, allow_multiple_votes=:allow_multiple_votes, state=:state"
            "WHERE polls.guild_id=:guild_id "
            "AND polls.channel_id=:channel_id "
            "AND polls.message_id=:message_id"
        )
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            await conn.execute(statement, to_update)

    def get_votes(self):
        votes = {}
        for elem in self.message.reactions:
            votes[elem.emoji] = elem.count - 1

        return votes

    async def open(self):
        print("Opening poll")

    async def close(self, scheduled=True):
        print("Closing poll")


class PollCommandCog(BaseCommandCog, name="poll"):
    def __init__(self, bot: BotT, db_engine, theme_color: int = 0) -> None:
        super().__init__(bot, theme_color)
        self.db_engine = db_engine

    @commands.group(
        invoke_without_command=True,
        extras=dict(response_messsage_deletion_reaction=True),
    )
    async def poll(self, ctx: commands.Context[BotT]):
        await ctx.send(content="Test")

    def get_emoji_text_dict(self, tup):
        if len(tup) % 2 == 1:
            raise commands.CommandInvokeError(
                commands.UserInputError("Unmatched emoji-text pair")
            )
        if len(tup) > 40:
            raise commands.CommandInvokeError(
                commands.UserInputError(f"Too many options provided ({len(tup)//2}/20)")
            )

        last_item = None
        items = {}
        for i, obj in enumerate(tup):
            if not isinstance(obj, str):
                raise commands.CommandInvokeError(
                    commands.UserInputError(f"Argument {obj} is not a string")
                )
            obj = obj.strip()
            if i % 2 == 0:
                if snakecore.utils.is_markdown_custom_emoji(obj):
                    id_ = snakecore.utils.extract_markdown_custom_emoji_id(obj)
                    last_item = self.bot.get_emoji(id_)
                else:
                    last_item = obj

            else:
                if len(obj) > 100:
                    raise commands.CommandInvokeError(
                        commands.UserInputError(
                            f"Too long description for {str(last_item)} ({len(obj)}/100)"
                        )
                    )
                items[last_item] = obj
                last_item = None

        return items

    @poll.command(name="create")
    async def poll_create(
        self,
        ctx: commands.Context[BotT],
        start_time: converters.DateTime,
        description: str,
        *args,
    ):
        # TODO: figure out a way to take other args (such as start and end times)
        # because last time I tested it, I could not get kwargs with *args (all kwargs would
        # just be put into args). Also, the start_time arg here is temporary
        assert isinstance(ctx.author, discord.Member)

        if len(description) > 3000:
            raise commands.CommandInvokeError(
                commands.UserInputError(
                    f"Description provided is too long ({len(description)}/3000)"
                )
            )

        emojis = self.get_emoji_text_dict(args)
        embed = discord.Embed(
            color=self.theme_color, title="Voting in progress", description=description
        )

        poll = await Poll.create_new(ctx, self.db_engine, emojis, embed)
        poll.start_time = start_time
        await poll.init()

    @poll.command("update")
    @flagconverter_kwargs()
    async def poll_update(
        self,
        ctx: commands.Context[BotT],
        msg: discord.Message,
        *,
        start_time: Union[converters.DateTime, None] = SENTINEL,
        end_time: Union[converters.DateTime, None] = SENTINEL,
        allow_multiple_votes: Union[bool, None] = SENTINEL,
    ):

        poll = await Poll.from_message(self.db_engine, msg)
        poll.start_time = poll.start_time if start_time is SENTINEL else start_time
        poll.end_time = poll.end_time if end_time is SENTINEL else end_time
        poll.allow_multiple_votes = (
            poll.allow_multiple_votes
            if allow_multiple_votes is SENTINEL
            else allow_multiple_votes
        )

        await poll.save()

    async def poll_close(self):
        ...

    @poll.command(name="info")
    async def info(self, ctx: commands.Context[BotT], arg: discord.Message):
        poll = await Poll.from_message(self.db_engine, arg)
        embed = discord.Embed(color=self.theme_color)

        for emoji, count in poll.get_votes().items():
            embed.add_field(name=emoji, value=count)

        start_time = (
            f"Starts: {snakecore.utils.create_markdown_timestamp(poll.start_time)}\n"
            if poll.start_time
            else ""
        )

        end_time = (
            f"Ends: {snakecore.utils.create_markdown_timestamp(poll.end_time)}\n"
            if poll.end_time
            else ""
        )

        embed.description = (
            f"State: {poll.state.name.lower().replace('_', ' ')} ({poll.state.__doc__})"
            f"Opened by: {poll.owner.mention}\n"
            f"Allows multiple votes: {poll.allow_multiple_votes}\n"
            + start_time
            + end_time
            + f"[Link to poll]({arg.jump_url})\n\nStandings:"
        )

        await ctx.send(embed=embed)


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: Union[int, discord.Color] = 0):
    db_engine = bot.get_database()
    if not isinstance(db_engine, AsyncEngine):
        raise RuntimeError(
            "Could not find primary database interface of type "
            "'sqlalchemy.ext.asyncio.AsyncEngine'"
        )
    elif db_engine.name not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Unsupported database engine: {db_engine.name}")

    first_setup = False
    try:
        extension_data = await bot.read_extension_data(__name__)
    except LookupError:
        first_setup = True
        extension_data = dict(name=__name__, db_table_prefix=DB_TABLE_PREFIX)
        await bot.create_extension_data(**extension_data, version=__version__)
    print(first_setup, extension_data)

    stored_version = "0.0.0" if first_setup else str(extension_data["version"])
    if stored_version > __version__:
        raise RuntimeError(
            f'Extension data is incompatible: Stored data version "{stored_version}" exceeds extension version "{__version__}"'
        )

    if first_setup:
        conn: AsyncConnection
        async with db_engine.begin() as conn:
            for vi in sorted(MIGRATIONS[db_engine.name].keys()):
                if vi > stored_version:
                    await conn.execute(text(MIGRATIONS[db_engine.name][vi]))

        extension_data["version"] = __version__
        await bot.update_extension_data(**extension_data)

    await bot.add_cog(PollCommandCog(bot, db_engine, theme_color=int(color)))

    # TODO: Open votes that are still open (from db) and start jobs
