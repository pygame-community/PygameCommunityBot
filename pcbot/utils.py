"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
from collections import deque
from dataclasses import dataclass
import importlib.util
import io
import logging
import logging.handlers
from math import log10
import os
import sys
import types
from typing import (
    Any,
    Callable,
    Collection,
    Coroutine,
    Hashable,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
    Union,
)

import discord
from discord.ext import commands
from discord.utils import _ColourFormatter
import snakecore
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.ext.asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncConnection

from ._types import DatabaseDict, ConfigDatabaseDict


class DefaultFormatter(logging.Formatter):
    default_msec_format = "%s.%03d"

    def formatException(self, ei):
        return f"...\n{super().formatException(ei)}\n..."


class ANSIColorFormatter(_ColourFormatter):
    FORMATS = {
        level: DefaultFormatter(
            f"\x1b[30;1m%(asctime)s\x1b[0m {colour}%(levelname)-8s\x1b[0m \x1b[35m%(name)s\x1b[0m %(message)s",
        )
        for level, colour in _ColourFormatter.LEVEL_COLOURS
    }


class RotatingTextIOHandler(logging.handlers.BaseRotatingHandler):
    """A subclass of `BaseRotatingHandler` that uses in-memory string buffers to
    write logging information to."""

    def __init__(
        self,
        maxBytes: int = 0,
        backupCount: int = 0,
        errors=None,
    ):
        self.maxBytes: int = maxBytes
        self.backupCount: int = backupCount

        self.baseFilename = ""
        self.mode = "a"
        self.encoding = "utf-8"
        self.errors = errors
        self.delay = False

        self.stream: io.StringIO = io.StringIO()
        self.streams: deque[io.StringIO] = deque()
        self.streams.append(self.stream)
        logging.Handler.__init__(self)

    def close(self):
        """
        Closes the stream.
        """
        self.acquire()
        try:
            try:
                if self.stream:
                    try:
                        self.flush()
                    finally:
                        for stream in self.streams:
                            if hasattr(stream, "close"):
                                stream.close()
                        self.stream = None  # type: ignore
            finally:
                # Issue #19523: call unconditionally to
                # prevent a handler leak when delay is set
                logging.StreamHandler.close(self)
        finally:
            self.release()

    def emit(self, record):
        """
        Emit a record.

        Output the record to the file, catering for rollover as described
        in doRollover().
        """
        try:
            if self.shouldRollover(record):
                self.doRollover()

            msg = self.format(record)
            stream = self.stream
            # issue 35046: merged two stream.writes into one.
            stream.write(msg + self.terminator)
            self.flush()
        except RecursionError:  # See issue 36272
            raise
        except Exception:
            self.handleError(record)

    def doRollover(self):
        """
        Do a rollover, as described in __init__().
        """
        old_stream = self.stream
        self.stream = io.StringIO()
        if self.backupCount > 0:
            self.streams.appendleft(self.stream)
            for _ in range(len(self.streams) - self.backupCount):
                self.streams.pop().close()
        else:
            old_stream.close()

    def shouldRollover(self, record):
        """
        Determine if rollover should occur.

        Basically, see if the supplied record would cause the file to exceed
        the size limit we have.
        """
        if self.maxBytes > 0:  # are we rolling over?
            msg = "%s\n" % self.format(record)
            self.stream.seek(0, 2)  # due to non-posix-compliant Windows feature
            if self.stream.tell() + len(msg) >= self.maxBytes:
                return True
        return False

    def __repr__(self):
        level = logging.getLevelName(self.level)
        return "<%s %s (%s)>" % (self.__class__.__name__, ":memory:", level)


class CustomRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A `RotatingFileHandler` subclass that supports padding backup numbers
    with zeros for alphabetical file name sorting, as well as adding a file
    extension as a suffix behind backup numbers.
    """

    def __init__(
        self,
        filename,
        mode="a",
        maxBytes=0,
        backupCount=0,
        encoding=None,
        delay=False,
        errors=None,
        extension=None,
    ):
        self.extension = extension.removeprefix(".") if extension else None
        self.file_number_width = int(log10(backupCount)) + 1 if backupCount > 0 else 0
        super().__init__(
            filename,
            mode,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )

    def _open(self):
        return open(
            self.baseFilename + f".{self.extension}" if self.extension else "",
            self.mode,
            encoding=self.encoding,
            errors=self.errors,
        )

    def doRollover(self):
        """
        Do a rollover, as described in __init__().
        """
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore

        extension = f".{self.extension}" if self.extension else ""
        if self.backupCount > 0:
            truncBaseFileName = self.baseFilename
            zerosuff_start_idx = truncBaseFileName.rfind(".") + 1
            zero_suff = truncBaseFileName[zerosuff_start_idx:]

            if zero_suff.isnumeric() and all(
                s == "0" for s in zero_suff
            ):  # handle potential trailing zeros in file name
                truncBaseFileName = truncBaseFileName[: zerosuff_start_idx - 1]

            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(
                    f"{truncBaseFileName}.{i:0>{self.file_number_width}}{extension}"
                )
                dfn = self.rotation_filename(
                    f"{truncBaseFileName}.{i+1:0>{self.file_number_width}}{extension}"
                )
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)

            dfn = self.rotation_filename(
                f"{truncBaseFileName}.{1:0>{self.file_number_width}}{extension}"
            )  # add zero-padding to the backup number
            if os.path.exists(dfn):
                os.remove(dfn)
            self.rotate(self.baseFilename + extension, dfn)
        if not self.delay:
            self.stream = self._open()  # type: ignore


class DummyHandler(logging.NullHandler):
    """A subclass of `logging.NullHandler` that handles `LogRecord` objects to e.g.
    call filters.
    """

    def handle(self, record: logging.LogRecord) -> bool:
        return super(logging.NullHandler, self).handle(record)


class QueuingFilter(logging.Filter):
    """A logging filter that stores filtered log records in a queue."""

    def __init__(
        self,
        name: str = "",
        queue_level: int = logging.NOTSET,
        maxlen: int | None = None,
    ) -> None:
        super().__init__(name)
        self.queue: deque[logging.LogRecord] = deque(maxlen=maxlen)
        self.queue_level = queue_level

    def filter(self, record: logging.LogRecord) -> bool:
        if (can_pass := super().filter(record)) and record.levelno >= self.queue_level:
            self.queue.append(record)
        return can_pass


DEFAULT_FORMATTER = DefaultFormatter(
    "[{asctime}] [ {levelname:<8} ] {name} -- {message}", style="{"
)

DEFAULT_FORMATTER_REGEX = r"\[(\d{4}-\d\d-\d\d.\d\d:\d\d:\d\d\.\d\d\d)\] *\[ *(\S+) *\] *(.+) -- ((?:(?!\n\[(\d{4}-\d\d-\d\d.\d\d:\d\d:\d\d\.\d\d\d)\])\n|.)+)"
# detects formatted output written by DEFAULT_FORMATTER, including appended tracebacks
# on followup lines

ANSI_FORMATTER = ANSIColorFormatter()


def import_module_from_path(module_name: str, file_path: str) -> types.ModuleType:
    abs_file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_file_path)  # type: ignore
    if spec is None:
        raise ImportError(
            f"failed to generate module spec for module named '{module_name}' at '{abs_file_path}'"
        )
    module = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore
    except FileNotFoundError as fnf:
        del sys.modules[module_name]
        raise ImportError(
            f"failed to find code for module named '{module_name}' at '{abs_file_path}'"
        ) from fnf
    except Exception:
        del sys.modules[module_name]
        raise

    return module


def unimport_module(module: types.ModuleType) -> None:
    """Unimport a module, by deleting it from `sys.modules`.
    Note that this will not remove any existing outer references
    to the module.

    Parameters
    ----------
    module : ModuleType
        The module object.
    """
    if module.__name__ in sys.modules:
        del sys.modules[module.__name__]


async def load_databases(
    db_info_data: Sequence[ConfigDatabaseDict],
    raise_exceptions: bool = True,
    logger: logging.Logger | None = None,
) -> list[DatabaseDict]:
    dbs = []

    for db_info_dict in db_info_data:
        db_name = db_info_dict["name"]
        engine = None

        try:
            engine_kwargs = {}

            if "connect_args" in db_info_dict:
                engine_kwargs["connect_args"] = db_info_dict["connect_args"]

            engine = create_async_engine(db_info_dict["url"], **engine_kwargs)

            async with engine.connect():  # test if connection is possible
                pass

        except sqlalchemy.exc.SQLAlchemyError as exc:
            if logger is not None:
                logger.error(
                    f"Failed to create engine and functioning connection "
                    + (
                        f"'{engine.name}+{engine.driver}' "
                        if engine is not None
                        else ""
                    )
                    + f"for database '{db_name}'",
                    exc_info=exc,
                )

            if raise_exceptions:
                raise
        else:
            dbs.append({"name": db_name, "engine": engine, "url": db_info_dict["url"]})

            if "connect_args" in db_info_dict:
                dbs[db_name]["connect_args"] = db_info_data["connect_args"]  # type: ignore

            if logger is not None:
                logger.info(
                    f"Successfully configured engine '{engine.name}+{engine.driver}' "
                    f"for database '{db_name}'"
                )

    return dbs


async def unload_databases(
    dbs: Iterable[DatabaseDict],
    raise_exceptions: bool = True,
    logger: logging.Logger | None = None,
):
    for db_dict in dbs:
        db_name = db_dict["name"]
        if not isinstance(db_dict["engine"], AsyncEngine):
            raise TypeError(
                "db_dict['engine'] must be instance of AsnycEngine for all dicts in 'dbs'"
            )

        engine: AsyncEngine = db_dict["engine"]

        try:
            await engine.dispose()
        except sqlalchemy.exc.SQLAlchemyError as err:
            if logger is not None:
                logger.error(
                    f"Failed to dispose connection pool of engine '{engine.name}+{engine.driver}' of database '{db_name}'",
                    exc_info=err,
                )

            if raise_exceptions:
                raise
        else:
            if logger is not None:
                logger.info(
                    f"Successfully disposed connection pool of engine '{engine.name}+{engine.driver}' of database '{db_name}'"
                )


async def create_bot_extension_data_table(db: DatabaseDict):
    engine = db["engine"]
    conn: AsyncConnection
    async with engine.begin() as conn:
        if engine.name == "sqlite":
            await conn.execute(
                sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS bot_extension_data ("
                    "name VARCHAR(1000), "
                    "last_session_version VARCHAR(1000), "
                    "revision_number INTEGER, "
                    "auto_migrate INTEGER, "
                    "db_table_prefix VARCHAR(1000), "
                    "data BLOB)"
                )
            )

        elif engine.name == "postgresql":
            await conn.execute(
                sqlalchemy.text(
                    "CREATE TABLE IF NOT EXISTS bot_extension_data ("
                    "name VARCHAR(1000), "
                    "last_session_version VARCHAR(1000), "
                    "revision_number INTEGER, "
                    "auto_migrate SMALLINT, "
                    "db_table_prefix VARCHAR(1000), "
                    "data BYTEA)"
                )
            )
        else:
            raise RuntimeError(f"Unsupported database engine: {engine.name}")


async def message_delete_reaction_listener(
    client: discord.Client | discord.AutoShardedClient,
    message: discord.Message,
    invoker: discord.Member | discord.User,
    emoji: discord.Emoji | discord.PartialEmoji | str,
    role_whitelist: Collection[discord.Role | int] | None = None,
    timeout: float | None = None,
    on_delete: Callable[[discord.Message], Coroutine[Any, Any, Any]]
    | Callable[[discord.Message], Any]
    | None = None,
):
    """Allows for a message to be deleted using a specific reaction.
    If any HTTP-related exceptions are raised by `discord.py` within this function,
    it will fail silently.

    Parameters
    ----------
    message : :class:`discord.Message`
        The message to use.
    invoker : :class:`discord.Member` | :class:`discord.User`
        The member/user who can delete a message.
    emoji : :class:`discord.Emoji` | :class:`discord.PartialEmoji` | :class:`str`):
        The emoji to listen for.
    role_whitelist : Collection[:class:`discord.Role` | :class:`int`] | None, optional
        A collection of roles or role IDs whose users' reactions can also be picked up by this function.
    timeout : :class:`float` | None, optional
        A timeout for waiting, before automatically removing any added reactions and returning silently.
    on_delete : Callable[[:class:`discord.Message`], Coroutine[Any, Any, Any]] | Callable[[:class:`discord.Message`], Any] | None, optional
        A (coroutine) function to call when a message is successfully deleted via the reaction. Defaults to `None`.

    Raises
    ------
    TypeError
        Invalid argument types.
    """

    role_whitelist_set = set(
        r.id if isinstance(r, discord.Role) else r for r in (role_whitelist or ())
    )

    if not isinstance(emoji, (discord.Emoji, discord.PartialEmoji, str)):
        raise TypeError("invalid emoji given as input.")

    try:
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            return

        check = None
        if isinstance(invoker, discord.Member):
            check = (
                lambda event: event.message_id == message.id
                and (
                    event.user_id == invoker.id
                    or any(
                        role.id in role_whitelist_set
                        for role in getattr(event.member, "roles", ())[1:]
                    )
                )
                and snakecore.utils.is_emoji_equal(event.emoji, emoji)
            )
        elif isinstance(invoker, discord.User):
            if isinstance(message.channel, discord.DMChannel):
                check = (
                    lambda event: event.message_id == message.id
                    and snakecore.utils.is_emoji_equal(event.emoji, emoji)
                )
            else:
                check = (
                    lambda event: event.message_id == message.id
                    and event.user_id == invoker.id
                    and snakecore.utils.is_emoji_equal(event.emoji, emoji)
                )
        else:
            raise TypeError(
                "argument 'invoker' expected discord.Member/.User, "
                f"not {invoker.__class__.__name__}"
            )

        event: discord.RawReactionActionEvent = await client.wait_for(
            "raw_reaction_add", check=check, timeout=timeout
        )

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        else:
            if on_delete is not None:
                await discord.utils.maybe_coroutine(on_delete, message)

    except asyncio.TimeoutError:
        try:
            await message.clear_reaction(emoji)
        except discord.HTTPException:
            pass


def raise_exc(exc: Exception):
    raise exc


class ParserMapping(dict[str, Callable[[str, Any, MutableMapping[str, Any]], Any]
            | "ParserMapping"
            | "ParserMappingValue",]):
    """A `dict` subclass that parses and/or validates mapping objects based on the
    structure and callback values of the input mapping given to it. The parsing and/or
    validating occurs in the order of definition of the key-value pairs of the input
    mapping. Input mapping fields can be marked as required using
    `ParserMappingValue(..., required=True)` as a value.

    `ParserMapping` instances can be arbitrarily nested inside input mappings of
    outer `ParserMapping` as values, to define more complex reqirements for the
    mappings to be validated and/or parsed.


    Examples
    --------

    ```py
    import re

    def raise_exception(exc):
        raise exc

    parser_mapping = ParserMapping(
        {
            "username": str,
            "password": lambda key, value, values_map: value # `values_map` is the value of the 
            if isinstance(value, str) and len(value) > 8
            else raise_exception(
                ParserMapping.ParsingError(
                    f"value for field '{key}' must be a string longer than 8 characters"
                )
            ),
            "email": ParserMappingValue(
                lambda key, value, values_map: value
                if isinstance(value, str) and re.match(r"^[\\w\\.]+@[\\w\\.]+$")
                else raise_exception(
                    ParserMapping.ParsingError(
                        f"value for field '{key}' must be a string that is a valid email"
                    )
                ),
                required=True,
            ),
            ...: ...,
        },
    )

    parsed = parser_mapping.parse(
        {"username": "abc", "password": 123456789}
    )  # will raise an exception, as "email" is missing and "password" is of the wrong type.
    ```
    """

    __slots__ = (
        "_key",
        "_parent",
        "require_all",
    )

    class ParsingError(Exception):
        """A class for :class:`ParserMapping` related parsing errors.
        """
        pass

    def __init__(
        self,
        mapping: Mapping[
            str,
            Callable[[str, Any, MutableMapping[str, Any]], Any]
            | "ParserMapping"
            | "ParserMappingValue",
        ],
        require_all: bool = False,
    ):
        self._key: str | None = None
        self._parent: ParserMapping | None = None
        self.require_all = require_all
        if not isinstance(mapping, Mapping):
            raise TypeError("argument 'mapping' must be a mapping object")

        temp_mapping = {}

        current_pmv = None
        for k, v in tuple(mapping.items()): # begin 
            if isinstance(v, ParserMappingValue): # A ParserMappingValue was explicitly declared
                current_pmv = v
                v = v.value

            if isinstance(v, self.__class__): # build parent-child references with nested ParserMappings
                v._parent = self
                v._key = k
            elif isinstance(v, type):  # convert class object to a validator using issinstance
                callback = (
                    lambda key, value, mapping: value
                    if isinstance(value, v)  # type: ignore
                    else raise_exc(
                        self.__class__.ParsingError(
                            f"value "
                            + (
                                f"at fully qualified key '{qk}' "
                                if (qk := self._get_qualified_key())
                                else " "
                            )
                            + f"must be an instance of '{v.__name__}' not '{type(value).__name__}'"
                        )
                    )
                )
                if current_pmv:
                    current_pmv.value = callback
                else:
                    temp_mapping[k] = v = callback

            elif not callable(v):
                raise ValueError(
                    f"value for mapping key '{k}' is not a class, callable, ParserMappingValue or a "
                    f"'{self.__class__.__name__}' object"
                )

            current_pmv = None

        self.update(mapping)
        self.update(temp_mapping)

    def _get_qualified_key(self, sep: str = ".") -> str:
        keys = []
        if self._key:
            keys.append(self._key)
        curr_parent = self._parent

        while curr_parent is not None:
            if curr_parent._key is not None:
                keys.append(
                    f"'{curr_parent._key}'"
                    if "." in curr_parent._key
                    else curr_parent._key
                )
            curr_parent = curr_parent._parent

        return sep.join(reversed(keys))

    def parse(
        self, input_mapping: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        if not isinstance(input_mapping, MutableMapping):
            raise self.__class__.ParsingError(
                f"value"
                + (
                    f"at fully qualified key '{qk}' "
                    if (qk := self._get_qualified_key())
                    else " "
                )
                + "must be an instance of a mutable mapping "
                "type instantiable without arguments (e.g. dict)"
            )

        if self.require_all and len(input_mapping) < len(self):
            raise self.__class__.ParsingError(
                "Cannot parse input mapping "
                + (
                    f"at fully qualified key " + f"'{qk}' "
                    if (qk := self._get_qualified_key())
                    else " "
                )
                + " as all values are required and some are missing "
            )

        try:
            output_mapping = input_mapping.__class__()
        except TypeError as t:
            raise self.__class__.ParsingError(
                f"value"
                + (
                    f"at fully qualified key '{qk}' "
                    if (qk := self._get_qualified_key())
                    else " "
                )
                + "must be an instance of a mutable mapping "
                "type instantiable without arguments (e.g. dict)"
            ) from t

        for k, v_or_pmv in self.items():
            was_pmv = False
            if isinstance(v_or_pmv, ParserMappingValue):
                was_pmv = True
                v = v_or_pmv.value
            else:
                v = v_or_pmv

            if k in input_mapping:
                if isinstance(v, self.__class__):
                    output_mapping[k] = v.parse(input_mapping[k])
                else:
                    output_mapping[k] = v(k, input_mapping[k], output_mapping)  # type: ignore
            elif was_pmv and v_or_pmv.required or self.require_all: # type: ignore
                raise self.__class__.ParsingError(
                    f"mapping "
                    + (
                        f"at fully qualified key '{qk}' "
                        if (qk := self._get_qualified_key())
                        else " "
                    )
                    + f"is missing required key '{k}' "
                )

        return output_mapping


@dataclass
class ParserMappingValue:
    value: Callable[[str, Any, MutableMapping], Any] | ParserMapping
    required: bool = False
