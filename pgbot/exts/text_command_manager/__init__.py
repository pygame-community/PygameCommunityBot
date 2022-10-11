from collections import ChainMap, OrderedDict
from hashlib import sha1
import pickle
from typing import TYPE_CHECKING, Any, Literal, Optional, Union
from uuid import UUID

import discord
from discord.ext import commands
from snakecore.commands.converters import Parens
from snakecore.commands.decorators import kwarg_command
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.engine import Result
from sqlalchemy import text

from ...bot import PygameBot
from ..base import BaseCommandCog
from .constants import TABLE_NAME_PREFIX, ZERO_UUID
from ._types import GuildTextCommandState
from .migrations import MIGRATIONS

__version__ = "0.1.0"

BotT = PygameBot

if TYPE_CHECKING:
    Parens = tuple


class TextCommandManager(BaseCommandCog, name="text-command-manager"):
    def __init__(self, bot: BotT, db_engine: AsyncEngine) -> None:
        super().__init__(bot)
        self.db_engine = db_engine
        self.cached_guild_tcmd_state_maps: OrderedDict[
            int, dict[str, GuildTextCommandState]
        ] = OrderedDict()
        self.cached_guild_tcmd_state_maps_maxlen = 100
        bot.add_check(self.global_tcmd_check)

    async def global_tcmd_check(self, ctx: commands.Context[BotT]):
        if not (
            ctx.guild
            and isinstance(ctx.author, discord.Member)
            and isinstance(ctx.channel, discord.abc.GuildChannel)
            and ctx.command
        ):
            return False
        elif not (
            isinstance(ctx.command, commands.Command)
            and await self.guild_tcmd_states_exists(ctx.guild.id)
        ):
            return True

        guild_tcmd_state_map: dict[
            str, GuildTextCommandState
        ] = await self.fetch_guild_tcmd_states(ctx.guild.id)

        # is_admin = ctx.author.guild_permissions.administrator

        tcmd_states = []
        for i, tcmd_obj in enumerate((ctx.command, *ctx.command.parents)):
            tcmd_uuid = tcmd_obj.extras.get("uuid")
            if tcmd_uuid is not None:
                try:
                    if isinstance(tcmd_uuid, str):
                        tcmd_uuid = str(UUID(tcmd_uuid))
                    elif isinstance(tcmd_uuid, UUID):
                        tcmd_uuid = str(tcmd_uuid)
                except (TypeError, ValueError):
                    tcmd_uuid = None

            if tcmd_uuid is None:
                qualname_sha1 = int(
                    sha1(
                        tcmd_obj.qualified_name.encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest(),
                    base=16,
                )
                tcmd_uuid = str(
                    UUID(int=qualname_sha1 >> max(qualname_sha1.bit_length() - 128, 0))
                )  # truncate to <= 128 bits

            tcmd_states.append(guild_tcmd_state_map.get(tcmd_uuid, {}))

        tcmd_states.append(guild_tcmd_state_map[ZERO_UUID])  # get fake root command

        tcmd_disabled = False
        missing_channel_permissions = False
        missing_role_permissions = False

        all_channels_id = ctx.guild.id - 1
        everyone_role_id = ctx.guild.id

        tcmd_state_channel_chainmap = ChainMap(
            *(tcmd_state.get("channels", {}) for tcmd_state in tcmd_states)
        )
        tcmd_state_role_chainmap = ChainMap(
            *(tcmd_state.get("roles", {}) for tcmd_state in tcmd_states)
        )

        for i, tcmd_state in enumerate(tcmd_states):
            if not tcmd_state:
                continue

            if (
                i == 0
                and not tcmd_state["enabled"] & 0b01
                or i > 0
                and not tcmd_state["enabled"] & 0b10
            ):
                tcmd_disabled = True  # command is disabled via its command bit or a parent's subcommand bit
                break

            channel_overrides = tcmd_state.get("channels")
            if channel_overrides:
                if all_channels_id in channel_overrides:
                    target_channel_overrides = (
                        channel_overrides
                        if i == 0
                        else ChainMap(*tcmd_state_channel_chainmap.maps[: i + 1])
                    )  # pick overrides of current command and possibly preceding subcommands
                    if not channel_overrides[all_channels_id] and not (
                        ctx.channel.id in target_channel_overrides
                        or (
                            ctx.channel.category_id if ctx.channel.category_id else 0
                        )  # 0 is invalid
                        in target_channel_overrides
                    ):
                        missing_channel_permissions = True
                        break
                elif (
                    i == len(tcmd_states) - 1
                ):  # we're at the fake root command and "All Channels" is not configured as an override on any preceding commands
                    target_channel_overrides = tcmd_state_channel_chainmap  # pick overrides of target command and parent commands
                    if not (
                        ctx.channel.id in target_channel_overrides
                        or (ctx.channel.category_id if ctx.channel.category_id else 0)
                        in target_channel_overrides
                    ):
                        missing_channel_permissions = True
                        break

            role_overrides = tcmd_state.get("roles")
            if role_overrides:
                if everyone_role_id in role_overrides:
                    target_role_overrides = (
                        role_overrides
                        if i == 0
                        else ChainMap(*tcmd_state_role_chainmap.maps[: i + 1])
                    )  # pick overrides of current command and possibly preceding subcommands
                    if not any(
                        role.id in target_role_overrides
                        and target_role_overrides[role.id]
                        for role in ctx.author.roles
                    ):  # will always include @everyone role
                        missing_role_permissions = True
                        break
                elif (
                    i == len(tcmd_states) - 1
                ):  # we're at the fake root command and @everyone role is not configured as an override on any preceding commands
                    target_role_overrides = tcmd_state_role_chainmap  # pick overrides of target command and parent commands
                    if not any(
                        role.id in target_role_overrides for role in ctx.author.roles
                    ):
                        missing_role_permissions = True
                        break

        if tcmd_disabled:
            raise commands.DisabledCommand(
                f'The "{ctx.command.qualified_name}" command is disabled in this guild/server.'
            )
        elif missing_channel_permissions or missing_role_permissions:
            # sidestep __init__ constructor function
            missing_perms_exc = commands.MissingPermissions.__new__(
                commands.MissingPermissions
            )
            missing_perms_exc.missing_permissions = []
            commands.CheckFailure.__init__(
                missing_perms_exc,
                "You don't have enough permissions to run the "
                f'"{ctx.command.qualified_name}" command'
                + (" in this channel." if missing_channel_permissions else "."),
            )

            raise missing_perms_exc

        return True

    async def guild_tcmd_states_exists(self, guild_id: int) -> bool:
        if guild_id in self.cached_guild_tcmd_state_maps:
            return True

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            return bool(
                (
                    await conn.execute(
                        text(
                            f"SELECT EXISTS(SELECT 1 FROM '{TABLE_NAME_PREFIX}guild_tcmd_states' "
                            "WHERE guild_id == :guild_id LIMIT 1)"
                        ),
                        dict(guild_id=guild_id),
                    )
                ).first()[0]
            )

    def create_guild_root_tcmd_state(self, guild_id: int) -> GuildTextCommandState:
        return {
            "tcmd_uuid": ZERO_UUID,
            "qualified_name": "",
            "parent_tcmd_uuid": ZERO_UUID,
            "enabled": 0b11,  # enable this root command and all subcommands by default
            "roles": {guild_id: True},  # guild_id is also the @everyone role ID
            "channels": {
                guild_id - 1: True
            },  # guild_id-1 refers to all channels (including category channels)
        }  # fake root command is the parent command of itself and all other root text commands

    async def fetch_guild_tcmd_states(self, guild_id: int):
        if guild_id in self.cached_guild_tcmd_state_maps:
            return self.cached_guild_tcmd_state_maps[guild_id]

        guild_tcmd_state_map: dict[str, GuildTextCommandState] = {}

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            result: Result = await conn.execute(
                text(
                    f"SELECT * FROM '{TABLE_NAME_PREFIX}guild_tcmd_states' "
                    "WHERE guild_id == :guild_id"
                ),
                dict(guild_id=guild_id),
            )

            for row in result.all():
                row_dict = row._asdict()  # type: ignore
                guild_tcmd_state_map[row_dict["tcmd_uuid"]] = row_dict
                guild_tcmd_state_map[row_dict["qualified_name"]] = row_dict

                for k in ("channels", "roles"):
                    if k in row_dict:
                        if row_dict[k] is None:
                            del row_dict[k]
                        else:
                            row_dict[k] = pickle.loads(row_dict[k])

        if not guild_tcmd_state_map:
            raise LookupError(
                f"No text command state data could be found for guild ID {guild_id}"
            )

        self.cached_guild_tcmd_state_maps[guild_id] = guild_tcmd_state_map

        return guild_tcmd_state_map

    async def update_guild_tcmd_states(
        self, guild_id: int, *tcmd_states: GuildTextCommandState
    ):
        if (
            guild_tcmd_state_map := self.cached_guild_tcmd_state_maps.get(guild_id)
        ) is not None:
            for tcmd_state in tcmd_states:
                guild_tcmd_state_map[tcmd_state["tcmd_uuid"]] = tcmd_state
                guild_tcmd_state_map[tcmd_state["qualified_name"]] = tcmd_state

        await self.save_guild_tcmd_states(guild_id, *tcmd_states)

    async def save_guild_tcmd_states(
        self, guild_id: int, *tcmd_states: GuildTextCommandState
    ):
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            param_list = []

            for tcmd_state in tcmd_states:
                params: Any = tcmd_state.copy()
                params["guild_id"] = guild_id
                for k in ("channels", "roles"):
                    if k not in params or not params[k]:
                        params[k] = None
                    else:
                        params[k] = pickle.dumps(params[k])

                param_list.append(params)

            if bool(
                (
                    await conn.execute(
                        text(
                            f"SELECT EXISTS(SELECT 1 FROM '{TABLE_NAME_PREFIX}guild_tcmd_states' "
                            "WHERE guild_id == :guild_id LIMIT 1)"
                        ),
                        dict(guild_id=guild_id),
                    )
                ).first()[0]
            ):
                target_columns = ", ".join(
                    (
                        f"{k} = :{k}"
                        for k in (
                            "parent_tcmd_uuid",
                            "qualified_name",
                            "enabled",
                            "channels",
                            "roles",
                        )
                    )
                )
                for param in param_list:
                    await conn.execute(
                        text(
                            f"UPDATE '{TABLE_NAME_PREFIX}guild_tcmd_states' AS guild_tcmd_states "
                            f"SET {target_columns} "
                            "WHERE guild_tcmd_states.guild_id == :guild_id AND guild_tcmd_states.tcmd_uuid == :tcmd_uuid"
                        ),
                        param,
                    )

            else:
                target_columns = (
                    "guild_id",
                    "tcmd_uuid",
                    "parent_tcmd_uuid",
                    "qualified_name",
                    "enabled",
                    "channels",
                    "roles",
                )
                await conn.execute(
                    text(
                        "INSERT INTO "
                        f"'{TABLE_NAME_PREFIX}guild_tcmd_states' ({', '.join(target_columns)}) "
                        f"VALUES ({', '.join(':'+colname for colname in target_columns)})"
                    ),
                    param_list,
                )

    async def delete_guild_tcmd_states(
        self, guild_id: int, *tcmd_states: GuildTextCommandState
    ):
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            param_list = []

            for tcmd_state in tcmd_states:
                if (
                    guild_id in self.cached_guild_tcmd_state_maps
                    and tcmd_state["tcmd_uuid"]
                    in self.cached_guild_tcmd_state_maps[guild_id]
                ):
                    del self.cached_guild_tcmd_state_maps[guild_id]

                params: Any = tcmd_state.copy()
                params["guild_id"] = guild_id

                param_list.append(params)

            await conn.execute(
                text(
                    f"DELETE FROM '{TABLE_NAME_PREFIX}guild_tcmd_states' "
                    "AS guild_tcmd_states "
                    "WHERE guild_tcmd_states.guild_id == :guild_id AND "
                    "(guild_tcmd_states.parent_tcmd_uuid == :tcmd_uuid "
                    "OR guild_tcmd_states.tcmd_uuid == :tcmd_uuid)"
                ),
                param_list,
            )  # delete entry for command and all its subcommands

    async def delete_all_guild_tcmd_states(
        self,
        guild_id: int,
    ):
        if guild_id in self.cached_guild_tcmd_state_maps:
            del self.cached_guild_tcmd_state_maps[guild_id]

        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    f"DELETE FROM '{TABLE_NAME_PREFIX}guild_tcmd_states' "
                    "AS guild_tcmd_states "
                    "WHERE guild_tcmd_states.guild_id == :guild_id"
                ),
                dict(guild_id=guild_id),
            )  # delete entry for command and all its subcommands

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
        *channel_or_role_overrides: Parens[
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
                    "everyone",
                    "@everyone",
                    "Everyone",
                    "EVERYONE",
                ],
            ],
            bool,
        ],
        enabled: Optional[bool] = None,
        subcommands_enabled: Optional[bool] = None,
    ):
        assert ctx.guild

        role_overrides = {}
        channel_overrides = {}
        tcmd_states: list[GuildTextCommandState] = []

        if isinstance(tcmd_names, str):
            tcmd_names = (tcmd_names,)

        for target, value in channel_or_role_overrides:
            if isinstance(target, str):
                if target.casefold() == "all channels":
                    channel_overrides[ctx.guild.id - 1] = value

                elif target.casefold() in ("everyone", "@everyone"):
                    role_overrides[ctx.guild.id] = value

            elif isinstance(target, discord.abc.GuildChannel):
                channel_overrides[target.id] = value

            elif isinstance(target, discord.Role):
                role_overrides[target.id] = value

        if not (
            guild_tcmd_states_exists := await self.guild_tcmd_states_exists(
                ctx.guild.id
            )
        ):
            tcmd_states.append(self.create_guild_root_tcmd_state(ctx.guild.id))

        for tcmd_name in tcmd_names:
            tcmd_obj = ctx.bot.get_command(tcmd_name)
            if tcmd_obj is None:
                if (
                    tcmd_name
                    and guild_tcmd_states_exists
                    and tcmd_name
                    in (
                        tcmd_state_map := await self.fetch_guild_tcmd_states(
                            ctx.guild.id
                        )
                    )
                ):
                    tcmd_state = tcmd_state_map[tcmd_name].copy()

                    tcmd_state["enabled"] = (  # only update if changes were specified
                        subcommands_enabled
                        if subcommands_enabled is not None
                        else bool(tcmd_state["enabled"] & 0b10)
                    ) << 1 | (
                        enabled
                        if enabled is not None
                        else bool(tcmd_state["enabled"] & 0b01)
                    )

                    if channel_overrides:
                        tcmd_state["channels"] = channel_overrides.copy()

                    if role_overrides:
                        tcmd_state["roles"] = role_overrides.copy()
                else:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f'No data could be found for a text command named "{tcmd_name}"'
                        )
                    )
            else:
                if guild_tcmd_states_exists:
                    tcmd_state_map = await self.fetch_guild_tcmd_states(ctx.guild.id)
                else:
                    tcmd_state_map = {}

                for i, current_tcmd in enumerate((tcmd_obj, *tcmd_obj.parents)):
                    tcmd_uuid = current_tcmd.extras.get("uuid")
                    if tcmd_uuid is not None:
                        try:
                            if isinstance(tcmd_uuid, str):
                                tcmd_uuid = str(UUID(tcmd_uuid))
                            elif isinstance(tcmd_uuid, UUID):
                                tcmd_uuid = str(tcmd_uuid)
                        except (TypeError, ValueError):
                            tcmd_uuid = None

                    if tcmd_uuid is None:
                        qualname_sha1 = int(
                            sha1(
                                current_tcmd.qualified_name.encode("utf-8"),
                                usedforsecurity=False,
                            ).hexdigest(),
                            base=16,
                        )
                        tcmd_uuid = str(
                            UUID(
                                int=qualname_sha1
                                >> max(qualname_sha1.bit_length() - 128, 0)
                            )
                        )  # truncate to <= 128 bits
                    else:
                        tcmd_uuid = str(tcmd_uuid)

                    tcmd_state = tcmd_state_map.get(tcmd_uuid, {})
                    tcmd_state["qualified_name"] = current_tcmd.qualified_name

                    tcmd_state["tcmd_uuid"] = tcmd_uuid

                    tcmd_state["parent_tcmd_uuid"] = ZERO_UUID
                    if isinstance(current_tcmd.parent, commands.Command):
                        parent_tcmd_uuid = current_tcmd.parent.extras.get("uuid")
                        if parent_tcmd_uuid is not None:
                            try:
                                if isinstance(parent_tcmd_uuid, str):
                                    parent_tcmd_uuid = str(UUID(parent_tcmd_uuid))
                                elif isinstance(tcmd_uuid, UUID):
                                    parent_tcmd_uuid = str(parent_tcmd_uuid)
                            except (TypeError, ValueError):
                                parent_tcmd_uuid = None

                        if parent_tcmd_uuid is None:
                            qualname_sha1 = int(
                                sha1(
                                    current_tcmd.parent.qualified_name.encode("utf-8"),
                                    usedforsecurity=False,
                                ).hexdigest(),
                                base=16,
                            )
                            parent_tcmd_uuid = str(
                                UUID(
                                    int=qualname_sha1
                                    >> max(qualname_sha1.bit_length() - 128, 0)
                                )
                            )  # truncate to <= 128 bits

                        tcmd_state["parent_tcmd_uuid"] = parent_tcmd_uuid

                    if i == 0:
                        # only update if changes were specified, initialize to enabled if no previous settings exist
                        tcmd_state["enabled"] = (
                            subcommands_enabled
                            if subcommands_enabled is not None
                            else bool(tcmd_state.get("enabled", 0b10) & 0b10)
                        ) << 1 | (
                            enabled
                            if enabled is not None
                            else bool(tcmd_state.get("enabled", 0b01) & 0b01)
                        )

                        if channel_overrides:
                            tcmd_state["channels"] = channel_overrides.copy()

                        if role_overrides:
                            tcmd_state["roles"] = role_overrides.copy()
                    else:
                        if "enabled" not in tcmd_state:
                            tcmd_state["enabled"] = 0b11

                    tcmd_states.append(tcmd_state)  # type: ignore

        await self.update_guild_tcmd_states(ctx.guild.id, *tcmd_states)

    @commands.has_guild_permissions(administrator=True)
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=True)
    @tcm.command(name="setroot")
    @kwarg_command()
    async def tcm_setroot(
        self,
        ctx: commands.Context[BotT],
        *channel_or_role_overrides: Parens[
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
                    "everyone",
                    "@everyone",
                    "Everyone",
                    "EVERYONE",
                ],
            ],
            bool,
        ],
    ):
        assert ctx.guild

        role_overrides = {}
        channel_overrides = {}

        for target, value in channel_or_role_overrides:
            if isinstance(target, str):
                if target.casefold() == "all channels":
                    channel_overrides[ctx.guild.id - 1] = value

                elif target.casefold() in ("everyone", "@everyone"):
                    role_overrides[ctx.guild.id] = value

            elif isinstance(target, discord.abc.GuildChannel):
                channel_overrides[target.id] = value

            elif isinstance(target, discord.Role):
                role_overrides[target.id] = value

        if await self.guild_tcmd_states_exists(ctx.guild.id) and ZERO_UUID in (
            tcmd_state_map := await self.fetch_guild_tcmd_states(ctx.guild.id)
        ):
            tcmd_state = tcmd_state_map[ZERO_UUID].copy()
        else:
            tcmd_state = self.create_guild_root_tcmd_state(ctx.guild.id)
        if channel_overrides:
            tcmd_state["channels"] = channel_overrides.copy()

        if role_overrides:
            tcmd_state["roles"] = role_overrides.copy()

        await self.update_guild_tcmd_states(ctx.guild.id, tcmd_state)  # type: ignore

    @commands.has_guild_permissions(administrator=True)
    @tcm.command(name="clear")
    @kwarg_command()
    async def tcm_clear(
        self,
        ctx: commands.Context[BotT],
        tcmd_names: Union[Parens[str, ...], str],
    ):
        assert ctx.guild

        if isinstance(tcmd_names, str):
            tcmd_names = (tcmd_names,)

        for tcmd_name in tcmd_names:
            if await self.guild_tcmd_states_exists(ctx.guild.id) and tcmd_name in (
                tcmd_state_map := await self.fetch_guild_tcmd_states(ctx.guild.id)
            ):
                await self.delete_guild_tcmd_states(
                    ctx.guild.id, tcmd_state_map[tcmd_name].copy()
                )
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        f'No data could be found for a text command named "{tcmd_name}"'
                    )
                )

    @commands.has_guild_permissions(administrator=True)
    @tcm.command(name="clearall")
    @kwarg_command()
    async def tcm_clearall(
        self,
        ctx: commands.Context[BotT],
    ):
        assert ctx.guild
        await self.delete_all_guild_tcmd_states(ctx.guild.id)

    @commands.has_guild_permissions(administrator=True)
    @tcm.command(name="clearoverrides")
    @kwarg_command()
    async def tcm_clearoverrides(
        self,
        ctx: commands.Context[BotT],
        tcmd_names: Union[Parens[str, ...], str],
        *,
        channels: bool = True,
        roles: bool = True,
    ):
        assert ctx.guild

        if isinstance(tcmd_names, str):
            tcmd_names = (tcmd_names,)

        for tcmd_name in tcmd_names:
            if await self.guild_tcmd_states_exists(ctx.guild.id) and tcmd_name in (
                tcmd_state_map := await self.fetch_guild_tcmd_states(ctx.guild.id)
            ):
                tcmd_state = tcmd_state_map[tcmd_name].copy()

                if "channels" in tcmd_state and channels:
                    del tcmd_state["channels"]

                if "roles" in tcmd_state and roles:
                    del tcmd_state["roles"]

                await self.update_guild_tcmd_states(ctx.guild.id, tcmd_state)
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        f'No data could be found for a text command named "{tcmd_name}"'
                    )
                )

    @commands.has_guild_permissions(administrator=True)
    @tcm.command(name="clearrootoverrides")
    async def tcm_clearrootoverrides(
        self,
        ctx: commands.Context[BotT],
        *,
        channels: bool = True,
        roles: bool = True,
    ):
        assert ctx.guild

        if await self.guild_tcmd_states_exists(ctx.guild.id) and ZERO_UUID in (
            tcmd_state_map := await self.fetch_guild_tcmd_states(ctx.guild.id)
        ):
            tcmd_state = tcmd_state_map[ZERO_UUID].copy()
            if "channels" in tcmd_state and channels:
                del tcmd_state["channels"]

            if "roles" in tcmd_state and roles:
                del tcmd_state["roles"]

            await self.update_guild_tcmd_states(ctx.guild.id, tcmd_state)
        else:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    f"No data could be found for root pseudo-command of this guild/server."
                )
            )


