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
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)

import discord
from discord.ext import commands
from discord.utils import _ColourFormatter
from typing_extensions import NotRequired  # type: ignore
import snakecore
from snakecore.constants import UNSET
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.ext.asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection, AsyncEngine

import pcbot
from pcbot.constants import UID

from ..types import Config, ConfigDatabaseDict, DatabaseDict, ExtensionData, Revision

_logger = logging.getLogger(__name__)


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


class RotatingFileHandler(logging.handlers.RotatingFileHandler):
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


def validate_revision_list(lst: list[Revision]) -> list[Revision]:
    for j, revision in enumerate(lst):
        for k in ("date", "description", "migrate", "rollback", "delete"):
            if k in revision:
                if not all(
                    isinstance(dct, dict)
                    and all(
                        isinstance(stmt_lst, list)
                        and all(isinstance(s, str) for s in stmt_lst)
                        for stmt_lst in dct.values()
                    )
                    for k, dct in revision.items()
                    if k not in ("date", "description")
                ):
                    raise ValueError(
                        f"Invalid structure for revision {j}: Must match "
                        "'dict[str, dict[str, str | list[str]]]'"
                    )

            elif k == "delete" and j == 0:
                raise ValueError(
                    f"Revision dictionary 0 (first revision) must define "
                    "field 'delete'"
                )
            else:
                raise ValueError(
                    f"Revision dictionary {j} does not define required field '{k}'"
                )

    return lst


async def load_databases(
    db_info_data: Sequence[ConfigDatabaseDict],
    raise_exceptions: bool = True,
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
            _logger.error(
                f"Failed to create engine and functioning connection "
                + (f"'{engine.name}+{engine.driver}' " if engine is not None else "")
                + f"for database '{db_name}'",
                exc_info=exc,
            )

            if raise_exceptions:
                raise
        else:
            dbs.append({"name": db_name, "engine": engine, "url": db_info_dict["url"]})

            if "connect_args" in db_info_dict:
                dbs[db_name]["connect_args"] = db_info_data["connect_args"]  # type: ignore

            _logger.info(
                f"Successfully configured engine '{engine.name}+{engine.driver}' "
                f"for database '{db_name}'"
            )

    return dbs


async def unload_databases(
    dbs: Iterable[DatabaseDict],
    raise_exceptions: bool = True,
):
    for db_dict in dbs:
        db_name = db_dict["name"]
        if not isinstance(db_dict["engine"], AsyncEngine):
            raise TypeError(
                "Value for 'engine' must be instance of "
                "'sqlalchemy.ext.asyncio.AsyncEngine' for all dicts in param 'dbs'"
            )

        engine: AsyncEngine = db_dict["engine"]

        try:
            await engine.dispose()
        except sqlalchemy.exc.SQLAlchemyError as err:
            _logger.error(
                f"Failed to dispose connection pool of engine"
                f" '{engine.name}+{engine.driver}' of database '{db_name}'",
                exc_info=err,
            )

            if raise_exceptions:
                raise
        else:
            _logger.info(
                "Successfully disposed connection pool of engine "
                f"'{engine.name}+{engine.driver}' of database '{db_name}'"
            )


async def pgcbots_db_schema_is_defined(db: DatabaseDict) -> bool:  # type: ignore
    engine = db["engine"]
    if engine.name not in ("sqlite", "postgresql"):
        raise RuntimeError(
            f"Unsupported database dialect '{engine.name}' for main database,"
            " must be 'sqlite' or 'postgresql'"
        )

    async with engine.connect() as conn:
        if engine.name == "sqlite":
            return bool(
                (
                    await conn.execute(
                        sqlalchemy.text(
                            "SELECT EXISTS(SELECT 1 FROM sqlite_schema "
                            f"WHERE type == 'table' "
                            "AND name == 'pgcbots_db_schema')"
                        )
                    )
                ).scalar()
            )

        elif engine.name == "postgresql":
            return bool(
                (
                    await conn.execute(
                        sqlalchemy.text(
                            "SELECT EXISTS(SELECT 1 FROM "
                            "information_schema.tables "
                            "WHERE table_name == 'pgcbots_db_schema')"
                        )
                    )
                ).scalar()
            )


async def initialize_pgcbots_db_schema(db: DatabaseDict, config: dict[str, Any]) -> int:
    engine = db["engine"]
    if engine.name not in ("sqlite", "postgresql"):
        raise RuntimeError(
            f"Unsupported database dialect '{engine.name}' for main database,"
            " must be 'sqlite' or 'postgresql'"
        )

    should_migrate = False
    revision_number = -1
    migration_count = 0
    is_initial_migration = False

    if await pgcbots_db_schema_is_defined(db):
        async with engine.connect() as conn:
            result_row = (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT value FROM globals " f"WHERE key == 'revision_number'"
                    )
                )
            ).one_or_none()

            if result_row:
                revision_number = int(result_row.value)

        if revision_number == -1 or (
            revision_number < len(MIGRATIONS) - 1 and config.get("auto_migrate")
        ):
            is_initial_migration = True
            should_migrate = True
    else:
        should_migrate = True

    if should_migrate:
        _logger.info(
            f"Performing "
            + (
                "initial "
                if is_initial_migration
                else "automatic "
                if config.get("auto_migrate")
                else ""
            )
            + "bot database migration..."
        )
        migration_count = await migrate_pgcbots_db_schema(db, 1)

    async with engine.begin() as conn:
        if not (
            await conn.execute(
                sqlalchemy.text("SELECT EXISTS(SELECT 1 FROM bots WHERE uid == :uid)"),
                dict(uid=UID),
            )
        ).scalar():
            await conn.execute(  # register bot application into database
                sqlalchemy.text(f"INSERT INTO bots VALUES (:uid, :name)"),
                dict(uid=UID, name=pcbot.__title__),
            )

    return migration_count


