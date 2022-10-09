from asyncio import constants
from collections import OrderedDict
import pickle
from typing import TYPE_CHECKING, Any, Literal, Optional, Union
from uuid import UUID

import discord
from discord.ext import commands
import snakecore
from snakecore.commands.converters import Parens
from snakecore.commands.decorators import kwarg_command
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.engine import Result
from sqlalchemy import text

from ..base import BaseCommandCog
from .constants import DB_TABLE_PREFIX, ZERO_UUID
from ._types import GuildTextCommandData, GuildTextCommandState


BotT = snakecore.commands.Bot

if TYPE_CHECKING:
    Parens = tuple


class TextCommandManager(BaseCommandCog, name="text-command-manager"):
    def __init__(self, bot: BotT, db_engine: AsyncEngine) -> None:
        super().__init__(bot)
        self.db_engine = db_engine
        self.cached_guild_tcmd_data: OrderedDict[
            int, GuildTextCommandData
        ] = OrderedDict()
        self.cached_guild_tcmd_data_maxlen = 100

    async def global_command_check(self, ctx: commands.Context[BotT]) -> None:
        pass

    async def guild_tcmd_data_exists(self, guild_id: int) -> bool:
        if guild_id in self.cached_guild_tcmd_data:
            return True

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            return bool(
                (
                    await conn.execute(
                        text(
                            f"SELECT EXISTS(SELECT 1 FROM '{DB_TABLE_PREFIX}guild_tcmd_states' "
                            "WHERE guild_id == :guild_id)"
                        ),
                        dict(guild_id=guild_id),
                    )
                ).first()[0]
            )

    async def fetch_guild_tcmd_data(self, guild_id: int) -> GuildTextCommandData:
        if guild_id in self.cached_guild_tcmd_data:
            return self.cached_guild_tcmd_data[guild_id]

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            result: Result = await conn.execute(
                text(
                    f"SELECT data FROM '{DB_TABLE_PREFIX}guild_tcmd_states' "
                    "WHERE guild_id == :guild_id"
                ),
                dict(guild_id=guild_id),
            )

            row: Any = result.one()
            guild_tcmd_data = pickle.loads(row.data)
            self.cached_guild_tcmd_data[guild_id] = guild_tcmd_data

        return guild_tcmd_data

    def create_guild_tcmd_data(self, guild_id: int) -> GuildTextCommandData:
        guild_tcmd_data: GuildTextCommandData = {
            "states": {
                ZERO_UUID: {  # fake root command is the parent command of itself and all other root text commands
                    "uuid": ZERO_UUID,
                    "parent_uuid": ZERO_UUID,
                    "enabled": 0b11,
                    "roles": {guild_id: True},  # guild_id is also the @everyone role ID
                    "channels": {
                        guild_id - 1: True
                    },  # guild_id-1 refers to all channels (including category channels)
                }
            }
        }

        return guild_tcmd_data

    async def update_guild_tcmd_data(
        self, guild_id: int, *tcmd_states: GuildTextCommandState
    ):
        guild_tcmd_data = self.cached_guild_tcmd_data.get(guild_id) or (
            await self.fetch_guild_tcmd_data(guild_id=guild_id)
            if (await self.guild_tcmd_data_exists(guild_id))
            else self.create_guild_tcmd_data(guild_id)
        )
        for tcmd_state in tcmd_states:
            if tcmd_state["uuid"] in guild_tcmd_data:
                guild_tcmd_data["states"][tcmd_state["uuid"]].update(tcmd_state)
            else:
                guild_tcmd_data["states"][tcmd_state["uuid"]] = tcmd_state

        await self.save_guild_tcmd_data(guild_id, guild_tcmd_data)

    async def save_guild_tcmd_data(self, guild_id: int, data: GuildTextCommandData):
        self.cached_guild_tcmd_data[guild_id] = data
        if len(self.cached_guild_tcmd_data) > self.cached_guild_tcmd_data_maxlen:
            self.cached_guild_tcmd_data.popitem(last=False)

        pickled_data = pickle.dumps(data)

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            if bool(
                (
                    await conn.execute(
                        text(
                            f"SELECT EXISTS(SELECT 1 FROM '{DB_TABLE_PREFIX}guild_tcmd_states' "
                            "WHERE guild_id == :guild_id)"
                        ),
                        dict(guild_id=guild_id),
                    )
                ).first()[0]
            ):
                await conn.execute(
                    text(
                        f"UPDATE '{DB_TABLE_PREFIX}guild_tcmd_states' "
                        "SET (data = :data) "
                        f"FROM '{DB_TABLE_PREFIX}guild_tcmd_states' as guild_tcmd_states "
                        "WHERE guild_tcmd_states.guild_id == :guild_id"
                    ),
                    dict(guild_id=guild_id, data=pickled_data),
                )

            else:
                await conn.execute(
                    text(
                        f"INSERT INTO '{DB_TABLE_PREFIX}guild_tcmd_states' "
                        "VALUES (guild_id == :guild_id, data = :data) "
                    ),
                    dict(guild_id=guild_id, data=pickled_data),
                )

            await conn.commit()

    @commands.has_guild_permissions(administrator=True)
    @commands.group(invoke_without_command=True)
    async def tcm(self, ctx: commands.Context[BotT]):
        pass

    @commands.has_guild_permissions(administrator=True)
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=True)
    @tcm.command(name="set")
    @kwarg_command()
    async def tcm_set(
        self,
        ctx: commands.Context[BotT],
        tcmd_names: Union[Parens[str, ...], str],
        *setting_pairs: Parens[
            Union[
                discord.Role,
                discord.TextChannel,
                discord.VoiceChannel,
                discord.ForumChannel,
                Literal[
                    "all channels",
                    "All Channels",
                    "All channels",
                    "all Channels",
                    "ALL CHANNELS",
                ],
            ],
            bool,
        ],
        enabled: bool = True,
        subcommands_enabled: bool = True,
    ):
        assert ctx.guild

        role_overrides = {}
        channel_overrides = {}

        tcmd_objs: list[commands.Command] = []
        if isinstance(tcmd_names, str):
            if TYPE_CHECKING:
                Parens = tuple
            tcmd_names = (tcmd_names,)

        for tcmd_name in tcmd_names:
            tcmd_obj = ctx.bot.get_command(tcmd_name)
            if tcmd_obj is None:
                raise commands.CommandInvokeError(
                    commands.CommandNotFound(f'Command "{tcmd_name}" is not found')
                )

            tcmd_objs.append(tcmd_obj)

        for target, value in setting_pairs:
            if isinstance(target, str) and target.casefold() == "all channels":
                channel_overrides[ctx.guild.id - 1] = value

            elif isinstance(target, discord.abc.GuildChannel):
                channel_overrides[target.id] = value

            elif isinstance(target, discord.Role):
                role_overrides[target.id] = value

        tcmd_states: list[GuildTextCommandState] = []

        for tcmd_obj in tcmd_objs:
            tcmd_state = {}
            tcmd_state["uuid"] = str(
                tcmd_obj.extras.get("uuid") or UUID(int=hash(tcmd_obj.qualified_name))
            )
            tcmd_state["parent_uuid"] = ZERO_UUID
            if isinstance(tcmd_obj.parent, commands.Command):
                tcmd_state["parent_uuid"] = str(
                    tcmd_obj.parent.extras.get("uuid")
                    or UUID(int=hash(tcmd_obj.parent.qualified_name))
                )

            tcmd_state["enabled"] = subcommands_enabled << 1 | enabled

            if role_overrides:
                tcmd_state["roles"] = role_overrides.copy()

            if channel_overrides:
                tcmd_state["channels"] = channel_overrides.copy()

            tcmd_states.append(tcmd_state)  # type: ignore

        await self.update_guild_tcmd_data(ctx.guild.id, *tcmd_states)

    @commands.has_guild_permissions(administrator=True)
    @tcm.command(name="set")
    async def tcm_clear(
        self, ctx: commands.Context[BotT], cmds: Union[Parens[str, ...], str]
    ):
        pass