async def setup(bot: BotT):
    db_engine = bot.get_database()
    if not isinstance(db_engine, AsyncEngine):
        raise RuntimeError(
            "Could not find primary database interface of type 'sqlalchemy.ext.asyncio.AsyncEngine'"
        )
    elif db_engine.name not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Unsupported database engine: {db_engine.name}")

    first_setup = False
    try:
        extension_data = await bot.read_extension_data(__name__)
    except LookupError:
        first_setup = True
        extension_data = dict(name=__name__, table_name_prefix=TABLE_NAME_PREFIX)
        await bot.create_extension_data(**extension_data, version=__version__)

    stored_version = "0.0.0" if first_setup else str(extension_data["version"])
    if stored_version > __version__:
        raise RuntimeError(
            f'Extension data is incompatible: Data version "{stored_version}" exceeds extension version "{__version__}"'
        )

    elif stored_version < __version__:
        conn: AsyncConnection
        async with db_engine.begin() as conn:
            for vi in sorted(MIGRATIONS[db_engine.name].keys()):
                if vi > stored_version:
                    await conn.execute(text(MIGRATIONS[db_engine.name][vi]))

        extension_data["version"] = __version__
        await bot.update_extension_data(**extension_data)

    await bot.add_cog(TextCommandManager(bot, db_engine))