async def get_pgcbots_db_schema_revision_number(db: DatabaseDict) -> int:
    revision_number = -1
    engine = db["engine"]

    conn: AsyncConnection
    async with engine.begin() as conn:
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database, "
                "must be 'sqlite' or 'postgresql'"
            )

        if await pgcbots_db_schema_is_defined(db):
            result_row = (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT value FROM globals WHERE key == 'revision_number'"
                    )
                )
            ).one_or_none()

            if result_row:
                revision_number = int(result_row.value)

    return revision_number


async def migrate_pgcbots_db_schema(
    db: DatabaseDict, steps: int | None = None
) -> int:  #
    old_revision_number = revision_number = -1
    migration_count = 0
    is_initial_migration = False

    engine = db["engine"]

    if steps and steps <= 0:
        raise ValueError("argument 'steps' must be None or > 0")

    _logger.info(
        f"Attempting bot database migration"
        + (f" ({steps} steps)..." if steps else "...")
    )

    conn: AsyncConnection
    async with engine.begin() as conn:
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database, "
                "must be 'sqlite' or 'postgresql'"
            )

        if await pgcbots_db_schema_is_defined(db):
            result_row = (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT value FROM globals WHERE key == 'revision_number'"
                    )
                )
            ).one_or_none()

            if result_row:
                old_revision_number = revision_number = int(result_row.value)

        else:
            is_initial_migration = True

        for revision_number in range(
            old_revision_number + 1,
            (
                len(MIGRATIONS)
                if not steps
                else min(old_revision_number + 1 + steps, len(MIGRATIONS))
            ),
        ):
            for statement in MIGRATIONS[revision_number]["migrate"][engine.name]:
                await conn.execute(sqlalchemy.text(statement))

            migration_count += 1

        # only runs if for-loop above did not run at all
        if revision_number == old_revision_number:
            _logger.info(
                f"Stored revision number {revision_number} already matches the "
                f"latest available revision ({len(MIGRATIONS)-1}). No migration "
                "was performed."
            )
            return migration_count
        elif revision_number == old_revision_number == -1:
            _logger.info(
                f"No revisions available for migration. No migration was performed."
            )
            return migration_count

        _logger.info(
            f"Successfully performed {'initial ' if is_initial_migration else ''}"
            "bot database migration from revision number "
            f"{old_revision_number} to {revision_number}."
        )

        await conn.execute(
            sqlalchemy.text(
                f"INSERT INTO globals "
                f"VALUES ('revision_number', :new_revision_number_str) "
                "ON CONFLICT DO UPDATE SET value = :new_revision_number_str "
                "WHERE key == 'revision_number'"
            ),
            dict(new_revision_number_str=revision_number),
        )

    return migration_count


