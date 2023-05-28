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
from typing import Any, Collection, MutableMapping, Optional

import click
import discord
from discord.ext import commands
import snakecore
from sqlalchemy import text
from sqlalchemy.engine.result import Result
from sqlalchemy.ext.asyncio import AsyncConnection

from pcbot.config_parsing import parse_databases, parser_mapping

from . import constants, utils
from .utils import raise_exc, ParserMapping, ParserMappingValue
from .bot import (
    PygameCommunityBot as Bot,
)
from ._types import Config, DatabaseDict

try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    # uvloop replaces the default Python event loop with a cythonized version.
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


config: dict[str, Any] = constants.DEFAULT_CONFIG.copy() | {"extensions": []}


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


def clear_logging_handlers(logger: logging.Logger | None = None):
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
    config_path: str | None, localconfig_path: str | None, quiet: bool = False
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

                row_dict = row._asdict()
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
                row_dict = row._asdict()
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

                row_dict = row._asdict()
                extname_row_map[ext_name] = row_dict
        else:
            result: Result = await conn.execute(
                text(
                    "SELECT name, last_session_version, revision_number, "
                    "auto_migrate, db_table_prefix FROM bot_extension_data"
                ),
            )
            for row in result.all():
                row_dict = row._asdict()
                extname_row_map[row_dict["name"]] = row_dict

    if not extname_row_map:
        click.secho(f"No extension data could be found.", fg="red")
        raise click.Abort()

    if not quiet:
        click.secho(
            f"\n{len(extname_row_map)} extension data entries found.\n", fg="yellow"
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
@click.option("--config", "config_path", default="./config.py",
    show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'config.py' file to use for configuration. "
    "credentials and launching. Failure will occur silently for an "
    "invalid/non-existing path.")
@click.option("--localconfig", "localconfig_path",
    default="./localconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the optional 'localconfig.py' file to use for locally overriding "
    "'config.py'. Failure will occur silently if this file could cannot be found/read "
    "successfully, except when 'config.py' is not provided, in which case an error "
    "will occur.\nHINT: Setting variables to '...' (Ellipsis) in 'localconfig.py' "
    "will treat them as if they were omitted.")
@click.option("--intents", type=str,
    help=("The integer of bot intents as bitwise flags to be used by the bot instead "
    f"of discord.py's defaults ({bin(constants.DEFAULT_CONFIG['intents'])}). "
    "It can be specified as a base 2, 8, 10 or 16 integer literal. Note that the "
    "message content intent (1 << 15) flag is not set by default. See more at "
    "https://discord.com/developers/docs/topics/gateway#list-of-intents"))
@click.option("--command-prefix", "command_prefix", multiple=True,
    show_default=True, type=str,
    help=("The command prefix(es) to use. "
    f"By default, {constants.DEFAULT_CONFIG['command_prefix']} is used as a prefix."))
@click.option("--mention-as-command-prefix",
    "mention_as_command_prefix", is_flag=True,
    help="Enable the usage of bot mentions as a prefix.")
@click.option("--ignore-ext", "--ignore-extension", "ignore_extension",
    multiple=True, type=str,
    help="The qualified name(s) of the extension(s) to ignore when loading extensions "
    "during startup.")
@click.option("--ignore-all-extensions", "ignore_all_extensions",
    is_flag=True, help="Ignore all extensions at startup.")
@click.option("--ignore-default-extensions",
    "ignore_default_extensions", is_flag=True, help="Ignore default extensions "
    "at startup.")
@click.option("--ignore-extra-extensions",
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
    config_path: str | None,
    localconfig_path: str | None,
    command_prefix: tuple[str, ...],
    mention_as_command_prefix: bool,
    intents: int | None,
    ignore_extension: tuple[str, ...],
    ignore_all_extensions: bool,
    ignore_default_extensions: bool,
    ignore_extra_extensions: bool,
    log_level: str | None,
    quiet: bool,
):
    """Launch this Discord bot application."""

    if ctx.invoked_subcommand is not None:
        return

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        command_prefix=command_prefix,
        mention_as_command_prefix=mention_as_command_prefix,
        intents=intents,
        ignore_extension=ignore_extension,
        ignore_all_extensions=ignore_all_extensions,
        ignore_default_extensions=ignore_default_extensions,
        ignore_extra_extensions=ignore_extra_extensions,
        log_level=log_level,
        quiet=quiet,
    )

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

    try:
        config.update(parser_mapping.parse(config))
    except ParserMapping.ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    if not quiet:
        click.echo("  Finished reading configuration data")

    bot = Bot(
        config["final_prefix"],
        intents=discord.Intents(config["intents"]),  # type: ignore
        strip_after_prefix=True,
        owner_id=config.get("owner_id"),
        owner_ids=config.get("owner_ids"),
        config=config,
    )

    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(log_level=logging.getLevelName(log_level)):
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
    config_path: str | None,
    localconfig_path: str | None,
    extension: tuple[str, ...],
    quiet: bool,
):
    """Show info about all/specific bot extensions with data stored."""
    if ctx.invoked_subcommand is not None:
        return

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {"databases": ParserMappingValue(parse_databases, required=True)}
            ).parse(config)
        )
    except ParserMapping.ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_database_input_data = config["databases"][0]

    async def _run():
        main_database_data = (await utils.load_databases([main_database_input_data]))[0]
        await utils.create_bot_extension_data_table(main_database_data)
        await print_bot_extension_info(main_database_data, extension, quiet)
        await utils.unload_databases([main_database_data])

    asyncio.run(_run())


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
    is_flag=True, help="Supress deletion confirmation messages.")
@click.help_option("-h", "--help", "help")
# fmt: on
def delete(
    config_path: str | None,
    localconfig_path: str | None,
    extension: tuple[str, ...],
    quiet: bool,
    yes: bool,
):
    """Delete the bot extension data of all/specific bot extensions."""
    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {"databases": ParserMappingValue(parse_databases, required=True)}
            ).parse(config)
        )
    except ParserMapping.ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_database_input_data = config["databases"][0]

    async def _run():
        main_database_data = (await utils.load_databases([main_database_input_data]))[0]
        await utils.create_bot_extension_data_table(main_database_data)
        await delete_bot_extension_data(main_database_data, extension, quiet, yes)
        await utils.unload_databases([main_database_data])

    asyncio.run(_run())


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
    is_flag=True, help="Supress deletion confirmation messages.")
@click.help_option("-h", "--help", "help")
# fmt: on
def migratefull(
    config_path: str | None,
    localconfig_path: str | None,
    extension: tuple[str, ...],
    quiet: bool,
    yes: bool,
):
    """Delete the bot extension data of all/specific bot extensions."""
    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {"databases": ParserMappingValue(parse_databases, required=True)}
            ).parse(config)
        )
    except ParserMapping.ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_database_input_data = config["databases"][0]

    async def _run():
        main_database_data = (await utils.load_databases([main_database_input_data]))[0]
        await utils.create_bot_extension_data_table(main_database_data)
        await delete_bot_extension_data(main_database_data, extension, quiet, yes)
        await utils.unload_databases([main_database_data])

    asyncio.run(_run())


if __name__ == "__main__":
    main()
