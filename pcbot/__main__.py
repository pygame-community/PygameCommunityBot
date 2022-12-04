"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file represents the main entry point into the bot application.
"""
import asyncio
import contextlib
from importlib.util import resolve_name
import logging
import logging.handlers
from math import log10
import os
from typing import Any, Optional

import click
import discord
from discord.ext import commands
import snakecore
from sqlalchemy import text
from sqlalchemy.engine.result import Result
from sqlalchemy.ext.asyncio import AsyncConnection

from . import constants, utils
from .bot import (
    PygameCommunityBot as Bot,
)
from ._types import DatabaseDict

try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    # uvloop replaces the default Python event loop with a cythonized version.
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

LOG_LEVEL_NAMES: set[str] = {
    "CRITICAL",
    "FATAL",
    "ERROR",
    "WARN",
    "WARNING",
    "INFO",
    "DEBUG",
    "NOTSET",
}

DEFAULT_EXTENSIONS: list[dict[str, Any]] = [
    # Add extensions here that should always be loaded upon startup.
    # These can only be excluded through the --ignore-ext' or '--disable-all-exts'
    # CLI options.
    {
        "name": f"{__package__}.exts.bot_management",
        "config": {
            "color": constants.DEFAULT_EMBED_COLOR,
        },
    },
    {
        "name": f"{__package__}.exts.docs_pre",
        "config": {"color": constants.DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.help",
        "config": {"color": constants.DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.messaging",
    },
    {
        "name": f"{__package__}.exts.polls_pre",
    },
    {
        "name": f"{__package__}.exts.text_command_manager",
        "config": {"color": constants.DEFAULT_EMBED_COLOR},
    },
]

DEFAULT_CONFIG: dict[str, Any] = {
    "intents": discord.Intents.default().value,
    "command_prefix": "!",
    "mention_as_command_prefix": False,
    "extensions": [],
}

config: dict[str, Any] = DEFAULT_CONFIG.copy() | {"extensions": []}


def setup_logging(log_level) -> None:
    logger = logging.getLogger()
    logger.setLevel(log_level)

    stream_handler = logging.StreamHandler()
    if discord.utils.stream_supports_colour(stream_handler.stream):
        stream_formatter = utils.ANSIColorFormatter()
    else:
        stream_formatter = utils.DefaultFormatter(
            "[{asctime}] [ {levelname:<8} ] {name} -- {message}", style="{"
        )

    if not os.path.exists("logs/"):
        os.mkdir("logs/")

    log_directory = config.get("log_directory", "logs")
    log_filename = config.get("log_filename", "pygamecommunitybot.0")
    log_file_extension = config.get("log_file_extension", ".log")

    rotating_file_handler = utils.CustomRotatingFileHandler(
        f"{log_directory}/{log_filename}",
        extension=log_file_extension,
        maxBytes=8 * 2**20,
        backupCount=10,
    )

    rotating_file_handler.setFormatter(
        utils.DefaultFormatter(
            "[{asctime}] [ {levelname:<8} ] {name} -- {message}", style="{"
        )
    )

    stream_handler.setFormatter(stream_formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(rotating_file_handler)


def clear_logging_handlers(logger: Optional[logging.Logger] = None):
    if logger is None:
        logger = logging.getLogger()

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


@contextlib.contextmanager
def logging_handling(log_level):
    try:
        setup_logging(log_level)
        yield
    finally:
        clear_logging_handlers()


async def start_bot(bot: Bot) -> None:
    try:
        await snakecore.init(global_client=bot)
        print(f"\nStarting bot ({bot.__class__.__name__})...")
        await bot.start(bot._config["authentication"]["token"])
    except KeyboardInterrupt:
        pass
    finally:
        await close_bot(bot)


async def close_bot(bot: Bot) -> None:
    print("\nClosing bot...")
    await bot.close()
    await snakecore.quit()


def load_config_files(
    config_path: Optional[str], localconfig_path: Optional[str], quiet: bool = False
) -> None:

    if not quiet:
        click.echo("Searching for configuration files...")

    config_loading_failed = False

    if config_path:
        # load config data
        try:
            config_module = utils.import_module_from_path("config", config_path)
            try:
                config.update(config_module.config)
            except AttributeError:
                click.secho(
                    "  Could not find 'config' data dictionary in 'config.py' "
                    f"file at path '{config_path}'.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
            else:
                if not quiet:
                    click.secho(
                        f"  Successfully loaded 'config' data from path '{config_path}'"
                    )
        except ImportError:
            if localconfig_path and os.path.exists(localconfig_path):
                click.secho(
                    f"  Could not find 'config.py' file at path '{config_path}', "
                    "looking for 'localconfig.py'...",
                    fg="yellow",
                )
            else:
                click.secho(
                    f"  Could not find 'config.py' file"
                    + (f" at '{config_path}'" if config_path else "")
                    + f" or 'localconfig.py' file at path '{localconfig_path}'",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

            config_loading_failed = True

    if localconfig_path:
        # load optional localconfig data
        try:
            localconfig_module = utils.import_module_from_path(
                "localconfig", localconfig_path
            )
            try:
                config.update(localconfig_module.config)
            except AttributeError:
                click.secho(
                    "  Could not find the 'config' data dictionary in the "
                    f"'localconfig.py' file at path '{localconfig_path}'.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except ImportError:
            if not config_path or config_loading_failed:
                click.secho(
                    f"  Could not find 'config.py' file"
                    + (f" at path '{config_path}'" if config_path else "")
                    + f" or 'localconfig.py' file at path {localconfig_path}",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

            if not quiet:
                click.echo("  No 'localconfig.py' file found, continuing...")
        else:
            if not quiet:
                click.echo(
                    f"  Successfully loaded 'localconfig' from {localconfig_path}"
                )


def parse_config_databases(required: bool = False) -> None:
    if "databases" in config:
        if not (
            config["databases"]
            and isinstance(config["databases"], list)
            and all(
                isinstance(db_info_dict, dict)
                and "name" in db_info_dict
                and isinstance(db_info_dict["name"], str)
                and "url" in db_info_dict
                and isinstance(db_info_dict["url"], str)
                and isinstance(db_info_dict.get("connect_args", {}), dict)
                for db_info_dict in config["databases"]
            )
        ):
            click.secho(
                "  config error: 'databases' variable must be of type "
                "'list' and must contain one or more database "
                "dictionaries.\n"
                "  Each of them must contain at least a 'name' key for the database "
                "name and a 'url' key mapping to an SQLAlchemy-compatible database "
                "URL string, see https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls "
                "for more details.\n"
                "  The 'connect_args' dictionary for setting up a database "
                "connection is driver-specific and optional.\n"
                "  The first database is always the primary one.\n\n"
                "  {\n"
                '      "...": {"...": "..."},\n'
                '      "databases": [\n'
                '          "my_database": {\n'
                '              "name": "my_database",\n'
                '              "url": "engine+driver://url_or_path/to/my_database",\n'
                '              "connect_args": {"...": "..."}\n'
                "          },\n"
                '          {"...": "...", }\n'
                "      ],\n"
                '      "...": "...",\n'
                "  }\n",
                err=True,
                fg="red",
            )
            raise click.Abort()

        if "main_database_name" in config:
            if not isinstance(config["main_database_name"], str):
                click.secho(
                    "  config error: 'main_database_name' variable must be of type "
                    "'str' and must be the name of a database specified in 'databases'",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

            for i in range(len(config["databases"])):
                if config["databases"][i]["name"] == config["main_database_name"]:
                    new_main_database = config["databases"].pop(i)
                    # move selected main db to front
                    config["databases"].insert(0, new_main_database)
                    break
            else:
                click.secho(
                    "  config error: 'main_database_name' variable must be "
                    "the name of a database specified in 'databases'",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

    elif required:
        click.secho(
            "  config error: Required 'databases' variable must be of type "
            "'list' and must contain one or more database "
            "dictionaries.\n"
            "  Each of them must contain at least a 'name' key for the database "
            "name and a 'url' key mapping to an SQLAlchemy-compatible database "
            "URL string, see https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls "
            "for more details.\n"
            "  The 'connect_args' dictionary for setting up a database "
            "connection is driver-specific and optional.\n"
            "  The first database is always the primary one.\n\n"
            "  {\n"
            '      "...": {"...": "..."},\n'
            '      "databases": [\n'
            '          "my_database": {\n'
            '              "name": "my_database",\n'
            '              "url": "engine+driver://url_or_path/to/my_database",\n'
            '              "connect_args": {"...": "..."}\n'
            "          },\n"
            '          {"...": "...", }\n'
            "      ],\n"
            '      "...": "...",\n'
            "  }\n",
            err=True,
            fg="red",
        )
        raise click.Abort()


async def print_bot_extension_info(
    db: DatabaseDict, extensions: tuple[str, ...], quiet: bool = False
):
    engine = db["engine"]
    info: list[dict[str, str]] = []
    max_name_width = 4
    max_last_session_version_width = 20
    max_revision_number_width = 15
    max_auto_migrate_width = 12
    max_db_table_prefix_width = 15

    conn: AsyncConnection
    async with engine.connect() as conn:
        if extensions:
            for ext_name in sorted(set(extensions)):
                result: Result = await conn.execute(
                    text(
                        "SELECT name, last_session_version, revision_number, "
                        "auto_migrate, db_table_prefix FROM bot_extension_data "
                        "WHERE name == :name"
                    ),
                    dict(name=ext_name),
                )

                row = result.one_or_none()
                if not row:
                    click.secho(
                        "No extension data could be found for an extension named "
                        f"'{ext_name}'",
                        fg="red",
                    )
                    raise click.Abort()

                row_dict = dict(row)
                max_name_width = max(max_name_width, len(row_dict["name"]))
                max_last_session_version_width = max(
                    max_last_session_version_width,
                    len(row_dict["last_session_version"]),
                )
                max_revision_number_width = max(
                    max_revision_number_width, len(str(row_dict["revision_number"]))
                )
                max_db_table_prefix_width = max(
                    max_db_table_prefix_width, len(row_dict["db_table_prefix"])
                )
                info.append(row_dict)
        else:
            result: Result = await conn.execute(
                text(
                    "SELECT name, last_session_version, revision_number, "
                    "auto_migrate, db_table_prefix FROM bot_extension_data"
                ),
            )
            for row in result.all():
                row_dict = dict(row)
                max_name_width = max(max_name_width, len(row_dict["name"]))
                max_last_session_version_width = max(
                    max_last_session_version_width,
                    len(row_dict["last_session_version"]),
                )
                max_revision_number_width = max(
                    max_revision_number_width, len(str(row_dict["revision_number"]))
                )
                max_db_table_prefix_width = max(
                    max_db_table_prefix_width, len(row_dict["db_table_prefix"])
                )
                info.append(row_dict)

    if not info:
        click.secho(f"No extension data could be found.", fg="red")
        raise click.Abort()

    if not quiet:
        click.secho(f"\n{len(info)} extension data entries found.\n", fg="yellow")

    click.echo(
        " "
        + "_"
        * (
            max_name_width
            + 3
            + max_last_session_version_width
            + 3
            + max_revision_number_width
            + 3
            + max_auto_migrate_width
            + 3
            + max_db_table_prefix_width
            + 3
            - 1
        )
        + " "
    )
    click.echo(
        "|"
        + f"{'Name': ^{max_name_width+2}}"
        + "|"
        + f"{'Last Session Version': ^{max_last_session_version_width+2}}"
        + "|"
        + f"{'Revision Number': ^{max_revision_number_width+2}}"
        + "|"
        + f"{'Auto Migrate': ^{max_auto_migrate_width+2}}"
        + "|"
        + f"{'DB Table Prefix': ^{max_db_table_prefix_width+2}}"
        + "|"
    )
    click.echo(
        "|"
        + "_" * (max_name_width + 2)
        + "|"
        + "_" * (max_last_session_version_width + 2)
        + "|"
        + "_" * (max_revision_number_width + 2)
        + "|"
        + "_" * (max_auto_migrate_width + 2)
        + "|"
        + "_" * (max_db_table_prefix_width + 2)
        + "|"
    )

    for row_dict in info:
        click.echo(
            f"| {row_dict['name']: <{max_name_width+1}}"
            f"| {row_dict['last_session_version']: <{max_last_session_version_width+1}}"
            f"| {row_dict['revision_number']: <{max_revision_number_width+1}}"
            f"| {str(bool(row_dict['auto_migrate'])): <{max_auto_migrate_width+1}}"
            f"| {row_dict['db_table_prefix']: <{max_db_table_prefix_width+1}}|"
        )

    click.echo(
        "|"
        + "_" * (max_name_width + 2)
        + "|"
        + "_" * (max_last_session_version_width + 2)
        + "|"
        + "_" * (max_revision_number_width + 2)
        + "|"
        + "_" * (max_auto_migrate_width + 2)
        + "|"
        + "_" * (max_db_table_prefix_width + 2)
        + "|"
    )


async def delete_bot_extension_data(
    db: DatabaseDict,
    extensions: tuple[str, ...],
    quiet: bool = False,
    yes: bool = False,
):
    engine = db["engine"]
    extname_row_map: dict[str, dict[str, str]] = {}

    conn: AsyncConnection
    async with engine.connect() as conn:
        if extensions:
            for ext_name in sorted(set(extensions)):
                result: Result = await conn.execute(
                    text(
                        "SELECT name, last_session_version, revision_number, "
                        "auto_migrate, db_table_prefix FROM bot_extension_data "
                        "WHERE name == :name"
                    ),
                    dict(name=ext_name),
                )

                row = result.one_or_none()
                if not row:
                    click.secho(
                        "No extension data could be found for an extension named "
                        f"'{ext_name}'",
                        fg="red",
                    )
                    raise click.Abort()

                row_dict = dict(row)
                extname_row_map[ext_name] = row_dict
        else:
            result: Result = await conn.execute(
                text(
                    "SELECT name, last_session_version, revision_number, "
                    "auto_migrate, db_table_prefix FROM bot_extension_data"
                ),
            )
            for row in result.all():
                row_dict = dict(row)
                extname_row_map[row_dict["name"]] = row_dict

    if not extname_row_map:
        click.secho(f"No extension data could be found.", fg="red")
        raise click.Abort()

    if not quiet:
        click.secho(
            f"\n{len(extname_row_map )} extension data entries found.\n", fg="yellow"
        )

    deletions = 0
    conn: AsyncConnection
    async with engine.begin() as conn:
        for row_dict in extname_row_map.values():
            click.echo(
                "Preparing to delete extension data for extension:\n"
                f"  - Name:                 {row_dict['name']}\n"
                f"  - Last Session Version: {row_dict['last_session_version']}\n"
                f"  - Revision Number: {row_dict['revision_number']}\n"
                f"  - Auto Migrate: {bool(row_dict['auto_migrate'])}\n"
                f"  - DB Table Prefix: '{row_dict['db_table_prefix']}'"
            )
            if not yes:
                confirm = click.confirm(
                    click.style(
                        "This entry and all data associated with it will be deleted."
                        "\nAre you sure you wish to proceed?",
                        fg="yellow",
                        bold=True,
                    )
                )
                if not confirm:
                    continue

            if engine.name == "sqlite":
                result: Result = await conn.execute(
                    text(
                        "SELECT name FROM sqlite_schema "
                        f"WHERE type == 'table' AND name LIKE :db_table_prefix || '%'"
                    ),
                    dict(db_table_prefix=row_dict["db_table_prefix"]),
                )

                table_names = []

                for row in result.all():
                    table_names.append(row.name)  # type: ignore

                for table_name in table_names:
                    await conn.execute(text(f"DELETE FROM '{table_name}'"))
                    await conn.execute(text(f"DROP TABLE '{table_name}'"))

                await conn.execute(
                    text(
                        "DELETE FROM bot_extension_data as bed "
                        "WHERE bed.name == :extension"
                    ),
                    dict(extension=row_dict["name"]),
                )

                if not quiet:
                    click.secho(
                        f"Successfully deleted all stored data of extension {row_dict['name']}",
                        fg="green",
                    )

                deletions += 1

            elif engine.name == "postgresql":
                result: Result = await conn.execute(
                    text(
                        "SELECT tablename AS name FROM pg_tables "
                        "WHERE pg_tables.tableowner == current_user "
                        "AND name LIKE :db_table_prefix || '%'"
                    ),
                    dict(db_table_prefix=row_dict["db_table_prefix"]),
                )

                table_names = []

                for row in result.all():
                    table_names.append(row.name)  # type: ignore

                for table_name in table_names:
                    await conn.execute(text(f"DELETE FROM '{table_name}'"))
                    await conn.execute(text(f"DROP TABLE '{table_name}'"))

                await conn.execute(
                    text(
                        "DELETE FROM bot_extension_data as bed "
                        "WHERE bed.name == :extension"
                    ),
                    dict(extension=row_dict["name"]),
                )

                if not quiet:
                    click.secho(
                        f"Successfully deleted all stored data of extension {row_dict['name']}",
                        fg="green",
                    )

                deletions += 1

    if not (deletions or quiet):
        click.secho(f"No extension data was deleted.", fg="yellow")
        raise click.Abort()


# fmt: off
@click.group(invoke_without_command=True, add_help_option=False)
@click.option("--config", "--config-path", "config_path", default="./config.py",
    show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'config.py' file to use for configuration. "
    "credentials and launching. Failure will occur silently for an "
    "invalid/non-existing path.")
@click.option("--localconfig", "--localconfig-path", "localconfig_path",
    default="./localconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the optional 'localconfig.py' file to use for locally overriding "
    "'config.py'. Failure will occur silently if this file could cannot be found/read "
    "successfully, except when 'config.py' is not provided, in which case an error "
    "will occur.\nHINT: Setting variables to '...' (Ellipsis) in 'localconfig.py' "
    "will treat them as if they were omitted.")
@click.option("--intents", type=str,
    help=("The integer of bot intents as bitwise flags to be used by the bot instead "
    f"of discord.py's defaults ({bin(DEFAULT_CONFIG['intents'])}). "
    "It can be specified as a base 2, 8, 10 or 16 integer literal. Note that the "
    "message content intent (1 << 15) flag is not set by default. See more at "
    "https://discord.com/developers/docs/topics/gateway#list-of-intents"))
@click.option("--command-prefix", "--prefix", "command_prefix", multiple=True,
    show_default=True, type=str,
    help=("The command prefix(es) to use. "
    f"By default, {DEFAULT_CONFIG['command_prefix']} is used as a prefix."))
@click.option("--mention-as-command-prefix", "--mention-as-prefix",
    "mention_as_command_prefix", is_flag=True,
    help="Enable the usage of bot mentions as a prefix.")
@click.option("--ignore-ext", "--ignore-extension", "ignore_extension",
    multiple=True, type=str,
    help="The qualified name(s) of the extension(s) to ignore when loading extensions "
    "during startup.")
@click.option("--ignore-all-exts", "--ignore-all-extensions", "ignore_all_extensions",
    is_flag=True, help="Ignore all extensions at startup.")
@click.option("--ignore-default-exts", "--ignore-default-extensions",
    "ignore_default_extensions", is_flag=True, help="Ignore default extensions "
    "at startup.")
@click.option("--ignore-extra-exts", "--ignore-extra-extensions",
    "ignore_extra_extensions", is_flag=True,
    help="Ignore extra (non-default) extensions at startup.")
@click.option("--log-level", "--bot-log-level", "log_level",
    show_default=True, type=click.Choice(
        ('NOTSET', 'DEBUG', 'INFO', 'WARNING', 'WARN', 'ERROR', 'FATAL', 'CRITICAL'), case_sensitive=False),
    help="The log level to use for the bot's default logging system.")
@click.option("-quiet",
    is_flag=True, help="Supress informational (non-error) output.")
# TODO: Add more CLI options specific to your application.
@click.help_option("-h", "--help", "help")
@click.pass_context
# fmt: on
def main(
    ctx: click.Context,
    config_path: Optional[str],
    localconfig_path: Optional[str],
    command_prefix: tuple[str, ...],
    mention_as_command_prefix: bool,
    intents: Optional[int],
    ignore_extension: tuple[str, ...],
    ignore_all_extensions: bool,
    ignore_default_extensions: bool,
    ignore_extra_extensions: bool,
    log_level: Optional[str],
    quiet: bool,
):
    """Launch this Discord bot application."""

    if ctx.invoked_subcommand is not None:
        return

    load_config_files(config_path, localconfig_path, quiet)

    if not quiet:
        click.echo("Reading configuration data...")
    removed = 0
    for k, v in config.items():
        if v is Ellipsis:
            # automatically delete configuration variables that are Ellipsis objects
            del config[k]
            removed += 1

    if removed and not quiet:
        click.secho(
            f"Removed {removed} configuration variables marked as '...' (Ellipsis).",
            fg="yellow",
        )

    # -------------------------------------------------------------------------
    # config.authentication
    ## config.authentication.token

    if (
        "authentication" not in config or not isinstance(config["authentication"], dict)
    ) or (
        "token" not in config["authentication"]
        or not isinstance(config["authentication"]["token"], str)
    ):
        click.secho(
            "  config error: Required 'authentication' variable must be of type 'dict' "
            "and must at least contain 'token' of type 'str'",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # config.intents

    if intents is not None:
        config["intents"] = intents

    if not isinstance(config["intents"], int):
        intents_fail = False
        if isinstance(config["intents"], str):
            try:
                config["intents"] = int(
                    config["intents"],
                    base=(
                        2
                        if (base_hint := config["intents"][:2]) == "0b"
                        else 8
                        if base_hint == "0o"
                        else 16
                        if base_hint == "0x"
                        else 10
                    ),
                )
            except ValueError:
                intents_fail = True
        else:
            intents_fail = True

        if intents_fail:
            click.secho(
                "  config error: 'intents' variable must be of type 'int' or 'str' (STRING) "
                "and must be interpretable as an integer.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.command_prefix
    # config.mention_as_command_prefix

    final_prefix = None

    if command_prefix:
        config["command_prefix"] = command_prefix

    if (
        config["command_prefix"] is not None
        and not isinstance(config["command_prefix"], (str, list, tuple))
    ) or (
        isinstance(config["command_prefix"], (list, tuple))
        and not all(isinstance(pfx, str) for pfx in config["command_prefix"])
    ):
        click.secho(
            "  config error: Optional 'command_prefix' variable must be of type "
            "'str', of type 'list'/'tuple' containing strings or just None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    if mention_as_command_prefix:
        config["mention_as_command_prefix"] = mention_as_command_prefix

    if not isinstance(config["mention_as_command_prefix"], bool):
        click.secho(
            "  config error: 'mention_as_command_prefix' variable must be of type 'bool'.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    if config["command_prefix"] is not None and config["mention_as_command_prefix"]:
        final_prefix = commands.when_mentioned_or(
            *(
                (config["command_prefix"],)
                if isinstance(config["command_prefix"], str)
                else config["command_prefix"]
            )
        )
    elif config["command_prefix"] is not None:
        final_prefix = config["command_prefix"]
    elif config["mention_as_command_prefix"]:
        final_prefix = commands.when_mentioned
    else:
        click.secho(
            "  config error: 'mention_as_command_prefix' variable must be True if 'command_prefix' is None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # config.extensions

    if not isinstance(config["extensions"], (list, tuple)):
        click.secho(
            "  config error: 'extensions' variable must be a container of type "
            "'list'/'tuple' containing dictionaries that specify "
            "parameters for the extensions to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    elif config["extensions"] and not all(
        isinstance(ext_dict, dict) and "name" in ext_dict
        for ext_dict in config["extensions"]
    ):
        click.secho(
            "  config error: The objects in the 'extensions' variable container "
            "must be of type 'dict' and must at least contain the 'name' key "
            "that maps to the string name of an extension to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # handle extension dicts
    if ignore_all_extensions:
        config["extensions"] = []
    else:
        default_extensions = DEFAULT_EXTENSIONS
        extra_extensions = config["extensions"]
        final_extensions = []

        if not ignore_default_extensions:
            final_extensions.extend(default_extensions)
        if not ignore_extra_extensions:
            final_extensions.extend(extra_extensions)

        if ignore_extension:
            ignore_extension_set = set(ignore_extension)
            final_extensions = [
                ext_dict
                for ext_dict in final_extensions
                if ext_dict["name"] not in ignore_extension_set
            ]
        try:
            config["extensions"] = list(
                {
                    resolve_name(dct["name"], dct["package"])
                    if "package" in dct
                    else dct["name"]: dct
                    for dct in final_extensions
                }.values()
            )  # allow extension dicts to overwrite each other by their qualified name
        except Exception as e:
            click.secho(
                "  config error: Internal error while processing 'extension' "
                f"variable: {e.__class__.__name__}: {e}",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.databases
    # config.main_database_name

    parse_config_databases()

    # -------------------------------------------------------------------------
    # config.log_level

    if "log_level" not in config:  # logging is disabled in the default configuration
        if log_level is not None:
            config["log_level"] = (log_level := log_level.upper())
        else:
            config["log_level"] = None

    elif config["log_level"] is not None and config["log_level"] not in LOG_LEVEL_NAMES:
        click.secho(
            "  config error: 'log_level' variable must be a valid log level name of "
            "type 'str', or None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # config.log_directory

    if "log_directory" in config:
        if not isinstance(config["log_directory"], str) or not os.path.isdir(
            config["log_directory"]
        ):
            click.secho(
                "  config error: 'log_directory' variable must be a valid 'str' path "
                "to a directory.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.log_filename

    if "log_filename" in config:
        if not isinstance(config["log_filename"], str):
            click.secho(
                "  config error: 'log_filename' variable must be a valid file name.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.log_file_extension

    if "log_file_extension" in config:
        if not isinstance(config["log_file_extension"], str) or config[
            "log_file_extension"
        ].startswith("."):
            click.secho(
                "  config error: 'log_file_extension' variable must be a 'str'"
                "representing a file extension (do not prefix it with a '.' symbol).",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.owner_id

    if "owner_id" in config and not isinstance(config["owner_id"], (int, type(None))):
        click.secho(
            "  config error: 'owner_id' variable must be either an 'int' object or 'None'.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # config.owner_ids

    if "owner_ids" in config:
        if "owner_id" in config and config["owner_id"] is not None:
            click.secho(
                "  config error: 'owner_id' and 'owner_ids' variables cannot be "
                "specified together.",
                err=True,
                fg="red",
            )
            raise click.Abort()
        try:
            if not (
                config["owner_ids"]
                and all(isinstance(role_id, int) for role_id in config["owner_ids"])
            ):
                click.secho(
                    "  config error: 'owner_ids' variable must be a container "
                    "(preferably a 'set' object) of 'int's that supports membership testing.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except TypeError:
            click.secho(
                "  config error: 'owner_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.owner_role_ids

    if "owner_role_ids" in config:
        try:
            if not (
                config["owner_role_ids"]
                and all(
                    isinstance(role_id, int) for role_id in config["owner_role_ids"]
                )
            ):
                click.secho(
                    "  config error: 'owner_role_ids' variable must be a container "
                    "(preferably a 'set' object) of 'int's that supports membership testing.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except TypeError:
            click.secho(
                "  config error: 'owner_role_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # config.manager_role_ids

    if "manager_role_ids" in config:
        try:
            if not all(
                isinstance(role_id, int) for role_id in config["manager_role_ids"]
            ):
                click.secho(
                    "  config error: 'manager_role_ids' variable must be a container "
                    "(preferably a 'set' object) of 'int's that supports membership testing.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except TypeError:
            click.secho(
                "  config error: 'manager_role_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more config variables as desired

    if not quiet:
        click.echo("  Finished reading configuration data")

    bot = Bot(
        final_prefix,
        intents=discord.Intents(config["intents"]),  # type: ignore
        strip_after_prefix=True,
        owner_id=config.get("owner_id"),
        owner_ids=config.get("owner_ids", set()),
        config=config,
    )

    if (
        config["log_level"] is not None
    ):  #  not specifying a logging level disables logging
        with logging_handling(log_level=logging.getLevelName(config["log_level"])):
            asyncio.run(start_bot(bot))
            return

    asyncio.run(start_bot(bot))


# fmt: off
@main.group(invoke_without_command=True)
@click.option("--config", "--config-path", "config_path", default="./config.py",
    show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'config.py' file to use for configuration. "
    "credentials and launching. Failure will occur silently for an "
    "invalid/non-existing path.")
@click.option("--localconfig", "--localconfig-path", "localconfig_path",
    default="./localconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the optional 'localconfig.py' file to use for locally overriding "
    "'config.py'. Failure will occur silently if this file could cannot be found/read "
    "successfully, except when 'config.py' is not provided, in which case an error "
    "will occur.")
@click.option("--ext", "--extension", "extension",  multiple=True, help="The qualified name of an extension.")
@click.option("-q", "--quiet",
    is_flag=True, help="Supress informational (non-error) output.")
@click.help_option("-h", "--help", "help")
@click.pass_context
# fmt: on
def extdata(
    ctx: click.Context,
    config_path: Optional[str],
    localconfig_path: Optional[str],
    extension: tuple[str, ...],
    quiet: bool,
):
    """Show info about all/specific bot extensions with data stored."""
    if ctx.invoked_subcommand is not None:
        return

    load_config_files(config_path, localconfig_path, quiet)
    parse_config_databases(required=True)

    main_database_input_data = config["databases"][0]

    loop = asyncio.get_event_loop()

    main_database_data = loop.run_until_complete(
        utils.load_databases([main_database_input_data])
    )[0]
    loop.run_until_complete(utils.create_bot_extension_data_table(main_database_data))
    loop.run_until_complete(
        print_bot_extension_info(main_database_data, extension, quiet)
    )
    loop.run_until_complete(utils.unload_databases([main_database_data]))


# fmt: off
@extdata.command()
@click.option("--config", "--config-path", "config_path", default="./config.py",
    show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'config.py' file to use for configuration. "
    "credentials and launching. Failure will occur silently for an "
    "invalid/non-existing path.")
@click.option("--localconfig", "--localconfig-path", "localconfig_path",
    default="./localconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the optional 'localconfig.py' file to use for locally overriding "
    "'config.py'. Failure will occur silently if this file could cannot be found/read "
    "successfully, except when 'config.py' is not provided, in which case an error "
    "will occur.")
@click.option("--ext", "--extension", "extension",  multiple=True, help="The qualified name of an extension.")
@click.option("-q", "--quiet",
    is_flag=True, help="Supress informational (non-error) output.")
@click.option("-y", "--yes",
    is_flag=True, help="Supress deletetion confirmation messages.")
@click.help_option("-h", "--help", "help")
# fmt: on
def delete(
    config_path: Optional[str],
    localconfig_path: Optional[str],
    extension: tuple[str, ...],
    quiet: bool,
    yes: bool,
):
    """Delete the bot extension data of all/specific bot extensions."""
    load_config_files(config_path, localconfig_path, quiet)
    parse_config_databases(required=True)

    main_database_input_data = config["databases"][0]

    loop = asyncio.get_event_loop()

    main_database_data = loop.run_until_complete(
        utils.load_databases([main_database_input_data])
    )[0]
    loop.run_until_complete(utils.create_bot_extension_data_table(main_database_data))
    loop.run_until_complete(
        delete_bot_extension_data(main_database_data, extension, quiet, yes)
    )
    loop.run_until_complete(utils.unload_databases([main_database_data]))


if __name__ == "__main__":
    main()