async def rollback_pgcbots_db_schema(db: DatabaseDict, steps: int) -> int:  #
    old_revision_number = revision_number = -1
    rollback_count = 0

    engine = db["engine"]

    if steps < 0:
        raise ValueError("argument 'steps' must be > 0")

    _logger.info(
        f"Attempting bot database rollback"
        + (f" ({steps} steps)..." if steps != -1 else "...")
    )

    conn: AsyncConnection
    async with engine.begin() as conn:
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database, "
                "must be 'sqlite' or 'postgresql'"
            )

        if await pgcbots_db_schema_is_defined(db):
            result_row = (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT value FROM globals WHERE key == 'revision_number'"
                    )
                )
            ).one_or_none()

            if result_row:
                old_revision_number = revision_number = int(result_row.value)

        else:
            raise RuntimeError(
                "Failed to perform bot database rollback: Database is not configured "
                "or has incorrect schema structure"
            )

        if old_revision_number >= len(MIGRATIONS):
            raise RuntimeError(
                f"Stored revision number {old_revision_number} exceeds "
                f"highest available revision number {len(MIGRATIONS)-1}"
            )
        elif old_revision_number < 0:
            raise RuntimeError(
                f"Stored revision number {old_revision_number} must be >= 0 "
            )
        elif old_revision_number == 0:
            _logger.info(
                f"Stored revision number is already at 0. " "No rollback was performed."
            )
            return rollback_count

        for revision_number in range(
            old_revision_number, max(old_revision_number - steps, -1), -1
        ):
            for statement in MIGRATIONS[revision_number]["rollback"][engine.name]:
                await conn.execute(sqlalchemy.text(statement))

            rollback_count += 1

        revision_number = old_revision_number - steps

        await conn.execute(
            sqlalchemy.text(
                f"INSERT INTO globals "
                f"VALUES ('revision_number', :new_revision_number_str) "
                "ON CONFLICT DO UPDATE SET value = :new_revision_number_str "
                "WHERE key == 'revision_number'"
            ),
            dict(new_revision_number_str=revision_number),
        )

    _logger.info(
        f"Successfully performed "
        "bot database rollback from revision number "
        f"{old_revision_number} to {revision_number}."
    )
    return rollback_count


async def delete_pgcbots_db_schema(db: DatabaseDict):
    engine = db["engine"]
    conn: AsyncConnection
    async with engine.begin() as conn:
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database, "
                "must be 'sqlite' or 'postgresql'"
            )

        for i in range(-1, -len(MIGRATIONS) - 1, -1):
            if "delete" not in MIGRATIONS[i]:
                continue

            for statement in MIGRATIONS[i]["migrate"][engine.name]:
                await conn.execute(sqlalchemy.text(statement))


async def create_extension_data(
    db: DatabaseDict,
    name: str,
    revision_number: int,
    auto_migrate: bool,
    db_prefix: str,
    data: bytes | None = None,
) -> None:
    if not isinstance(name, str):
        raise TypeError(
            f"argument 'name' must be a fully qualified extension "
            "name of type 'str', not "
            f"'{name.__class__.__name__}'"
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
    elif not isinstance(db_prefix, str):
        raise TypeError(
            f"argument 'db_prefix' must be of type 'str', not "
            f"'{db_prefix.__class__.__name__}'"
        )
    elif data is not None and not isinstance(data, bytes):
        raise TypeError(
            f"argument 'data' must be 'None' or of type 'bytes', "
            f"not '{data.__class__.__name__}'"
        )

    engine: AsyncEngine = db["engine"]  # type: ignore
    conn: AsyncConnection

    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO bot_extensions "
                "(name, revision_number, auto_migrate, db_prefix, "
                "data) VALUES (:name, :revision_number, :auto_migrate, "
                ":db_prefix, :data)"
            ),
            dict(
                name=name,
                revision_number=revision_number,
                auto_migrate=auto_migrate,
                db_prefix=db_prefix,
                data=data,
            ),
        )


async def get_extension_data_names(db: DatabaseDict) -> tuple[str, ...]:
    if not await pgcbots_db_schema_is_defined(db):
        return ()

    engine: AsyncEngine = db["engine"]
    conn: AsyncConnection
    async with engine.connect() as conn:
        result: sqlalchemy.engine.Result = await conn.execute(
            sqlalchemy.text(f"SELECT name FROM bot_extensions"),
        )

        rows: Any = result.all()
        return tuple(row.name for row in rows)


async def read_extension_data(
    db: DatabaseDict, name: str, data: bool = True
) -> ExtensionData:
    if not isinstance(name, str):
        raise TypeError(
            f"argument 'name' must be of type 'str', not "
            f"'{name.__class__.__name__}'"
        )

    engine: AsyncEngine = db["engine"]
    conn: AsyncConnection

    columns = "*"

    if not data:
        columns = "name, revision_number, auto_migrate, db_prefix"

    async with engine.connect() as conn:
        result: sqlalchemy.engine.Result = await conn.execute(
            sqlalchemy.text(
                f"SELECT {columns} FROM bot_extensions WHERE name == :name"
            ),
            dict(name=name),
        )

        row: Any = result.first()
        if row is None:
            raise LookupError(
                f"Could not find extension storage data for extension named "
                f"'{name}'"
            )

        return ExtensionData(  # type: ignore
            name=row.name,
            revision_number=row.revision_number,
            auto_migrate=bool(row.auto_migrate),
            db_prefix=row.db_prefix,
        ) | (dict(data=row.data) if data else {})


