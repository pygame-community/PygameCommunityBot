"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file should define the `discord.ext.commands.Bot` subclass to use for the project. 
"""

import asyncio
from collections import OrderedDict
import datetime
import logging
import time
from types import MappingProxyType
from typing import Any, Mapping, Optional, Type, Union

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
import sqlalchemy.engine
import sqlalchemy.exc
from sqlalchemy import text
import discord
from discord.ext import commands, tasks
from discord.ext.commands.view import StringView
import snakecore
from snakecore.constants import UNSET
from snakecore.utils.pagination import EmbedPaginator

from . import constants, utils
from ._types import DatabaseDict, ExtensionData

_logger = logging.getLogger(__name__)


class PygameCommunityBot(snakecore.commands.Bot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._config: dict[str, Any] = kwargs.get("config", {})
        self.loading_emoji = "🔄"
        self._loading_reaction_queue: asyncio.Queue = UNSET

        self._recent_response_error_messages: dict[int, discord.Message] = {}

        self._cached_response_messages: OrderedDict[
            int, discord.Message
        ] = OrderedDict()

        self._cached_response_messages_maxsize = 1000

        self._cached_embed_paginators: dict[
            int, tuple[EmbedPaginator, asyncio.Task[None]]
        ] = {}

        self._cached_embed_paginators_maxsize = 1000

        self._main_database: DatabaseDict = {}  # type: ignore
        self._databases: dict[str, DatabaseDict] = {}
        self._extension_data_storage_is_init = False

        self.before_invoke(self.bot_before_invoke)
        self.after_invoke(self.bot_after_invoke)

    @property
    def config(self) -> Mapping[str, Any]:
        """Optional bot configuration data provided during bot creation."""
        return MappingProxyType(self._config)

    @property
    def cached_response_messages(self):
        """A mapping of invocation message IDs to successful response messages."""
        return self._cached_response_messages

    @property
    def cached_response_messages_maxsize(self):
        return self._cached_response_messages_maxsize

    @property
    def cached_embed_paginators(self):
        """A mapping of successful response message IDs to a list containing an
        EmbedPaginator object along with an asyncio Task object to run it.
        """
        return self._cached_embed_paginators

    @property
    def cached_embed_paginators_maxsize(self):
        return self._cached_embed_paginators_maxsize

    async def is_owner(self, user: discord.User | discord.Member, /) -> bool:
        return (
            isinstance(user, discord.Member)
            and (owner_role_ids := self._config.get("owner_role_ids", ()))
            and any(role.id in owner_role_ids for role in user.roles)
        ) or await super().is_owner(user)

    async def process_commands(
        self, message: discord.Message, /, ctx: commands.Context | None = None
    ) -> None:
        if message.author.bot:
            return

        if ctx is None:
            ctx = await self.get_context(message)

        invoke_task = asyncio.create_task(self.invoke(ctx))
        try:
            await asyncio.wait_for(asyncio.shield(invoke_task), timeout=3)
            # check if command invocation is taking time
        except asyncio.TimeoutError:
            await self._loading_reaction_queue.put(
                ctx.message.add_reaction(self.loading_emoji)
            )
            if not invoke_task.done():
                await invoke_task
        except asyncio.CancelledError:
            if not invoke_task.done():
                invoke_task.cancel()
        else:
            if not invoke_task.done():
                await invoke_task

    @staticmethod
    def _find_invoked_subcommand(ctx: commands.Context):
        if not ctx.valid:
            return None

        if ctx.invoked_subcommand:
            return ctx.invoked_subcommand

        command = ctx.command
        if (
            isinstance(command, commands.Group) and command.invoke_without_command
        ):  # try to find a subcommand being invoked
            view = StringView(ctx.view.buffer)
            view.index = ctx.view.index
            view.end = ctx.view.end
            view.previous = ctx.view.previous

            while isinstance(command, commands.Group):
                view.skip_ws()
                trigger = view.get_word()

                if trigger and trigger in command.all_commands:
                    command = command.all_commands[trigger]
                else:
                    break

            return None if command is ctx.command else command
        else:
            return None

    async def on_message_edit(self, old: discord.Message, new: discord.Message) -> None:
        if new.author.bot:
            return

        if (time.time() - (new.edited_at or new.created_at).timestamp()) < 120:
            ctx = await self.get_context(new)

            if not (ctx.command and ctx.valid):
                return

            command = self._find_invoked_subcommand(ctx) or ctx.command

            if (
                (modifier_flag := command.extras.get("invoke_on_message_edit"))
                or modifier_flag is not False
                and command.cog is not None
                and getattr(command.cog, "invoke_on_message_edit", False)
            ):
                await self.process_commands(new, ctx=ctx)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if response_error_message := self._recent_response_error_messages.get(
            payload.message_id
        ):
            try:
                await response_error_message.delete()
            except discord.NotFound:
                pass

    async def bot_before_invoke(self, ctx: commands.Context):
        if (
            (command := ctx.invoked_subcommand or ctx.command) is not None
            and (
                (
                    modifier_flag := command.extras.get(
                        "inject_reference_as_first_argument"
                    )
                )
                or modifier_flag is not False
                and command.cog is not None
                and getattr(command.cog, "inject_reference_as_first_argument", False)
            )
            and (reference := ctx.message.reference)
            and reference.message_id
            and not isinstance(reference.resolved, discord.DeletedReferencedMessage)
        ):
            try:
                message = reference.resolved or await ctx.fetch_message(
                    reference.message_id
                )
            except discord.NotFound:
                pass
            else:
                if ctx.args and isinstance(
                    ctx.args[0], commands.Cog
                ):  # command was defined inside cog
                    if len(ctx.args) > 2 and ctx.args[2] is None:
                        ctx.args[2] = message
                    else:
                        ctx.args.insert(2, message)
                else:
                    if len(ctx.args) > 1 and ctx.args[1] is None:
                        ctx.args[1] = message
                    else:
                        ctx.args.insert(1, message)

    async def bot_after_invoke(self, ctx: commands.Context):
        assert ctx.command
        if (
            any(
                reaction.emoji == self.loading_emoji
                for reaction in ctx.message.reactions
            )
            and self.user is not None
        ):
            await self._loading_reaction_queue.put(
                ctx.message.remove_reaction(self.loading_emoji, self.user)
            )

        resp_msg_cache_overflow = (
            len(self._cached_response_messages) - self._cached_response_messages_maxsize
        )

        for _ in range(min(max(resp_msg_cache_overflow, 0), 100)):
            _, response_message = self._cached_response_messages.popitem(last=False)
            paginator_list = self._cached_embed_paginators.get(response_message.id)
            if paginator_list is not None and paginator_list[0].is_running():  # type: ignore
                paginator_list[1].cancel()  # type: ignore

        command = ctx.invoked_subcommand or ctx.command

        if not ctx.command_failed:
            if (
                (flag_value := command.extras.get("delete_invocation", False))
                or flag_value is not False
                and command.cog is not None
                and getattr(command.cog, "delete_invocation", False)
            ):
                try:
                    await ctx.message.delete()
                except discord.NotFound:
                    pass

        if (
            (modifier_flag := command.extras.get("response_deletion_with_reaction"))
            or modifier_flag is not False
            and command.cog is not None
            and getattr(command.cog, "response_deletion_with_reaction", False)
        ) and (
            response_message := self.cached_response_messages.get(ctx.message.id)
        ) is not None:

            snakecore.utils.hold_task(
                asyncio.create_task(
                    utils.message_delete_reaction_listener(
                        self,
                        response_message,
                        ctx.author,
                        emoji="🗑",
                        timeout=60,
                    )
                )
            )

    @tasks.loop(reconnect=False)
    async def handle_loading_reactions(self):
        while True:
            reaction_coro = await self._loading_reaction_queue.get()
            try:
                await reaction_coro
            except discord.HTTPException:
                pass

            await asyncio.sleep(0.1)

    async def get_context(
        self,
        origin: discord.Message | discord.Interaction,
        /,
        *,
        cls: Type[commands.Context["PygameCommunityBot"]] = discord.utils.MISSING,
    ) -> commands.Context["PygameCommunityBot"]:
        new_ctx = await super().get_context(origin, cls=cls)
        setattr(new_ctx, "created_at", datetime.datetime.now(datetime.timezone.utc))
        return new_ctx

    async def _create_database_connections(self) -> None:
        self._databases = {  # type: ignore
            db_dict["name"]: db_dict
            for db_dict in await utils.load_databases(
                self._config["databases"], raise_exceptions=False, logger=_logger
            )
            if isinstance(db_dict["name"], str)
        }

        failures = len(self._config["databases"]) - len(self._databases.keys())

        if failures == len(self._config["databases"]):
            _logger.warning(
                f"Could not establish a connection to any supported database"
            )

        if self._databases:
            self._main_database = next(iter(self._databases.values()))

    async def _close_database_connections(self) -> None:
        await utils.unload_databases(
            self._databases.values(), raise_exceptions=False, logger=_logger
        )

    async def setup_hook(self) -> None:
        self._loading_reaction_queue = asyncio.Queue()
        if "databases" in self._config:
            await self._create_database_connections()
            await self._init_extension_data_storage()

        for ext_dict in self._config["extensions"]:
            _logger.info(
                f"Attempting to load extension "
                f"'{ext_dict.get('package', '')}{ext_dict['name']}'"
            )
            try:
                await self.load_extension_with_config(
                    ext_dict["name"],
                    package=ext_dict.get("package"),
                    config=ext_dict.get("config"),
                )
            except commands.ExtensionAlreadyLoaded:
                _logger.info(
                    f"Extension "
                    f"'{ext_dict.get('package', '')}{ext_dict['name']}' was already "
                    "loaded, skipping..."
                )
                continue

            except (TypeError, commands.ExtensionError) as exc:
                _logger.error(
                    f"Failed to load extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch",
                    exc_info=exc,
                )
            else:
                _logger.info(
                    f"Successfully loaded extension "
                    f"'{ext_dict.get('package', '')}{ext_dict['name']}' at launch"
                )

    async def teardown_hook(self) -> None:
        self.handle_loading_reactions.cancel()
        if self._databases:
            await self._close_database_connections()

    async def close(self) -> None:
        if not self.is_closing():
            await asyncio.gather(
                *self.dispatch("close"), return_exceptions=True
            )  # wait for all 'close' events to finish being processed.
            return await super().close()

    async def on_ready(self):
        assert self.user is not None
        self.loading_emoji = (
            self.get_emoji(constants.PGC_LOADING_EMOJI_ID) or self.loading_emoji
        )
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        handle_loading_reactions = self.handle_loading_reactions
        if not handle_loading_reactions.is_running():
            handle_loading_reactions.start()

    async def on_command_error(
        self,
        context: commands.Context["PygameCommunityBot"],
        exception: commands.CommandError,
    ) -> None:

        send_error_message = True

        if self.extra_events.get("on_command_error", None):
            send_error_message = False

        if not (command := context.command):
            return
        elif command.has_error_handler():
            send_error_message = False

        cog = context.cog
        if cog and cog.has_error_handler():
            send_error_message = False

        title = exception.__class__.__name__
        description = exception.args[0] if isinstance(exception.args[0], str) else ""
        if len(description) > 3800:
            description = description[:3801] + "..."
        footer_text = exception.__class__.__name__

        log_exception = False
        has_cause = False

        color = 0x170401

        if isinstance(
            exception, commands.CommandNotFound
        ):  # prevent potentially unintended command invocations
            return

        elif isinstance(exception, commands.BadArgument):
            if (
                isinstance(exception, commands.BadFlagArgument)
                and exception.original.args
            ):
                description = (
                    f"\n> Flag '{exception.flag.name}': {exception.original.args[0]}"
                )
            title = "Invalid argument(s)"
            description = (
                (
                    f"Parameter '{context.current_parameter.name}': "
                    if context.current_parameter
                    else ""
                )
                + f"{description}\n\nFor help on bot commands, call `help <command>`"
                " with a correct prefix."
            )

        elif isinstance(exception, commands.UserInputError):
            title = "Invalid command input(s)"
            description = (
                f"{description}\n\nFor help on bot commands, call `help <command>` with "
                "a correct prefix."
            )

        elif isinstance(exception, commands.DisabledCommand):
            title = f"Cannot execute command ({exception.args[0]})"
            description = (
                f"The specified command has been globally disabled. "
                "Please stand by as the bot wizards search for "
                "workarounds and solutions to this issue."
            )

        elif isinstance(exception, commands.CheckFailure):
            title = "Command invocation check(s) failed"
            if isinstance(
                exception,
                (
                    commands.MissingPermissions,
                    commands.MissingRole,
                    commands.MissingAnyRole,
                    commands.BotMissingPermissions,
                    commands.BotMissingRole,
                    commands.BotMissingAnyRole,
                ),
            ):
                title = "You're missing some "

                if isinstance(
                    exception,
                    (
                        commands.BotMissingPermissions,
                        commands.BotMissingRole,
                        commands.BotMissingAnyRole,
                    ),
                ):
                    title = "I'm missing some "

                if isinstance(
                    exception,
                    (commands.MissingPermissions, commands.BotMissingPermissions),
                ):
                    title += "permissions"
                else:
                    title += "roles"

        elif isinstance(
            exception, (commands.CommandInvokeError, commands.ConversionError)
        ):
            if isinstance(exception, commands.CommandInvokeError) and (
                not exception.__cause__
                or isinstance(
                    exception.__cause__, (discord.HTTPException, discord.RateLimited)
                )
            ):
                title = f"Command `{context.invoked_with}` reported an error"
                description = exception.args[0] if exception.args else ""
                description = description.replace(
                    f"Command raised an exception: {exception.original.__class__.__name__}: ",
                    "",
                )
                color = constants.KNOWN_COMMAND_ERROR_COLOR
                footer_text = exception.__class__.__name__

            elif exception.__cause__:
                log_exception = True
                has_cause = True
                title = "Unknown error"
                description = (
                    "An unknown error occured while running the "
                    f"{context.command.qualified_name} command!\n"
                    "This is most likely a bug in this bot application, "
                    "please report this to the bot team.\n\n"
                    f"```\n{exception.__cause__.args[0] if exception.__cause__.args else ''}```"
                )
                color = constants.UNKNOWN_COMMAND_ERROR_COLOR
                footer_text = exception.__cause__.__class__.__name__

        footer_text += "\n(React with 🗑 to delete this error message in the next 30s)"

        if send_error_message:
            target_message = self._recent_response_error_messages.get(
                context.message.id
            )
            try:
                if target_message is not None:
                    await target_message.edit(
                        embed=discord.Embed(
                            title=title, description=description, color=color
                        ).set_footer(text=footer_text),
                    )
                else:
                    target_message = await context.send(
                        embed=discord.Embed(
                            title=title, description=description, color=color
                        ).set_footer(text=footer_text)
                    )
            except discord.NotFound:
                # response message was deleted, send a new message
                target_message = await context.send(
                    embed=discord.Embed(
                        title=title, description=description, color=color
                    ).set_footer(text=footer_text)
                )

            self._recent_response_error_messages[
                context.message.id
            ] = target_message  # store updated message object

            snakecore.utils.hold_task(
                asyncio.create_task(
                    utils.message_delete_reaction_listener(
                        self,
                        target_message,
                        context.author,
                        emoji="🗑",
                        timeout=30,
                    )
                )
            )

        main_exception = exception
        if log_exception:
            if has_cause:
                main_exception = exception.__cause__

            _logger.error(
                "An unhandled exception occured in command '%s'",
                context.command.qualified_name,
                exc_info=main_exception,
            )

    async def on_command_completion(self, ctx: commands.Context):
        if ctx.message.id in self._recent_response_error_messages:
            try:
                await self._recent_response_error_messages[ctx.message.id].delete()
            except discord.NotFound:
                pass
            finally:
                del self._recent_response_error_messages[ctx.message.id]

    def get_database(self) -> AsyncEngine | None:
        """Get an `sqlachemy.ext.asyncio.AsyncEngine` object for the main
        database of this bot.

        Returns
        -------
        AsyncEngine | None
            The engine, or None if nothing was loaded/configured.
        """

        return self._main_database.get("engine")

    def get_databases_data(self, *names: str) -> list[DatabaseDict]:
        """Get the database dictionaries for all the currently configured databases,
        containing the keys "name" for the database name, "engine" for the SQLAlchemy
        engine, "url" for the  database url in SQLAlchemy format, and if available,
        "conect_args" for a dictionary containing the database driver library-specific
        arguments for their `.connect()` function. The first dictionary to be returned
        is always that of the bot's main database.

        If string database names are given, only the dictionaries of those (if found)
        will be returned by the bot.

        Parameters
        ----------
        *names: :class:`str`
            The database name.

        Returns
        -------
        :class:`list`[:class:`dict`]
            A list of found dictionaries.
        """
        return [
            self._databases[name].copy()
            for name in (names if names else self._databases)
            if name in self._databases
        ]

    async def _init_extension_data_storage(self):
        if not self._main_database:
            return
        await utils.create_bot_extension_data_table(self._main_database)
        self._extension_data_storage_is_init = True

    async def _uninit_extension_data_storage(self):
        self._extension_data_storage_is_init = False

    async def create_extension_data(
        self,
        name: str,
        last_session_version: str,
        revision_number: int,
        auto_migrate: bool,
        db_table_prefix: str,
        data: bytes | None = None,
    ):
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")
        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )
        elif not isinstance(last_session_version, str):
            raise TypeError(
                f"argument 'last_session_version' must be of type 'str', not "
                f"'{last_session_version.__class__.__name__}'"
            )
        elif not isinstance(revision_number, int):
            raise TypeError(
                f"argument 'revision_number' must be of type 'int', not "
                f"'{revision_number.__class__.__name__}'"
            )
        elif not isinstance(auto_migrate, bool):
            raise TypeError(
                f"argument 'auto_migrate' must be of type 'bool', not "
                f"'{auto_migrate.__class__.__name__}'"
            )
        elif not isinstance(db_table_prefix, str):
            raise TypeError(
                f"argument 'db_table_prefix' must be of type 'str', not "
                f"'{db_table_prefix.__class__.__name__}'"
            )
        elif data is not None and not isinstance(data, bytes):
            raise TypeError(
                f"argument 'data' must be 'None' or of type 'bytes', "
                f"not '{data.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO bot_extension_data "
                    "(name, last_session_version, revision_number, auto_migrate, db_table_prefix, "
                    "data) VALUES (:name, :last_session_version, :revision_number, :auto_migrate, "
                    ":db_table_prefix, :data)"
                ),
                dict(
                    name=name,
                    last_session_version=last_session_version,
                    revision_number=revision_number,
                    auto_migrate=auto_migrate,
                    db_table_prefix=db_table_prefix,
                    data=data,
                ),
            )

    async def read_extension_data(self, name: str, data: bool = True) -> ExtensionData:
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        columns = "*"

        if not data:
            columns = "name, last_session_version, revision_number, auto_migrate, "
            "db_table_prefix"

        async with engine.connect() as conn:
            result: sqlalchemy.engine.Result = await conn.execute(
                text(f"SELECT {columns} FROM bot_extension_data WHERE name == :name"),
                dict(name=name),
            )

            row: Any = result.first()
            if row is None:
                raise LookupError(
                    f"Could not find extension storage data for extension named "
                    f"'{name}'"
                )

            return ExtensionData(
                name=row.name,
                last_session_version=row.last_session_version,
                revision_number=row.revision_number,
                auto_migrate=bool(row.auto_migrate),
                db_table_prefix=row.db_table_prefix,
                data=row.data,
            )

    async def extension_data_exists(self, name: str):
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.connect() as conn:
            storage_exists = bool(
                (
                    await conn.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM bot_extension_data WHERE name == :name)"
                        ),
                        dict(name=name),
                    )
                ).scalar()
            )
        return storage_exists

    async def update_extension_data(
        self,
        name: str,
        last_session_version: str | None = None,
        revision_number: int | None = None,
        auto_migrate: bool | None = None,
        db_table_prefix: str | None = None,
        data: bytes | None = None,
    ):

        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        elif last_session_version is not None and not isinstance(
            last_session_version, str
        ):
            raise TypeError(
                f"argument 'last_session_version' must be of type 'str', not "
                f"'{last_session_version.__class__.__name__}'"
            )
        elif revision_number is not None and not isinstance(revision_number, int):
            raise TypeError(
                f"argument 'revision_number' must be of type 'int', not "
                f"'{revision_number.__class__.__name__}'"
            )
        elif auto_migrate is not None and not isinstance(auto_migrate, bool):
            raise TypeError(
                f"argument 'auto_migrate' must be of type 'bool', not "
                f"'{auto_migrate.__class__.__name__}'"
            )
        elif db_table_prefix is not None and not isinstance(db_table_prefix, str):
            raise TypeError(
                f"argument 'db_table_prefix' must be of type 'str', not "
                f"'{db_table_prefix.__class__.__name__}'"
            )
        elif data is not None and not isinstance(data, bytes):
            raise TypeError(
                f"argument 'data' must be 'None' or of type 'bytes', "
                f"not '{data.__class__.__name__}'"
            )

        if not any(
            (last_session_version, revision_number, auto_migrate, db_table_prefix, data)
        ):
            raise TypeError(
                f"arguments 'last_session_version', 'revision_number', 'auto_migrate', 'db_table_prefix' "
                "and 'data' cannot all be 'None'"
            )

        engine: AsyncEngine = self._main_database["engine"]
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.begin() as conn:
            if not bool(
                (
                    await conn.execute(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM bot_extension_data WHERE name == :name)"
                        ),
                        dict(name=name),
                    )
                ).scalar()
            ):
                raise LookupError(
                    f"Could not find extension storage data for extension named "
                    f"'{name}'"
                )

            params = {}
            params["name"] = name
            params |= (
                dict(last_session_version=last_session_version)
                if last_session_version is not None
                else {}
            )
            params |= (
                dict(revision_number=revision_number)
                if revision_number is not None
                else {}
            )
            params |= (
                dict(auto_migrate=auto_migrate) if auto_migrate is not None else {}
            )
            params |= (
                dict(db_table_prefix=db_table_prefix)
                if db_table_prefix is not None
                else {}
            )
            params |= dict(data=data) if data is not None else {}

            target_columns = ", ".join((f"{k} = :{k}" for k in params))

            await conn.execute(
                text(
                    "UPDATE bot_extension_data AS bed"
                    + f" SET {target_columns}"
                    + " WHERE bed.name == :name",
                ),
                parameters=params,
            )

    async def delete_extension_data(self, name: str):
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM bot_extension_data WHERE name == :name"),
                dict(name=name),
            )
