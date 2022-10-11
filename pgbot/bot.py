"""This file should define the `discord.ext.commands.Bot` subclass to use for the project. 
"""

import asyncio
from collections import OrderedDict
import datetime
import logging
import time
from typing import Any, Optional, Type, Union

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
import sqlalchemy.engine
import sqlalchemy.exc
from sqlalchemy import text
import discord
from discord.ext import commands, tasks
import snakecore
from snakecore.constants import UNSET
from snakecore.utils.pagination import EmbedPaginator

from . import utils

_logger = logging.getLogger(__name__)


class PygameBot(snakecore.commands.Bot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._botconfig: dict = {}
        self._launchconfig: dict = {}
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

        self._main_database: dict[str, Union[str, dict, AsyncEngine]] = {}
        self._databases: dict[str, dict[str, Union[str, dict, AsyncEngine]]] = {}
        self._extension_data_storage_is_init = False

        self.before_invoke(self.bot_before_invoke)
        self.after_invoke(self.bot_after_invoke)

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

    async def process_commands(
        self, message: discord.Message, /, ctx: Optional[commands.Context] = None
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

    async def on_message_edit(self, old: discord.Message, new: discord.Message) -> None:
        if new.author.bot:
            return

        if (time.time() - (new.edited_at or new.created_at).timestamp()) < 120:
            if (
                (ctx := await self.get_context(new)).valid
                and ctx.command is not None
                and (
                    ctx.command.extras.get("invoke_on_message_edit", False)
                    or ctx.command.extras.get("invoke_on_message_edit") is not False
                    and ctx.command.cog is not None
                    and getattr(ctx.command.cog, "invoke_on_message_edit", False)
                )
            ):
                await self.process_commands(new, ctx=ctx)

    async def bot_before_invoke(self, ctx: commands.Context):
        if (
            ctx.command is not None
            and ctx.command.extras.get("reference_message_is_argument", False)
            and ctx.message.reference is not None
            and isinstance(ctx.message.reference.resolved, discord.Message)
        ):
            if ctx.args and isinstance(
                ctx.args[0], commands.Cog
            ):  # command was defined inside cog
                ctx.args.insert(2, ctx.message.reference.resolved)
            else:
                ctx.args.insert(1, ctx.message.reference.resolved)

    async def bot_after_invoke(self, ctx: commands.Context):
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

        if (
            ctx.command is not None
            and (
                ctx.command.extras.get("response_message_deletion_by_author", False)
                or ctx.command.extras.get("response_message_deletion_by_author")
                is not False
                and ctx.command.cog is not None
                and getattr(
                    ctx.command.cog, "response_message_deletion_by_author", False
                )
            )
            and (response_message := self.cached_response_messages.get(ctx.message.id))
            is not None
        ):

            snakecore.utils.hold_task(
                asyncio.create_task(
                    utils.message_delete_reaction_listener(
                        self,
                        response_message,
                        ctx.author,
                        emoji="🗑",
                        timeout=30,
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
        origin: Union[discord.Message, discord.Interaction],
        /,
        *,
        cls: Type[commands.Context["PygameBot"]] = discord.utils.MISSING,
    ) -> commands.Context["PygameBot"]:
        new_ctx = await super().get_context(origin, cls=cls)
        setattr(new_ctx, "created_at", datetime.datetime.now(datetime.timezone.utc))
        return new_ctx

    async def _create_database_connections(self) -> None:
        self._databases = {
            db_dict["name"]: db_dict
            for db_dict in await utils.load_databases(
                self._launchconfig["databases"], raise_exceptions=False, logger=_logger
            )
            if isinstance(db_dict["name"], str)
        }

        failures = len(self._launchconfig["databases"]) - len(self._databases.keys())

        if failures == len(self._launchconfig["databases"]):
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
        if "databases" in self._launchconfig:
            await self._create_database_connections()
            await self._init_extension_data_storage()

        for ext_dict in self._launchconfig["extensions"]:
            try:
                await self.load_extension_with_config(
                    ext_dict["name"],
                    package=ext_dict.get("package"),
                    config=ext_dict.get("config"),
                )
            except commands.ExtensionAlreadyLoaded:
                continue

            except (TypeError, commands.ExtensionError) as exc:
                _logger.error(
                    f"Failed to load extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch",
                    exc_info=exc,
                )
            else:
                _logger.info(
                    f"Successfully loaded extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch"
                )

    async def teardown_hook(self) -> None:
        self.handle_loading_reactions.cancel()
        if self._databases:
            await self._close_database_connections()

    async def on_ready(self):
        assert self.user is not None
        self.loading_emoji = self.get_emoji(1017826887990509661) or self.loading_emoji
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")
        handle_loading_reactions = self.handle_loading_reactions
        if not handle_loading_reactions.is_running():
            handle_loading_reactions.start()

    async def on_command_error(
        self, context: commands.Context["PygameBot"], exception: commands.CommandError
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

        color = 0xFF0000

        if isinstance(
            exception, commands.CommandNotFound
        ):  # prevent potentially unintended command invocations
            return

        elif isinstance(exception, commands.BadArgument):
            if (
                isinstance(exception, commands.BadFlagArgument)
                and exception.original.args
            ):
                description = exception.original.args[0]
            title = "Invalid argument(s)!"
            description = (
                f"{description}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.UserInputError):
            title = "Invalid command input(s)!"
            description = (
                f"{description}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.DisabledCommand):
            title = f"Cannot execute command! ({exception.args[0]})"
            description = (
                f"The specified command has been temporarily disabled, "
                "while the bot wizards are casting their spells on it!\n"
                "Please try running the command after the maintenance work "
                "has finished."
            )
        elif isinstance(exception, commands.CommandInvokeError):
            if isinstance(exception.__cause__, (type(None), discord.HTTPException)):
                title = f"Command `{context.invoked_with}` reported an error:"
                description = exception.args[0] if exception.args else ""
                description = description.replace(
                    f"Command raised an exception: {exception.original.__class__.__name__}: ",
                    "",
                )
                color = 0x851D08
                footer_text = exception.__class__.__name__

            else:
                log_exception = True
                has_cause = True
                title = "Unknown error!"
                description = (
                    "An unknown error occured while running the "
                    f"{context.command.qualified_name} command!\n"
                    "This is most likely a bug in the bot itself, and our fellow bot wizards will "
                    f"recast magical spells on it soon!\n\n"
                    f"```\n{exception.__cause__.args[0] if exception.__cause__.args else ''}```"
                )
                footer_text = exception.__cause__.__class__.__name__

        elif isinstance(exception, commands.ConversionError):
            log_exception = True
            has_cause = True
            title = "Unknown error!"
            description = (
                "An unknown error occured while running the "
                f"{context.command.qualified_name} command!\n"
                "This is most likely a bug in the bot itself, and our fellow bot wizards will "
                f"recast magical spells on it soon!\n\n"
                f"```\n{exception.__cause__.args[0] if exception.__cause__ and exception.__cause__.args else ''}```"
            )
            footer_text = exception.__cause__.__class__.__name__

        footer_text = f"{footer_text}\n(React with 🗑 to delete this error message in the next 30s)"

        if send_error_message:
            target_message = self._recent_response_error_messages.get(
                context.message.id
            )
            try:
                (
                    (
                        await snakecore.utils.embeds.replace_embed_at(
                            target_message,
                            title=title,
                            description=description,
                            color=color,
                            footer_text=footer_text,
                        )
                    )
                    if target_message is not None
                    else (
                        target_message := await snakecore.utils.embeds.send_embed(
                            context.channel,
                            title=title,
                            description=description,
                            color=color,
                            footer_text=footer_text,
                        )
                    )
                )
            except discord.NotFound:
                # response message was deleted, send a new message
                target_message = await snakecore.utils.embeds.send_embed(
                    context.channel,
                    title=title,
                    description=description,
                    color=color,
                    footer_text=footer_text,
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
                "An unhandled exception occured in command %s",
                context.invoked_with
                if context.invoked_with
                else context.command.qualified_name,
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

    def get_database_data(self) -> Optional[dict[str, Union[str, dict, AsyncEngine]]]:
        """Get the database dictionary for the primary database of this bot,
        containing the keys "name" for the database name, "engine" for the
        SQLAlchemy engine and if available, "conect_args" for a dictionary
        containing the database driver library-specific arguments for their
        `.connect()` function.

        Returns:
            Optional[dict]: The dictionary, or None dictionary if nothing was
              loaded/configured.
        """
        if not self._main_database:
            return None

        db_dict = self._main_database.copy()
        if "url" in db_dict:
            del db_dict["url"]
        return db_dict

    def get_database(self) -> Optional[AsyncEngine]:
        """Get the `sqlachemy.ext.asyncio.AsyncEngine` object for the primary
        database of this bot.

        Returns:
            Optional[AsyncEngine]: The engine, or None if nothing was
              loaded/configured.
        """

        return self._main_database.get("engine")  # type: ignore

    def get_databases(
        self, *names: str
    ) -> list[dict[str, Union[str, dict, AsyncEngine]]]:
        """Get the database dictionaries for all the databases of this bot,
        containing the keys "name" for the database name, "engine" for the
        SQLAlchemy engine and if available, "conect_args" for a dictionary
        containing the database driver library-specific arguments for their
        `.connect()` function. The first dictionary to be returned is always
        that of the bot's primary database.

        If string database names are given, only the
        dictionaries of those (if found) will be returned by the bot.

        Returns:
            list[dict]: The dictionaries.
        """

        db_dicts = []

        for name in names if names else self._databases:
            if name in self._databases:
                db_dict = self._databases[name].copy()
                if "url" in db_dict:
                    del db_dict["url"]

                db_dicts.append(db_dict)

        return db_dicts

    async def _init_extension_data_storage(self):
        if not self._main_database:
            return

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection
        async with engine.begin() as conn:
            if engine.name == "sqlite":
                await conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS "
                        "bot_extension_data"
                        "(name VARCHAR(1000), version VARCHAR(1000), table_name_prefix VARCHAR(1000), data BLOB)"
                    )
                )

            elif engine.name == "postgresql":
                await conn.execute(
                    text(
                        "CREATE TABLE IF NOT EXISTS "
                        "bot_extension_data"
                        "(name VARCHAR(1000), version VARCHAR(1000), table_name_prefix VARCHAR(1000), data BYTEA)"
                    )
                )

        self._extension_data_storage_is_init = True

    async def _uninit_extension_data_storage(self):
        self._extension_data_storage_is_init = False

    async def create_extension_data(
        self,
        name: str,
        version: str,
        table_name_prefix: str,
        initial_data: Optional[bytes] = None,
    ):

        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")
        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )
        elif not isinstance(version, str):
            raise TypeError(
                f"argument 'version' must be of type 'str', not "
                f"'{version.__class__.__name__}'"
            )
        elif not isinstance(table_name_prefix, str):
            raise TypeError(
                f"argument 'table_name_prefix' must be of type 'str', not "
                f"'{table_name_prefix.__class__.__name__}'"
            )
        elif initial_data is not None and not isinstance(initial_data, bytes):
            raise TypeError(
                f"argument 'initial_data' must be 'None' or of type 'bytes', "
                f"not '{initial_data.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "INSERT INTO bot_extension_data "
                    "(name, version, table_name_prefix, data) "
                    "VALUES (:name, :version, :table_name_prefix, :initial_data)"
                ),
                dict(
                    name=name,
                    version=version,
                    table_name_prefix=table_name_prefix,
                    initial_data=initial_data,
                ),
            )
            await conn.commit()

    async def read_extension_data(self, name: str) -> dict[str, Union[str, bytes]]:
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.connect() as conn:
            result: sqlalchemy.engine.Result = await conn.execute(
                text("SELECT * FROM bot_extension_data"),
                dict(name=name),
            )

            row: Any = result.first()
            if row is None:
                raise LookupError(
                    f"Could not find extension storage data for extension named "
                    f"'{name}'"
                )

            return dict(
                name=row.name,
                version=row.version,
                table_name_prefix=row.table_name_prefix,
                data=row.data,
            )

    async def check_extension_data_exists(self, name: str):
        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
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
                ).first()[0]
            )
        return storage_exists

    async def update_extension_data(
        self,
        name: str,
        version: Optional[str] = None,
        table_name_prefix: Optional[str] = None,
        data: Optional[bytes] = None,
    ):

        if not self._extension_data_storage_is_init:
            raise RuntimeError("Extension data storage was not initialized.")

        elif not isinstance(name, str):
            raise TypeError(
                f"argument 'name' must be a fully qualified extension "
                "name of type 'str', not "
                f"'{name.__class__.__name__}'"
            )

        elif version is not None and not isinstance(version, str):
            raise TypeError(
                f"argument 'version' must be of type 'str', not "
                f"'{version.__class__.__name__}'"
            )
        elif table_name_prefix is not None and not isinstance(table_name_prefix, str):
            raise TypeError(
                f"argument 'table_name_prefix' must be of type 'str', not "
                f"'{table_name_prefix.__class__.__name__}'"
            )
        elif data is not None and not isinstance(data, bytes):
            raise TypeError(
                f"argument 'data' must be 'None' or of type 'bytes', "
                f"not '{data.__class__.__name__}'"
            )

        if not any((version, table_name_prefix, data)):
            raise TypeError(
                f"'version', 'table_name_prefix' and 'data' cannot all be 'None'"
            )

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.begin() as conn:
            if not (
                await conn.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM bot_extension_data WHERE name == :name)"
                    ),
                    dict(name=name),
                )
            ).first()[0]:
                raise LookupError(
                    f"Could not find extension storage data for extension named "
                    f"'{name}'"
                )

            params = {}
            params |= dict(version=version) if version is not None else {}
            params |= (
                dict(table_name_prefix=table_name_prefix)
                if table_name_prefix is not None
                else {}
            )
            params |= dict(data=data) if data is not None else {}

            target_columns = ", ".join((f"{k} = :{k}" for k in params))

            params["name"] = name

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

        engine: AsyncEngine = self._main_database["engine"]  # type: ignore
        conn: AsyncConnection

        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(f"Unsupported database dialect '{engine.name}'")

        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM bot_extension_data WHERE name == :name"),
                dict(name=name),
            )