async def extension_data_exists(db: DatabaseDict, name: str) -> bool:
    if not isinstance(name, str):
        raise TypeError(
            f"argument 'name' must be a fully qualified extension "
            "name of type 'str', not "
            f"'{name.__class__.__name__}'"
        )

    engine: AsyncEngine = db["engine"]
    conn: AsyncConnection

    async with engine.connect() as conn:
        storage_exists = (await pgcbots_db_schema_is_defined(db)) and bool(
            (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT EXISTS(SELECT 1 FROM bot_extensions WHERE name == :name)"
                    ),
                    dict(name=name),
                )
            ).scalar()
        )
    return storage_exists


async def update_extension_data(
    db: DatabaseDict,
    name: str,
    revision_number: int | None = UNSET,
    auto_migrate: bool | None = UNSET,
    db_prefix: str | None = UNSET,
    data: bytes | None = UNSET,
) -> None:
    if not isinstance(name, str):
        raise TypeError(
            f"argument 'name' must be a fully qualified extension "
            "name of type 'str', not "
            f"'{name.__class__.__name__}'"
        )
    elif revision_number is not UNSET and not isinstance(revision_number, int):
        raise TypeError(
            f"argument 'revision_number' must be of type 'int', not "
            f"'{revision_number.__class__.__name__}'"
        )
    elif auto_migrate is not UNSET and not isinstance(auto_migrate, bool):
        raise TypeError(
            f"argument 'auto_migrate' must be of type 'bool', not "
            f"'{auto_migrate.__class__.__name__}'"
        )
    elif db_prefix is not UNSET and not isinstance(db_prefix, str):
        raise TypeError(
            f"argument 'db_prefix' must be of type 'str', not "
            f"'{db_prefix.__class__.__name__}'"
        )
    elif data is not UNSET and not isinstance(data, (bytes, type(None))):
        raise TypeError(
            f"argument 'data' must be 'None' or of type 'bytes', "
            f"not '{data.__class__.__name__}'"
        )

    if all(
        field is UNSET for field in (revision_number, auto_migrate, db_prefix, data)
    ):
        raise TypeError(
            f"arguments 'revision_number', 'auto_migrate', 'db_prefix' "
            "and 'data' cannot all be 'None'"
        )

    engine: AsyncEngine = db["engine"]
    conn: AsyncConnection

    async with engine.begin() as conn:
        if not bool(
            (
                await conn.execute(
                    sqlalchemy.text(
                        "SELECT EXISTS(SELECT 1 FROM bot_extensions WHERE name == :name)"
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
            dict(revision_number=revision_number)
            if revision_number is not UNSET
            else {}
        )
        params |= dict(auto_migrate=auto_migrate) if auto_migrate is not UNSET else {}
        params |= dict(db_prefix=db_prefix) if db_prefix is not UNSET else {}
        params |= dict(data=data) if data is not UNSET else {}

        target_columns = ", ".join((f"{k} = :{k}" for k in params))

        await conn.execute(
            sqlalchemy.text(
                "UPDATE bot_extensions AS be"
                + f" SET {target_columns}"
                + " WHERE be.name == :name",
            ),
            parameters=params,
        )


async def delete_extension_data(db: DatabaseDict, name: str) -> None:
    if not isinstance(name, str):
        raise TypeError(
            f"argument 'name' must be a fully qualified extension "
            "name of type 'str', not "
            f"'{name.__class__.__name__}'"
        )

    engine: AsyncEngine = db["engine"]
    conn: AsyncConnection

    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text("DELETE FROM bot_extensions WHERE name == :name"),
            dict(name=name),
        )


async def message_delete_reaction_listener(
    client: discord.Client | discord.AutoShardedClient,
    message: discord.Message,
    invoker: discord.Member | discord.User,
    emoji: discord.Emoji | discord.PartialEmoji | str,
    role_whitelist: Collection[discord.Role | int] | None = None,
    timeout: float | None = None,
    on_delete: (
        Callable[[discord.Message], Coroutine[Any, Any, Any]]
        | Callable[[discord.Message], Any]
        | None
    ) = None,
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


raise_ = raise_exc

from ..migrations import MIGRATIONS
from . import parsermapping
