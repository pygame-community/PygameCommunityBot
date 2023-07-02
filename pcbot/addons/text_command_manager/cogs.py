"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
from collections import ChainMap, OrderedDict
import enum
from hashlib import sha1
import pickle
import re
import time
from typing import Any, Literal
from uuid import UUID

import discord
from discord.types.embed import Embed as EmbedDict, EmbedField
from discord.ext import commands
import snakecore
from snakecore.commands.converters import Parens
from snakecore.commands.decorators import flagconverter_kwargs
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.engine import Result
from sqlalchemy import text

from ... import __version__
from ...bot import PygameCommunityBot
from ...base import BaseExtensionCog
from .constants import DB_PREFIX, ZERO_UUID, UUID_PATTERN
from ._types import GuildTextCommandState

BotT = PygameCommunityBot

ChannelOrRoleOverrides = list[
    tuple[
        discord.Role
        | discord.TextChannel
        | discord.VoiceChannel
        | discord.ForumChannel
        | Literal[
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
        bool,
    ]
]


class text_commandCantRunReason(enum.Enum):
    BAD_CONTEXT = enum.auto()
    DISABLED = enum.auto()
    DISABLED_BY_PARENT = enum.auto()
    MISSING_ROLE_PERMISSIONS = enum.auto()
    MISSING_CHANNEL_PERMISSIONS = enum.auto()


class TextCommandManagerCog(BaseExtensionCog, name="text-command-manager"):
    """A text command manager to meet all your text
    command management needs, from enabling/disabling commands
    and/or their subcommands to setting channel or role-specific permissions
    and applying mock roles for testing."""

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        revision_number: int,
        theme_color: int = 0,
    ) -> None:
        super().__init__(bot)
        self.db_engine = db_engine
        self.revisiob_number = revision_number
        self.cached_guild_text_command_state_maps: OrderedDict[
            int, dict[str, GuildTextCommandState]
        ] = OrderedDict()
        self.cached_guild_text_command_state_maps_maxlen = 100
        bot.add_check(self.global_text_command_check)
        self.theme_color = int(theme_color)
        self.guild_mock_roles: dict[
            int, dict[int, tuple[tuple[int, ...], asyncio.Task[None], float, float]]
        ] = {}

    async def global_text_command_check(self, ctx: commands.Context[BotT]):
        if not (
            ctx.guild
            and isinstance(ctx.author, discord.Member)
            and isinstance(ctx.channel, (discord.abc.GuildChannel, discord.Thread))
            and ctx.command
        ):
            return False
        elif not (
            isinstance(ctx.command, commands.Command)
            and await self.guild_text_command_states_exists(ctx.guild.id)
        ):
            return (
                True  # nothing was configured for target guild, always allow invocation
            )

        cannot_run_reason = await self.text_command_cannot_run_reason(ctx)

        if not cannot_run_reason:
            return True

        elif cannot_run_reason is text_commandCantRunReason.DISABLED:
            raise commands.CheckFailure(
                f'The "{ctx.command.qualified_name}" command is disabled in this '
                "guild/server."
            )
        elif cannot_run_reason is text_commandCantRunReason.DISABLED_BY_PARENT:
            split_parent_qualname = ctx.command.qualified_name.split()[:-1]
            possible_parent_qualnames = " or ".join(
                f"\"{' '.join(split_parent_qualname[:i])}\""
                for i in range(1, len(split_parent_qualname) + 1)
            )

            raise commands.CheckFailure(
                f'The "{ctx.command.qualified_name}" command is disabled in this '
                "guild/server, due to subcommands being disabled by a parent command "
                f"({possible_parent_qualnames})."
            )
        elif cannot_run_reason in (
            text_commandCantRunReason.MISSING_CHANNEL_PERMISSIONS,
            text_commandCantRunReason.MISSING_ROLE_PERMISSIONS,
        ):
            # sidestep __init__ constructor function
            missing_perms_exc = commands.MissingPermissions.__new__(
                commands.MissingPermissions
            )
            missing_perms_exc.missing_permissions = []
            commands.CheckFailure.__init__(
                missing_perms_exc,
                "You don't have enough permissions to run the "
                f'"{ctx.command.qualified_name}" command'
                + (
                    " in this channel."
                    if cannot_run_reason
                    is text_commandCantRunReason.MISSING_CHANNEL_PERMISSIONS
                    else " in this guild/server."
                ),
            )

            raise missing_perms_exc

        return True

    async def guild_text_command_states_exists(self, guild_id: int) -> bool:
        if guild_id in self.cached_guild_text_command_state_maps:
            return True

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            return bool(
                (
                    await conn.execute(
                        text(
                            f"SELECT EXISTS(SELECT 1 FROM '{DB_PREFIX}guild_text_command_states' "
                            "WHERE guild_id == :guild_id LIMIT 1)"
                        ),
                        dict(guild_id=guild_id),
                    )
                ).scalar()
            )

    async def text_command_cannot_run_reason(
        self, ctx: commands.Context[BotT], command: commands.Command | None = None
    ) -> text_commandCantRunReason | None:
        if not (
            ctx.guild
            and isinstance(ctx.author, discord.Member)
            and isinstance(ctx.channel, discord.abc.GuildChannel)
            and (command or ctx.command)
        ):
            return text_commandCantRunReason.BAD_CONTEXT
        elif not (
            isinstance(ctx.command, commands.Command)
            and await self.guild_text_command_states_exists(ctx.guild.id)
        ):  # nothing was configured for target guild, always allow invocation
            return None

        everyone_role_id = ctx.guild.id
        all_channels_id = ctx.guild.id - 1

        category_id = ctx.channel.category_id if ctx.channel.category_id else 0

        using_mock_roles = False

        command = command or ctx.command

        if (
            ctx.guild.id in self.guild_mock_roles
            and ctx.author.id in self.guild_mock_roles[ctx.guild.id]
        ):
            using_mock_roles = True
            role_ids, *_ = self.guild_mock_roles[ctx.guild.id][ctx.author.id]
        else:
            role_ids = tuple(role.id for role in ctx.author.roles)

        guild_text_command_state_map: dict[
            str, GuildTextCommandState
        ] = await self.fetch_guild_text_command_states(ctx.guild.id)

        is_admin = ctx.author.guild_permissions.administrator

        text_command_states: list[GuildTextCommandState] = []
        for i, text_command_obj in enumerate((command, *command.parents)):
            text_command_uuid = text_command_obj.extras.get("uuid")
            if text_command_uuid is not None:
                try:
                    if isinstance(text_command_uuid, str):
                        text_command_uuid = str(UUID(text_command_uuid))
                    elif isinstance(text_command_uuid, UUID):
                        text_command_uuid = str(text_command_uuid)
                except (TypeError, ValueError):
                    text_command_uuid = None

            if text_command_uuid is None:
                qualname_sha1 = int(
                    sha1(
                        text_command_obj.qualified_name.encode("utf-8"),
                        usedforsecurity=False,
                    ).hexdigest(),
                    base=16,
                )
                text_command_uuid = str(
                    UUID(int=qualname_sha1 >> max(qualname_sha1.bit_length() - 128, 0))
                )  # truncate to <= 128 bits

            text_command_states.append(guild_text_command_state_map.get(text_command_uuid, {}))  # type: ignore

        text_command_states.append(
            guild_text_command_state_map[ZERO_UUID]
        )  # get fake root command

        text_command_state_channel_chainmap = ChainMap(
            *(
                text_command_state.get("channels", {})
                for text_command_state in text_command_states
            )
        )
        text_command_state_role_chainmap = ChainMap(
            *(
                text_command_state.get("roles", {})
                for text_command_state in text_command_states
            )
        )

        for i, text_command_state in enumerate(text_command_states):
            if not text_command_state:
                continue

            if i == 0 and not text_command_state["enabled"] & 0b01:
                return (
                    text_commandCantRunReason.DISABLED
                )  # command is disabled via its command bit
            elif i > 0 and not text_command_state["enabled"] & 0b10:
                return (
                    text_commandCantRunReason.DISABLED_BY_PARENT
                )  # command is disabled via a parent's subcommand bit

            if (
                not using_mock_roles
                and is_admin
                or using_mock_roles
                and command in (self.tcm_mockroles, self.tcm_clearmockroles)
            ):
                continue

            if channel_overrides := text_command_state.get("channels"):
                if all_channels_id in channel_overrides:
                    target_channel_overrides = (
                        channel_overrides
                        if i == 0
                        else ChainMap(
                            *text_command_state_channel_chainmap.maps[: i + 1]
                        )
                    )  # pick overrides of current command and possibly preceding subcommands

                    if (
                        target_channel_overrides[all_channels_id]
                        and not (
                            # a channel's category or the channel must not be disabled for permission to be granted
                            target_channel_overrides.get(
                                category_id,
                                True,
                            )
                            is True
                            and target_channel_overrides.get(ctx.channel.id, True)
                            is not False
                            or target_channel_overrides.get(ctx.channel.id, True)
                            is True
                        )
                    ) or (
                        not target_channel_overrides[all_channels_id]
                        and not (
                            # if a channel's category is enabled, the channel must not be disabled for permission to be granted
                            target_channel_overrides.get(
                                category_id,
                                False,
                            )
                            is True
                            and target_channel_overrides.get(ctx.channel.id, True)
                            is not False
                            or target_channel_overrides.get(ctx.channel.id, False)
                            is True
                        )
                    ):
                        return text_commandCantRunReason.MISSING_CHANNEL_PERMISSIONS
                elif (
                    i == len(text_command_states) - 1
                ):  # we're at the fake root command and "All Channels" is not configured as an override on any preceding commands,
                    # pretend as if it were set to False

                    # pick overrides of original command and all preceding parent commands
                    target_channel_overrides = text_command_state_channel_chainmap

                    if not (
                        # if a channel's category is enabled, the channel must not be disabled for permission to be granted
                        target_channel_overrides.get(
                            category_id,
                            False,
                        )
                        is True
                        and target_channel_overrides.get(ctx.channel.id, True)
                        is not False
                        or target_channel_overrides.get(ctx.channel.id, False) is True
                    ):
                        return text_commandCantRunReason.MISSING_CHANNEL_PERMISSIONS

            if role_overrides := text_command_state.get("roles"):
                if everyone_role_id in role_overrides:
                    target_role_overrides = (
                        role_overrides
                        if i == 0
                        else ChainMap(*text_command_state_role_chainmap.maps[: i + 1])
                    )  # pick overrides of current command and possibly preceding subcommands

                    if (
                        target_role_overrides[everyone_role_id]
                        and not (
                            (
                                none_disabled := all(
                                    target_role_overrides.get(role_ids[i], True)
                                    for i in range(1, len(role_ids))
                                )
                            )
                            or (
                                not none_disabled
                                and (
                                    any_enabled := any(
                                        target_role_overrides.get(role_ids[i], False)
                                        for i in range(1, len(role_ids))
                                    )
                                )
                            )
                        )
                    ) or (
                        not target_role_overrides[everyone_role_id]
                        and not any(
                            target_role_overrides.get(role_ids[i], False)
                            for i in range(1, len(role_ids))
                        )
                    ):  # will always include @everyone role
                        return text_commandCantRunReason.MISSING_ROLE_PERMISSIONS
                elif (
                    i == len(text_command_states) - 1
                ):  # we're at the fake root command and @everyone role is not configured as an override on any preceding commands
                    # pretend as if it were set to False
                    target_role_overrides = text_command_state_role_chainmap  # pick overrides of target command and parent commands
                    if not any(
                        target_role_overrides.get(role_ids[i], False)
                        for i in range(1, len(role_ids))
                    ):
                        return text_commandCantRunReason.MISSING_ROLE_PERMISSIONS

        return None

    async def text_command_can_run(
        self, ctx: commands.Context[BotT], command: commands.Command | None = None
    ) -> bool:
        return not await self.text_command_cannot_run_reason(ctx, command=command)

    def create_guild_root_text_command_state(
        self, guild_id: int
    ) -> GuildTextCommandState:
        return {
            "text_command_uuid": ZERO_UUID,
            "qualified_name": "",
            "parent_text_command_uuid": ZERO_UUID,
            "enabled": 0b11,  # enable this root command and all subcommands by default
            "roles": {guild_id: True},  # guild_id is also the @everyone role ID
            "channels": {
                guild_id - 1: True
            },  # guild_id-1 refers to all channels (including category channels)
        }  # fake root command is the parent command of itself and all other root text commands

    async def get_text_command_state_hierarchy(
        self, guild_id: int, text_command_state: GuildTextCommandState
    ):
        if guild_id in self.cached_guild_text_command_state_maps:
            guild_text_command_state_map = self.cached_guild_text_command_state_maps[
                guild_id
            ]
        else:
            guild_text_command_state_map = await self.fetch_guild_text_command_states(
                guild_id
            )

        state_hierarchy = [text_command_state]
        current_state = text_command_state

        if current_state["text_command_uuid"] == ZERO_UUID:
            return state_hierarchy

        while True:
            current_state = guild_text_command_state_map[
                current_state["parent_text_command_uuid"]
            ]
            state_hierarchy.append(current_state)
            if current_state["text_command_uuid"] == ZERO_UUID:
                break

        return state_hierarchy

    async def fetch_guild_text_command_states(self, guild_id: int):
        if guild_id in self.cached_guild_text_command_state_maps:
            return self.cached_guild_text_command_state_maps[guild_id]

        guild_text_command_state_map: dict[str, GuildTextCommandState] = {}

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            result: Result = await conn.execute(
                text(
                    f"SELECT * FROM '{DB_PREFIX}guild_text_command_states' "
                    "WHERE guild_id == :guild_id"
                ),
                dict(guild_id=guild_id),
            )

            for row in result.all():
                row_dict = row._asdict()  # type: ignore
                guild_text_command_state_map[row_dict["text_command_uuid"]] = row_dict  # type: ignore
                guild_text_command_state_map[row_dict["qualified_name"]] = row_dict  # type: ignore

                for k in ("channels", "roles"):
                    if k in row_dict:
                        if row_dict[k] is None:
                            del row_dict[k]
                        else:
                            row_dict[k] = pickle.loads(row_dict[k])

        if not guild_text_command_state_map:
            raise LookupError(
                f"No text command state data could be found for guild ID {guild_id}"
            )

        self.cached_guild_text_command_state_maps[
            guild_id
        ] = guild_text_command_state_map

        if (
            len(self.cached_guild_text_command_state_maps)
            > self.cached_guild_text_command_state_maps_maxlen
        ):
            self.cached_guild_text_command_state_maps.popitem(last=False)

        return guild_text_command_state_map

    async def update_guild_text_command_states(
        self, guild_id: int, *text_command_states: GuildTextCommandState
    ):
        if (
            guild_text_command_state_map := self.cached_guild_text_command_state_maps.get(
                guild_id
            )
        ) is not None:
            for text_command_state in text_command_states:
                guild_text_command_state_map[
                    text_command_state["text_command_uuid"]
                ] = text_command_state
                guild_text_command_state_map[
                    text_command_state["qualified_name"]
                ] = text_command_state

        await self.save_guild_text_command_states(guild_id, *text_command_states)

    async def save_guild_text_command_states(
        self, guild_id: int, *text_command_states: GuildTextCommandState
    ):
        param_list = []
        target_insert_columns = (
            "bot",
            "guild_id",
            "text_command_uuid",
            "parent_text_command_uuid",
            "qualified_name",
            "enabled",
            "channels",
            "roles",
        )
        target_update_set_columns = ", ".join(
            (
                f"{k} = :{k}"
                for k in (
                    "bot",
                    "parent_text_command_uuid",
                    "qualified_name",
                    "enabled",
                    "channels",
                    "roles",
                )
            )
        )

        for text_command_state in text_command_states:
            params: Any = text_command_state.copy()
            params["bot"] = self.bot.uid  # type: ignore
            params["guild_id"] = guild_id
            for k in ("channels", "roles"):
                if k not in params or not params[k]:
                    params[k] = None
                else:
                    params[k] = pickle.dumps(params[k])

            param_list.append(params)

        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO "
                    f"'{DB_PREFIX}guild_text_command_states' AS guild_text_command_states "
                    f"({', '.join(target_insert_columns)}) "
                    f"VALUES ({', '.join(':'+colname for colname in target_insert_columns)}) "
                    f"ON CONFLICT DO UPDATE SET {target_update_set_columns} "
                    "WHERE guild_text_command_states.guild_id == :guild_id AND "
                    "guild_text_command_states.text_command_uuid == :text_command_uuid"
                ),
                param_list,
            )

    async def delete_guild_text_command_states(
        self, guild_id: int, *text_command_states: GuildTextCommandState
    ):
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            param_list = []

            for text_command_state in text_command_states:
                if (
                    guild_id in self.cached_guild_text_command_state_maps
                    and text_command_state["text_command_uuid"]
                    in self.cached_guild_text_command_state_maps[guild_id]
                ):
                    del self.cached_guild_text_command_state_maps[guild_id]

                params: Any = text_command_state.copy()
                params["guild_id"] = guild_id

                param_list.append(params)

            await conn.execute(
                text(
                    f"DELETE FROM '{DB_PREFIX}guild_text_command_states' "
                    "AS guild_text_command_states "
                    "WHERE guild_text_command_states.guild_id == :guild_id AND "
                    "(guild_text_command_states.parent_text_command_uuid == :text_command_uuid "
                    "OR guild_text_command_states.text_command_uuid == :text_command_uuid)"
                ),
                param_list,
            )  # delete entry for command and all its subcommands

    async def delete_all_guild_text_command_states(
        self,
        guild_id: int,
    ):
        if guild_id in self.cached_guild_text_command_state_maps:
            del self.cached_guild_text_command_state_maps[guild_id]

        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    f"DELETE FROM '{DB_PREFIX}guild_text_command_states' "
                    "AS guild_text_command_states "
                    "WHERE guild_text_command_states.guild_id == :guild_id"
                ),
                dict(guild_id=guild_id),
            )  # delete entry for command and all its subcommands

    @commands.guild_only()
    @commands.group(
        invoke_without_command=True,
        extras=dict(response_deletion_with_reaction=True),
    )
    async def tcm(self, ctx: commands.Context[BotT]):
        """A text command manager to meet all your text
        command management needs,
        from enabling/disabling commands and/or their subcommands
        to setting channel or role-specific restrictions.
        To see existing settings, run the `tcm view` command.
        Use `tcm set` to alter text command settings.
        """
        await self.send_paginated_response_embeds(
            ctx,
            discord.Embed(
                title="Text Command Manager",
                description="A text command manager to meet all your text "
                "command management needs, "
                "from enabling/disabling commands and/or their subcommands "
                "to setting channel or role-specific restrictions.\n\n"
                "To see existing settings, run the `tcm view` command. "
                "Use `tcm set` to alter text command settings.",
                color=int(self.theme_color),
            ),
        )

    async def _delete_member_mock_roles(
        self, delay: float, guild_id: int, member_id: int
    ):
        try:
            await asyncio.sleep(delay)
            if guild_id in self.guild_mock_roles:
                if member_id in self.guild_mock_roles[guild_id]:
                    del self.guild_mock_roles[guild_id][member_id]

                if not self.guild_mock_roles[guild_id]:
                    del self.guild_mock_roles[guild_id]
        except asyncio.CancelledError:
            return

    @commands.has_guild_permissions(manage_roles=True)
    @tcm.command(
        name="mockroles",
        usage="[roles (Role)...]",
        extras=dict(response_deletion_with_reaction=True),
    )
    async def tcm_mockroles(
        self,
        ctx: commands.Context[BotT],
        *roles: discord.Role | Literal["everyone", "@everyone", "Everyone", "EVERYONE"],
    ):
        """Apply one or more ephemeral mock roles to yourself, to be used for testing
        text command permissions. Only 100 mock roles can be set at a time.
        You can't set mock roles that are higher than your current highest role.
        Mock roles automatically disappear after 5 minutes.

        __**Parameters:**__

        **`[roles (Role)...]`**
        > A role or sequence of roles to apply as mock roles.
        > If omitted, an embed of currently set mock roles will be sent.
        > 'everyone' can be speficied to refer to the default @everyone role
        (hidden guild ID role that applies to every server member).
        """
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        if len(roles) > 100:
            raise commands.CommandInvokeError(
                commands.CommandError("Cannot set more than 100 mock roles per member.")
            )

        role_list: list[discord.Role] = []
        highest_role_position = max(
            ctx.author.roles, key=lambda role: role.position
        ).position

        for role in roles:
            if isinstance(role, str) and role.lower() in ("everyone", "@everyone"):
                role = ctx.guild.get_role(ctx.guild.id)

            if isinstance(role, discord.Role):
                if role.position > highest_role_position:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            "Cannot set any mock roles higher than your highest role."
                        )
                    )

                role_list.append(role)

        main_embed = discord.Embed(
            title="Text Command Mock Roles",
            description=f"No mock roles found for {ctx.author.mention} .",
            color=int(self.theme_color),
        )

        role_ids = task = deletion_delay_secs = timestamp = None

        if (
            ctx.guild.id in self.guild_mock_roles
            and ctx.author.id in self.guild_mock_roles[ctx.guild.id]
        ):
            role_ids, task, deletion_delay_secs, timestamp = self.guild_mock_roles[
                ctx.guild.id
            ][ctx.author.id]
            if role_list:
                if not task.done():
                    task.cancel()
                del self.guild_mock_roles[ctx.guild.id][ctx.author.id]

        if role_list:
            if ctx.guild.id not in self.guild_mock_roles:
                self.guild_mock_roles[ctx.guild.id] = {}

            if ctx.author.id not in self.guild_mock_roles[ctx.guild.id]:
                deletion_delay_secs = 300.0
                task = asyncio.create_task(
                    self._delete_member_mock_roles(
                        deletion_delay_secs, ctx.guild.id, ctx.author.id
                    )
                )
                role_ids, task, deletion_delay_secs, timestamp = self.guild_mock_roles[
                    ctx.guild.id
                ][ctx.author.id] = (
                    tuple(role.id for role in role_list),
                    task,
                    deletion_delay_secs,
                    time.time(),
                )

        if role_ids and task and deletion_delay_secs and timestamp:
            main_embed.description = (
                f"**Mock roles for {ctx.author.mention} ({len(role_ids)}):**\n\n"
                + "\n".join(
                    f"• @everyone (No Roles)"
                    if role_id == ctx.guild.id
                    else f"• <@&{role_id}>"
                    for role_id in role_ids
                )
                + f"\n\nThese mock roles will expire **<t:{int(timestamp+deletion_delay_secs)}:R>**."
            )

        await self.send_paginated_response_embeds(ctx, main_embed)

    @commands.has_guild_permissions(manage_roles=True)
    @tcm.command(name="clearmockroles")
    async def tcm_clearmockroles(
        self,
        ctx: commands.Context[BotT],
    ):
        """Clear any mock roles that were previously set."""
        assert ctx.guild and isinstance(ctx.author, discord.Member)
        if (
            ctx.guild.id in self.guild_mock_roles
            and ctx.author.id in self.guild_mock_roles[ctx.guild.id]
        ):
            role_ids, task, deletion_delay_secs, timestamp = self.guild_mock_roles[
                ctx.guild.id
            ][ctx.author.id]
            if not task.done():
                task.cancel()
            del self.guild_mock_roles[ctx.guild.id][ctx.author.id]

    @commands.guild_only()
    @tcm.command(
        name="view",
        extras=dict(response_deletion_with_reaction=True, invoke_on_message_edit=True),
    )
    async def tcm_view(
        self,
        ctx: commands.Context[BotT],
        *names: str,
    ):
        """View the settings of all configured text commands or those specified by full name.

        __**Parameters:**__

        **`[names (Text)...]`**
        > The full command name or a sequence of full command names whose settings should be shown.
        """
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        text_command_names = names

        everyone_role_id = ctx.guild.id
        all_channels_id = ctx.guild.id - 1

        main_embed_dict: EmbedDict = {}
        main_embed_dict["title"] = "Text Command State & Permission Settings"
        main_embed_dict["color"] = int(self.theme_color)

        if not await self.guild_text_command_states_exists(ctx.guild.id):
            main_embed_dict["description"] = (
                "No text command data found "
                "for this guild. Run the `tcm set` command to add configuration data."
            )
            return await self.send_paginated_response_embeds(
                ctx, discord.Embed.from_dict(main_embed_dict)
            )

        main_embed_dict["fields"] = []

        main_embed_dict["footer"] = {
            "text": (
                "\u200b\n\n✅ On\n"
                "❌ Off\n"
                "🔁 Permissions synced with parent(s)\n"
                "🔀 Permissions unsynced with/overriding parent(s)"
            )
        }

        guild_text_command_state_map = await self.fetch_guild_text_command_states(
            ctx.guild.id
        )

        if isinstance(text_command_names, str):
            text_command_names = (text_command_names,)

        if text_command_names:
            filtered_states = sorted(
                (
                    guild_text_command_state_map[text_command_name]
                    for text_command_name in set(text_command_names)
                    if text_command_name in guild_text_command_state_map
                ),
                key=lambda state: state["qualified_name"],
            )
        else:
            filtered_states = sorted(
                (
                    state
                    for k, state in guild_text_command_state_map.items()
                    if re.match(UUID_PATTERN, k)
                ),
                key=lambda state: state["qualified_name"],
            )

        for text_command_state in filtered_states:
            text_command_state_hierarchy = await self.get_text_command_state_hierarchy(
                ctx.guild.id, text_command_state
            )
            main_embed_field: EmbedField = {"name": "", "value": ""}
            roles_embed_field: EmbedField = {"name": "", "value": ""}
            channels_embed_field: EmbedField = {"name": "", "value": ""}

            if text_command_state["text_command_uuid"] == ZERO_UUID:
                roles_embed_field["name"] = "Roles"
                channels_embed_field["name"] = "Channels"
            else:
                roles_embed_field[
                    "name"
                ] = f"{'🔀' if 'roles' in text_command_state else '🔁'} Roles"
                channels_embed_field[
                    "name"
                ] = f"{'🔀' if 'channels' in text_command_state else '🔁'} Channels"

            roles_embed_field["inline"] = True
            channels_embed_field["inline"] = True

            enabled_emoji = "✅" if text_command_state["enabled"] & 0b01 else "❌"
            subcommands_enabled_emoji = (
                "✅" if text_command_state["enabled"] & 0b10 else "❌"
            )

            enabled_by_parent = True

            if text_command_state["text_command_uuid"] == ZERO_UUID:
                main_embed_field["name"] = "\u200b\nGlobal Settings"
                main_embed_field["value"] = "..."
            else:
                enabled_by_parent = not any(
                    not text_command_state2["enabled"] & 0b10
                    for text_command_state2 in text_command_state_hierarchy[1:]
                )

                main_embed_field["name"] = (
                    "\u200b\n"
                    f"`{enabled_emoji}` `{subcommands_enabled_emoji}` "
                    f"`{text_command_state['qualified_name']}`"
                )

                if await ctx.bot.is_owner(ctx.author):
                    main_embed_field[
                        "value"
                    ] = f"UUID: `{text_command_state['text_command_uuid']}`\n"

                main_embed_field["value"] += (
                    "Command: "
                    + ("  On" if text_command_state["enabled"] & 0b01 else "Off")
                    + " | Subcommands: "
                    + ("On" if text_command_state["enabled"] & 0b10 else "Off")
                )

                if not enabled_by_parent:
                    main_embed_field["name"] = f'~~ {main_embed_field["name"]} ~~'
                    main_embed_field["value"] = "\n".join(
                        f"~~ {ln} ~~" for ln in main_embed_field["value"].split("\n")
                    )
                    main_embed_field["value"] += "\nDisabled by parent command"

            condensed_role_overrides = text_command_state.get("roles", {})

            for i, text_command_state2 in enumerate(text_command_state_hierarchy):
                if (
                    "roles" in text_command_state2
                    and everyone_role_id in text_command_state2["roles"]
                ):  # guild ID is @everyone role
                    for j in range(i, 0, -1):
                        condensed_role_overrides |= text_command_state_hierarchy[j].get(
                            "roles", {}
                        )  # update with parent command overrides
                    break

            condensed_channel_overrides = text_command_state.get("channels", {})

            for i, text_command_state2 in enumerate(text_command_state_hierarchy):
                if (
                    "channels" in text_command_state2
                    and all_channels_id in text_command_state2["channels"]
                ):  # guild ID - 1 means all channels
                    for j in range(i, 0, -1):
                        condensed_channel_overrides |= text_command_state_hierarchy[
                            j
                        ].get(
                            "channels", {}
                        )  # update with parent command overrides
                    break

            role_sort_lambda = lambda item: role.position if (role := ctx.guild.get_role(item[0])) else -1  # type: ignore
            channel_sort_lambda = lambda item: channel.position if (channel := ctx.guild.get_channel(item[0])) else -1  # type: ignore

            roles_embed_field["value"] = "\n".join(
                f"`{'✅' if override_bool else '❌'}`  <@&{role_id}>"
                if role_id != everyone_role_id
                else f"`{'✅' if override_bool else '❌'}`  @everyone"
                for role_id, override_bool in sorted(
                    condensed_role_overrides.items(), key=role_sort_lambda, reverse=True
                )
            )
            channels_embed_field["value"] = "\n".join(
                f"`{'✅' if override_bool else '❌'}`  <#{channel_id}> "
                if channel_id != all_channels_id
                else f"`{'✅' if override_bool else '❌'}`  **All Channels**"
                for channel_id, override_bool in sorted(
                    condensed_channel_overrides.items(),
                    key=channel_sort_lambda,
                    reverse=True,
                )
            )

            if not enabled_by_parent:
                roles_embed_field["name"] = f'~~ {roles_embed_field["name"]} ~~'
                roles_embed_field["value"] = "\n".join(
                    f"~~ {ln} ~~" for ln in roles_embed_field["value"].split("\n")
                )

                channels_embed_field["name"] = f'~~ {channels_embed_field["name"]} ~~'
                channels_embed_field["value"] = "\n".join(
                    f"~~ {ln} ~~" for ln in channels_embed_field["value"].split("\n")
                )

            main_embed_dict["fields"].extend(
                (main_embed_field, roles_embed_field, channels_embed_field)
            )

        main_embed_dict[
            "description"
        ] = f"**{len(filtered_states)}** text command configurations found.\n\n"
        "\n\u200b"

        main_embed_dicts = snakecore.utils.embeds.split_embed_dict(main_embed_dict)  # type: ignore
        final_embeds: list[discord.Embed] = []

        for embed_dict in main_embed_dicts:
            embed_dict["title"] = main_embed_dict["title"]
            embed_dict["description"] = main_embed_dict["description"]

            final_embed_dicts = (
                snakecore.utils.embeds.split_embed_dict(embed_dict)
                if snakecore.utils.embeds.check_embed_dict_char_count(embed_dict)
                > snakecore.utils.embeds.EMBED_TOTAL_CHAR_LIMIT
                else [embed_dict]
            )
            final_embeds.extend(
                discord.Embed.from_dict(final_embed_dict)
                for final_embed_dict in final_embed_dicts
            )

        await self.send_paginated_response_embeds(ctx, *final_embeds)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=True)
    @tcm.command(
        name="set",
        usage="<name/( name ... )> <override: Role/Channel on|off>... "
        "[enabled: yes|no] [subcommands_enabled: yes|no]",
    )
    @flagconverter_kwargs()
    async def tcm_set(
        self,
        ctx: commands.Context[BotT],
        name: Parens[str, ...] | str,
        *,
        override: ChannelOrRoleOverrides,
        enabled: bool | None = None,
        subcommands_enabled: bool | None = None,
    ):
        """Add or replace settings for the specified text commands.

        __**Parameters:**__

        **`<name/( name ... )>`**
        > The full command name or a parenthesized sequence of full command names to alter the settings of.

        **`<override: Role/Channel on|off>...`**
        > A flag for a role or channel to override, followed by 'on' or 'off' to allow or deny command execution for the specified command(s).
        > 'everyone' can be speficied to refer to the default @everyone role (hidden guild ID role that applies to every server member).
        > If specified, any previous overrides are overwritten.
        > Can be specified multiple times.

        **`[enabled: on|off]`**
        > A flag for enabling or disabling the execution of the specified command(s).

        **`[subcommands_enabled: on|off]`**
        > A flag for enabling or recursively disabling the execution of any subcommands of the specified command(s).

        __**Examples:**__

        tcm set ( "kick" "ban" "purge" )
        override: "everyone" off
        override: @Moderator on

        tcm set "economy" override: "everyone" off override: @Level 5 on
        tcm set "catbomb" enabled: no
        tcm set "warnings" subcommands_enabled: no
        """
        assert ctx.guild

        text_command_names = name

        channel_or_role_overrides = override or []

        if (
            not text_command_names
            or text_command_names
            and not (
                channel_or_role_overrides
                or isinstance(enabled, bool)
                or isinstance(subcommands_enabled, bool)
            )
        ):
            raise commands.CommandInvokeError(
                commands.CommandError("No valid inputs given.")
            )

        everyone_role_id = ctx.guild.id
        all_channels_id = ctx.guild.id - 1

        role_overrides = {}
        channel_overrides = {}
        text_command_states: list[GuildTextCommandState] = []

        if isinstance(text_command_names, str):
            text_command_names = (text_command_names,)

        for target, value in channel_or_role_overrides:
            if isinstance(target, str):
                if target.casefold() == "all channels":
                    channel_overrides[all_channels_id] = value

                elif target.casefold() in ("everyone", "@everyone"):
                    role_overrides[everyone_role_id] = value

            elif isinstance(target, discord.abc.GuildChannel):
                channel_overrides[target.id] = value

            elif isinstance(target, discord.Role):
                role_overrides[target.id] = value

        if not (
            guild_text_command_states_exists := await self.guild_text_command_states_exists(
                ctx.guild.id
            )
        ):
            text_command_states.append(
                self.create_guild_root_text_command_state(ctx.guild.id)
            )

        for text_command_name in text_command_names:
            text_command_obj = ctx.bot.get_command(text_command_name)
            if text_command_obj is None:
                if (
                    text_command_name
                    and guild_text_command_states_exists
                    and text_command_name
                    in (
                        text_command_state_map := await self.fetch_guild_text_command_states(
                            ctx.guild.id
                        )
                    )
                ):
                    text_command_state = text_command_state_map[
                        text_command_name
                    ].copy()

                    text_command_state[
                        "enabled"
                    ] = (  # only update if changes were specified
                        subcommands_enabled
                        if subcommands_enabled is not None
                        else bool(text_command_state["enabled"] & 0b10)
                    ) << 1 | (
                        enabled
                        if enabled is not None
                        else bool(text_command_state["enabled"] & 0b01)
                    )

                    if channel_overrides:
                        text_command_state["channels"] = channel_overrides.copy()

                    if role_overrides:
                        text_command_state["roles"] = role_overrides.copy()
                else:
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f'No data could be found for a text command named "{text_command_name}"'
                        )
                    )
            else:
                if text_command_obj.cog is self and not (
                    enabled is None and subcommands_enabled is None
                ):
                    raise commands.CommandInvokeError(
                        commands.CommandError(
                            f"Cannot enable/disable `tcm` command or any of its subcommands."
                        )
                    )
                if guild_text_command_states_exists:
                    text_command_state_map = await self.fetch_guild_text_command_states(
                        ctx.guild.id
                    )
                else:
                    text_command_state_map = {}

                for i, current_text_command in enumerate(
                    (text_command_obj, *text_command_obj.parents)
                ):
                    text_command_uuid = current_text_command.extras.get("uuid")
                    if text_command_uuid is not None:
                        try:
                            if isinstance(text_command_uuid, str):
                                text_command_uuid = str(UUID(text_command_uuid))
                            elif isinstance(text_command_uuid, UUID):
                                text_command_uuid = str(text_command_uuid)
                        except (TypeError, ValueError):
                            text_command_uuid = None

                    if text_command_uuid is None:
                        qualname_sha1 = int(
                            sha1(
                                current_text_command.qualified_name.encode("utf-8"),
                                usedforsecurity=False,
                            ).hexdigest(),
                            base=16,
                        )
                        text_command_uuid = str(
                            UUID(
                                int=qualname_sha1
                                >> max(qualname_sha1.bit_length() - 128, 0)
                            )
                        )  # truncate to <= 128 bits
                    else:
                        text_command_uuid = str(text_command_uuid)

                    text_command_state = text_command_state_map.get(
                        text_command_uuid, {}
                    )
                    text_command_state[
                        "qualified_name"
                    ] = current_text_command.qualified_name

                    text_command_state["text_command_uuid"] = text_command_uuid

                    text_command_state["parent_text_command_uuid"] = ZERO_UUID
                    if isinstance(current_text_command.parent, commands.Command):
                        parent_text_command_uuid = (
                            current_text_command.parent.extras.get("uuid")
                        )
                        if parent_text_command_uuid is not None:
                            try:
                                if isinstance(parent_text_command_uuid, str):
                                    parent_text_command_uuid = str(
                                        UUID(parent_text_command_uuid)
                                    )
                                elif isinstance(text_command_uuid, UUID):
                                    parent_text_command_uuid = str(
                                        parent_text_command_uuid
                                    )
                            except (TypeError, ValueError):
                                parent_text_command_uuid = None

                        if parent_text_command_uuid is None:
                            qualname_sha1 = int(
                                sha1(
                                    current_text_command.parent.qualified_name.encode(
                                        "utf-8"
                                    ),
                                    usedforsecurity=False,
                                ).hexdigest(),
                                base=16,
                            )
                            parent_text_command_uuid = str(
                                UUID(
                                    int=qualname_sha1
                                    >> max(qualname_sha1.bit_length() - 128, 0)
                                )
                            )  # truncate to <= 128 bits

                        text_command_state[
                            "parent_text_command_uuid"
                        ] = parent_text_command_uuid

                    if i == 0:
                        # only update if changes were specified, initialize to enabled if no previous settings exist
                        text_command_state["enabled"] = (
                            subcommands_enabled
                            if subcommands_enabled is not None
                            else bool(text_command_state.get("enabled", 0b10) & 0b10)
                        ) << 1 | (
                            enabled
                            if enabled is not None
                            else bool(text_command_state.get("enabled", 0b01) & 0b01)
                        )

                        if channel_overrides:
                            text_command_state["channels"] = channel_overrides.copy()

                        if role_overrides:
                            text_command_state["roles"] = role_overrides.copy()
                    else:
                        if "enabled" not in text_command_state:
                            text_command_state["enabled"] = 0b11

                    text_command_states.append(text_command_state)  # type: ignore

        await self.update_guild_text_command_states(ctx.guild.id, *text_command_states)

    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.guild, wait=True)
    @tcm.command(name="setglobal", usage="<override: Role/Channel on|off>...")
    @flagconverter_kwargs()
    async def tcm_setglobal(
        self,
        ctx: commands.Context[BotT],
        *,
        override: ChannelOrRoleOverrides,
    ):
        """Add or replace global settings that may be used or overridden by text commands.
        This can be used to globally enable/disable all text commands for specific roles or channels.

        __**Parameters:**__

        **`<override: Role/Channel on|off>...`**
        > A flag for a role or channel to override, followed by 'on' or 'off' to allow or deny command execution.
        > 'everyone' can be speficied to refer to the default @everyone role (hidden guild ID role that applies to every server member).
        > 'all channels' can be speficied to refer all channels in a guild/server.
        > If specified, any preexisting overrides are overwritten.
        > Can be specified multiple times.

        __**Examples:**__

        tcm setglobal override: "All Channels" off override: #bot-playground on
        """
        assert ctx.guild

        channel_or_role_overrides = override

        if not channel_or_role_overrides:
            raise commands.CommandInvokeError(
                commands.CommandError("No valid inputs given.")
            )

        everyone_role_id = ctx.guild.id
        all_channels_id = ctx.guild.id - 1

        role_overrides = {}
        channel_overrides = {}

        for target, value in channel_or_role_overrides:
            if isinstance(target, str):
                if target.casefold() == "all channels":
                    channel_overrides[all_channels_id] = value

                elif target.casefold() in ("everyone", "@everyone"):
                    role_overrides[everyone_role_id] = value

            elif isinstance(target, discord.abc.GuildChannel):
                channel_overrides[target.id] = value

            elif isinstance(target, discord.Role):
                role_overrides[target.id] = value

        if await self.guild_text_command_states_exists(ctx.guild.id) and ZERO_UUID in (
            text_command_state_map := await self.fetch_guild_text_command_states(
                ctx.guild.id
            )
        ):
            text_command_state = text_command_state_map[ZERO_UUID].copy()
        else:
            text_command_state = self.create_guild_root_text_command_state(ctx.guild.id)
        if channel_overrides:
            text_command_state["channels"] = channel_overrides.copy()

        if role_overrides:
            text_command_state["roles"] = role_overrides.copy()

        await self.update_guild_text_command_states(ctx.guild.id, text_command_state)  # type: ignore

    @commands.guild_only()
    @tcm.command(name="clear", require_var_positional=True)
    async def tcm_clear(
        self,
        ctx: commands.Context[BotT],
        *names: str,
    ):
        """Clear the settings configured for the specified text commands.

        __**Parameters:**__

        **`<names...>`**
        > The full command name or a sequence of full command names whose settings should be cleared.
        """
        assert ctx.guild

        text_command_names = names

        if isinstance(text_command_names, str):
            text_command_names = (text_command_names,)

        for text_command_name in text_command_names:
            if await self.guild_text_command_states_exists(
                ctx.guild.id
            ) and text_command_name in (
                text_command_state_map := await self.fetch_guild_text_command_states(
                    ctx.guild.id
                )
            ):
                await self.delete_guild_text_command_states(
                    ctx.guild.id, text_command_state_map[text_command_name].copy()
                )
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        f'No data could be found for a text command named "{text_command_name}"'
                    )
                )

    @commands.guild_only()
    @tcm.command(name="clearall")
    async def tcm_clearall(
        self,
        ctx: commands.Context[BotT],
    ):
        """Clear the settings of all configured commands, including any global settings."""
        assert ctx.guild
        await self.delete_all_guild_text_command_states(ctx.guild.id)

    @commands.guild_only()
    @tcm.command(
        name="clearoverrides",
        usage="<name/( name ... )> [roles: yes|no] [channels: yes|no]",
    )
    @flagconverter_kwargs()
    async def tcm_clearoverrides(
        self,
        ctx: commands.Context[BotT],
        name: Parens[str, ...] | str,
        *,
        roles: bool | None = None,
        channels: bool | None = None,
    ):
        """Clear any channel and/or role overrides for the specified text commands.

        __**Parameters:**__

        **`<name/( name ... )>`**
        > The full command name or a parenthesized sequence of full command names to clear overrides of.

        **`[roles: yes|no]...`**
        > A flag for choosing whether role overrides should be cleared.
        > Defaults to 'no'.

        **`[channels: yes|no]...`**
        > A flag for choosing whether channel overrides should be cleared.
        > Default to 'no'.

        *If 'roles:' nor 'channels:' are specified, both will default to 'yes'.*

        __**Examples:**__

        tcm clearoverrides ( "economy" "8ball" ) roles: yes
        """
        assert ctx.guild

        text_command_names = name

        if isinstance(text_command_names, str):
            text_command_names = (text_command_names,)

        for text_command_name in text_command_names:
            if await self.guild_text_command_states_exists(
                ctx.guild.id
            ) and text_command_name in (
                text_command_state_map := await self.fetch_guild_text_command_states(
                    ctx.guild.id
                )
            ):
                text_command_state = text_command_state_map[text_command_name].copy()

                if channels is None and roles is None:
                    if "roles" in text_command_state:
                        del text_command_state["roles"]

                    if "channels" in text_command_state:
                        del text_command_state["channels"]
                else:
                    if "roles" in text_command_state and roles is True:
                        del text_command_state["roles"]

                    if "channels" in text_command_state and channels is True:
                        del text_command_state["channels"]

                await self.update_guild_text_command_states(
                    ctx.guild.id, text_command_state
                )
            else:
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        f'No data could be found for a text command named "{text_command_name}"'
                    )
                )

    @commands.guild_only()
    @tcm.command(
        name="clearglobaloverrides",
        usage="[[roles: on|off] [channels: on|off]]",
    )
    @flagconverter_kwargs()
    async def tcm_clearglobaloverrides(
        self,
        ctx: commands.Context[BotT],
        *,
        roles: bool | None = None,
        channels: bool | None = None,
    ):
        """Clear any global channel and/or role overrides that may be used or overridden by text commands.

        __**Parameters:**__

        **`[roles: yes|no]...`**
        > A flag for choosing whether role overrides should be cleared.
        > Defaults to 'no'.

        **`[channels: yes|no]...`**
        > A flag for choosing whether channel overrides should be cleared.
        > Default to 'no'.

        *If 'roles:' nor 'channels:' are specified, both will default to 'yes'.*

        __**Examples:**__

        tcm clearglobalroverrides channels: yes
        """
        assert ctx.guild

        everyone_role_id = ctx.guild.id
        all_channels_id = ctx.guild.id - 1

        if await self.guild_text_command_states_exists(ctx.guild.id) and ZERO_UUID in (
            text_command_state_map := await self.fetch_guild_text_command_states(
                ctx.guild.id
            )
        ):
            text_command_state = text_command_state_map[ZERO_UUID].copy()

            if channels is None and roles is None:
                if "roles" in text_command_state:
                    text_command_state["roles"] = {everyone_role_id: True}

                if "channels" in text_command_state:
                    text_command_state["channels"] = {all_channels_id: True}
            else:
                if "roles" in text_command_state and roles is True:
                    text_command_state["roles"] = {everyone_role_id: True}

                if "channels" in text_command_state and channels is True:
                    text_command_state["channels"] = {all_channels_id: True}

            await self.update_guild_text_command_states(
                ctx.guild.id, text_command_state
            )
        else:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    f"No data could be found for root pseudo-command of this guild/server."
                )
            )
