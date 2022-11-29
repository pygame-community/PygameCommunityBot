"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

import asyncio
from collections import deque
import importlib
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
    Iterable,
    Optional,
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

from ._types import _DatabaseDict, _InputDatabaseDict


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
        self.extension = extension
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
        maxlen: Optional[int] = None,
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

DEFAULT_FORMATTER_REGEX = r"\[(\d{4}-\d\d-\d\d.\d\d:\d\d:\d\d\.\d\d\d)\](?:(?!\n\[(\d{4}-\d\d-\d\d.\d\d:\d\d:\d\d\.\d\d\d)\])\n|.)+"
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
        spec.loader.exec_module(module)
    except FileNotFoundError as fnf:
        raise ImportError(
            f"failed to find code for module named '{module_name}' at '{abs_file_path}'"
        ) from fnf
    return module


async def load_databases(
    db_info_data: Sequence[_InputDatabaseDict],
    raise_exceptions: bool = True,
    logger: Optional[logging.Logger] = None,
) -> list[_DatabaseDict]:
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
    dbs: Iterable[_DatabaseDict],
    raise_exceptions: bool = True,
    logger: Optional[logging.Logger] = None,
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


async def message_delete_reaction_listener(
    client: Union[discord.Client, discord.AutoShardedClient],
    msg: discord.Message,
    invoker: Union[discord.Member, discord.User],
    emoji: Union[discord.Emoji, discord.PartialEmoji, str],
    role_whitelist: Optional[Collection[Union[discord.Role, int]]] = None,
    timeout: Optional[float] = None,
    on_delete: Union[
        Callable[[discord.Message], Coroutine[Any, Any, Any]],
        Callable[[discord.Message], Any],
        None,
    ] = None,
):
    """Allows for a message to be deleted using a specific reaction.
    If any HTTP-related exceptions are raised by `discord.py` within this function,
    it will fail silently.

    Parameters
    ----------
        msg: :class:`discord.Message`
            The message to use.
        invoker: Union[:class:`discord.Member`, :class:`discord.User`]
            The member/user who can delete a message.
        emoji Union[:class:`discord.Emoji`, :class:`discord.PartialEmoji`, :class:`str`]):
            The emoji to listen for.
        role_whitelist Optional[Collection[Union[:class:`discord.Role`, :class:`int`]]], optional
            A collection of roles or role IDs whose users' reactions can also be picked up by this function.
        timeout: Optional[:class:`float`], optional
            A timeout for waiting, before automatically removing any added reactions and returning silently.
        on_delete: Union[Callable[[:class:`discord.Message`], Coroutine[Any, Any, Any]], Callable[[:class:`discord.Message`], Any], None], optional
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
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            return

        check = None
        if isinstance(invoker, discord.Member):
            check = (
                lambda event: event.message_id == msg.id
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
            if isinstance(msg.channel, discord.DMChannel):
                check = (
                    lambda event: event.message_id == msg.id
                    and snakecore.utils.is_emoji_equal(event.emoji, emoji)
                )
            else:
                check = (
                    lambda event: event.message_id == msg.id
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
            await msg.delete()
        except discord.HTTPException:
            pass
        else:
            if on_delete is not None:
                await discord.utils.maybe_coroutine(on_delete, msg)

    except asyncio.TimeoutError:
        try:
            await msg.clear_reaction(emoji)
        except discord.HTTPException:
            pass
