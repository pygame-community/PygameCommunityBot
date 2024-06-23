"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file represents the main entry point into the bot application.
"""
import asyncio
import contextlib
import logging
import logging.handlers
import os
from typing import Any

import click
import discord
from pcbot.utils.parsermapping import PMValue, ParserMapping, ParsingError
import snakecore
import sqlalchemy.exc

from pcbot.config_parsing import (
    parse_databases,
    parse_extensions,
    parse_main_database_name,
    parser_mapping,
)

from . import cli_helpers, constants
from .utils import raise_
from .bot import (
    PygameCommunityBot as Bot,
)
from .migrations import MIGRATIONS
from pcbot import utils

try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    # uvloop replaces the default Python event loop with a cythonized version.
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


config: dict[str, Any] = constants.DEFAULT_CONFIG.copy() | {"extensions": []}
logging_is_setup = False


def setup_logging(log_level, stdout: bool = True) -> None:
    global logging_is_setup

    logger = logging.getLogger()
    logger.setLevel(log_level)

    if stdout:
        stream_handler = logging.StreamHandler()
        if discord.utils.stream_supports_colour(stream_handler.stream):
            stream_formatter = utils.ANSIColorFormatter()
        else:
            stream_formatter = utils.DefaultFormatter(
                "[{asctime}] [ {levelname:<8} ] {name} -- {message}", style="{"
            )
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)

    if not os.path.exists("logs/"):
        os.mkdir("logs/")

    log_directory = config.get("log_directory", "logs")
    log_filename = config.get("log_filename", "pygamecommunitybot.0")
    log_file_extension = config.get("log_file_extension", ".log")

    rotating_file_handler = utils.RotatingFileHandler(
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

    logger.addHandler(rotating_file_handler)

    logging_is_setup = True


def clear_logging_handlers(logger: logging.Logger | None = None):
    global logging_is_setup

    if logger is None:
        logger = logging.getLogger()

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    logging_is_setup = False


@contextlib.contextmanager
def logging_handling(log_level, stdout: bool = True):
    try:
        setup_logging(log_level, stdout)
        yield
    finally:
        clear_logging_handlers()


async def run_bot(bot: Bot) -> None:
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


_shared_options_map = dict(
    config_path=click.option(
        "--config",
        "config_path",
        default="./config.py",
        show_default=True,
        type=click.Path(resolve_path=True),
        help="A path to the 'config.py' file to use for configuration, "
        "credentials and launching. Failure will occur silently for an "
        "invalid/non-existing path.",
    ),
    localconfig_path=click.option(
        "--localconfig",
        "localconfig_path",
        default="./localconfig.py",
        show_default=True,
        type=click.Path(resolve_path=True),
        help="A path to the optional 'localconfig.py' file to use for locally overriding "
        "'config.py'. Failure will occur silently if this file could cannot be "
        "found/read successfully, except when 'config.py' is not provided, in which case "
        "an error will occur.",
    ),
    log_level=click.option(
        "--log-level",
        "log_level",
        show_default=True,
        type=click.Choice(
            (
                "NOTSET",
                "DEBUG",
                "INFO",
                "WARNING",
                "WARN",
                "ERROR",
                "FATAL",
                "CRITICAL",
            ),
            case_sensitive=False,
        ),
    ),
    ignore_failures=click.option(
        "--ignore-failures",
        "ignore_failures",
        is_flag=True,
        help="Ignore failed attempts.",
    ),
    quiet=click.option(
        "-q",
        "--quiet",
        "quiet",
        is_flag=True,
        help="Supress informational (non-error) output to the console.",
    ),
    yes=click.option(
        "-y", "--yes", "yes", is_flag=True, help="Supress confirmation messages."
    ),
    help=click.help_option("-h", "--help", "help"),
)


def shared_options(*option_names: str):
    def _shared_options(func):
        for option_name in reversed(option_names):
            func = _shared_options_map[option_name](func)

        return func

    return _shared_options


# fmt: off
@click.group(invoke_without_command=True, add_help_option=False)
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
@click.option("-i", "--ignore-extension", "ignore_extension",
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
@shared_options("config_path", "localconfig_path", "log_level", "quiet", "help")
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
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

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
    except ParsingError as p:
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

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(log_level), stdout=not quiet
        ):
            asyncio.run(run_bot(bot))
            return

    asyncio.run(run_bot(bot))


# fmt: off
@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("specifier", nargs=1)
@shared_options("config_path", "localconfig_path", "log_level", "quiet", "yes", "help")
# fmt: on
def migrate(
    specifier: str,
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    quiet: bool,
    yes: bool,
):
    """Perform a full bot database migration/rollback. Does not affect bot extensions."""

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

    if not (
        (specifier.isnumeric())
        or specifier == "+"
        or (
            specifier.startswith(("+", "-"))
            and specifier[1:].isnumeric()
            and int(specifier[1:])
        )
    ):
        click.secho(
            f"Argument 'specifier' must match '+', 'n', '+r' or '-r', where 'n' and "
            "'r' are positive integers and 'r' is nonzero.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {
                    "databases": PMValue(parse_databases, required=True),
                    "main_database_name": parse_main_database_name,
                }
            ).parse(config)
        )
    except ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_db_info_dict = None
    for db_info_dict in config["databases"]:
        if (
            "main_database_name" in config
            and db_info_dict["name"] == config["main_database_name"]
        ):
            main_db_info_dict = db_info_dict
            break
    else:
        main_db_info_dict = config["databases"][0]

    async def _run():
        try:
            db, *_ = await utils.load_databases([main_db_info_dict])
            await cli_helpers.migrate(db, specifier, config, quiet, yes)
            await utils.unload_databases([db])
        except click.Abort:
            raise
        except Exception as exc:
            click.secho(
                f"Bot database migration/rollback failed due to an error: "
                f"{exc.__class__.__name__}: {exc.args[0]}",
                fg="red",
            )
            if logging_is_setup:
                logging.getLogger().error(
                    "Bot database migration/rollback failed due to an error",
                    exc_info=exc,
                )
            raise click.Abort()

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(log_level), stdout=not quiet
        ):
            asyncio.run(_run())
    else:
        asyncio.run(_run())


# fmt: off
@click.option("-b", "--bot", "bot", multiple=True,
              help="The unique identifier of the bot whose information should be "
              "deleted.")
@shared_options("config_path", "localconfig_path", "log_level", "quiet", "yes", "help")
# fmt: on
def delete(
    bot: tuple[str, ...],
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    quiet: bool,
    yes: bool,
):
    raise click.Abort()


# fmt: off
@main.group(invoke_without_command=True)
@shared_options("help")
@click.pass_context
def extensions(ctx: click.Context):
    """Manage bot extensions and their data."""

    if ctx.invoked_subcommand is None:
        raise click.Abort()

# fmt: off
@extensions.command("info")
@click.argument("extensions",  nargs=-1)
@shared_options("config_path", "localconfig_path", "log_level", "ignore_failures",
                "quiet", "help")
@click.pass_context
# fmt: on
def extensions_info(
    ctx: click.Context,
    extensions: tuple[str, ...],
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    ignore_failures: bool,
    quiet: bool,
):
    """Show info about all/specific bot extensions with data stored."""

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {
                    "databases": PMValue(parse_databases, required=True),
                    "main_database_name": parse_main_database_name,
                }
            ).parse(config)
        )
    except ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_db_info_dict = None
    for db_info_dict in config["databases"]:
        if (
            "main_database_name" in config
            and db_info_dict["name"] == config["main_database_name"]
        ):
            main_db_info_dict = db_info_dict
            break
    else:
        main_db_info_dict = config["databases"][0]

    async def _run():
        try:
            main_db_dict = (await utils.load_databases([main_db_info_dict]))[0]
        except sqlalchemy.exc.SQLAlchemyError as error:
            click.secho(
                f"An error occured while establishing connection to main database: "
                f"{error.__class__.__name__}: {error}",
                fg="red",
            )
            raise click.Abort()

        engine = main_db_dict["engine"]
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database,"
                " must be 'sqlite' or 'postgresql'"
            )

        await utils.initialize_pgcbots_db_schema(main_db_dict, config)
        await cli_helpers.extract_bot_extension_info(
            main_db_dict, extensions, ignore_failures, quiet
        )
        await utils.unload_databases([main_db_dict])

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(log_level), stdout=not quiet
        ):
            asyncio.run(_run())
    else:
        asyncio.run(_run())


# fmt: off
@extensions.command("delete")
@click.argument("extensions",  nargs=-1)
@click.option("-b", "--bot", "bot", multiple=True, help="The unique identifier of a "
              "bot application whose extension-specific data should be deleted alone.")
@click.option("-a", "--all", "all_extensions", is_flag=True,
              help="Whether to delete the data of all bot extensions. This overrides "
              "the 'extensions' arguments.")
@click.option("-l", "--local", "local_extensions", is_flag=True, help="Whether to "
              "delete the data of all locally available bot extensions. This "
              "overrides the 'extensions' arguments.")
@shared_options("config_path", "localconfig_path", "log_level", "ignore_failures",
                "quiet", "yes", "help")
# fmt: on
def extensions_delete(
    extensions: tuple[str, ...],
    bot: tuple[str, ...],
    all_extensions: bool,
    local_extensions: bool,
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    ignore_failures: bool,
    quiet: bool,
    yes: bool,
):
    """Delete the bot extension data of the specified (or all if omitted) bot extensions."""

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

    bots = bot

    if all_extensions and local_extensions:
        click.secho(
            "Flags -a/--all and -l/--local are mutually exclusive.", err=True, fg="red"
        )
        raise click.Abort()

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {
                    "databases": PMValue(parse_databases, required=True),
                    "main_database_name": parse_main_database_name,
                    "extensions": parse_extensions,
                }
            ).parse(config)
        )
    except ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_db_info_dict = None
    for db_info_dict in config["databases"]:
        if (
            "main_database_name" in config
            and db_info_dict["name"] == config["main_database_name"]
        ):
            main_db_info_dict = db_info_dict
            break
    else:
        main_db_info_dict = config["databases"][0]

    async def _run():
        nonlocal extensions
        try:
            main_db_dict = (await utils.load_databases([main_db_info_dict]))[0]
        except sqlalchemy.exc.SQLAlchemyError as error:
            click.secho(
                f"An error occured while establishing connection to main database: "
                f"{error.__class__.__name__}: {error}",
                fg="red",
            )
            click.Abort()
            return

        engine = main_db_dict["engine"]
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database,"
                " must be 'sqlite' or 'postgresql'"
            )

        if all_extensions:
            extensions = ()

        elif local_extensions:
            extensions = (
                *(ext_dict["name"] for ext_dict in config["extensions"]),
                *extensions,
            )
        elif not extensions:
            click.secho(f"No bot extensions specified.", err=True, fg="red")
            raise click.Abort()

        await utils.initialize_pgcbots_db_schema(main_db_dict, config)
        await cli_helpers.delete_bot_extensions(
            main_db_dict, extensions, bots, all_extensions, ignore_failures, quiet, yes  # type: ignore
        )
        await utils.unload_databases([main_db_dict])

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(log_level), stdout=not quiet
        ):
            asyncio.run(_run())
    else:
        asyncio.run(_run())


# fmt: off
@extensions.command("migrate", context_settings={"ignore_unknown_options": True})
@click.option("-o", "--option", "option", multiple=True, type=(str, str),
              help="A bot extension migration option, consisting of a extension name "
              "and a migration/rollback specifier, where the latter must match '+' "
              "(migrate to latest revision), 'n' (migrate/rollback to revision 'n'), "
              "'+r' (migrate by '+r') or '-r' (migrate by '-r' (rollback)), where 'n' "
              "and 'r' are positive integers and 'r' is nonzero.")
@click.option("-a", "--all-option", "all_option", help="The migration/rollback "
              "specifier to use for all bot extensions, which must "
              "match '+' (migrate to latest revision), 'n' (migrate/rollback to "
              "revision 'n'), '+r' (migrate by '+r') or '-r' (migrate by '-r' "
              "(rollback)), where 'n' and 'r' are positive integers and 'r' is "
              "nonzero.")
@click.option("-l", "--local-option", "local_option", help="The migration/rollback "
              "specifier to use for all locally available bot extensions, which must "
              "match '+' (migrate to latest revision), 'n' (migrate/rollback to "
              "revision 'n'), '+r' (migrate by '+r') or '-r' (migrate by '-r' "
              "(rollback)), where 'n' and 'r' are positive integers and 'r' is "
              "nonzero.")
@shared_options("config_path", "localconfig_path", "log_level", "ignore_failures", 
                "quiet", "yes", "help")
# fmt: on
def extensions_migrate(
    option: tuple[tuple[str, str], ...],
    all_option: str | None,
    local_option: str | None,
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    ignore_failures: bool,
    quiet: bool,
    yes: bool,
):
    """Perform a full database migration for the specified bot extensions.
    If omitted, all extensions will be migrated.
    """

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

    if not (option or all_option or local_option):
        click.secho(
            f"Flags '--option', '--all-option' and '--local-option' cannot all be empty/omitted.",
            err=True,
            fg="red",
        )
        raise click.Abort()
    elif all_option and local_option:
        click.secho(
            "Flags -a/--all-option and -l/--local-option are mutually exclusive.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    if not all(
        sp is None
        or (
            (sp.isnumeric())
            or sp == "+"
            or (sp.startswith(("+", "-")) and sp[1:].isnumeric())
        )
        for sp in (all_option, local_option)
    ):
        click.secho(
            f"A migration/rollback specifier must match '+', 'n', '+r' or '-r', "
            "where 'n' and 'r' are positive integers and 'r' is nonzero.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    options = option

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {
                    "databases": PMValue(parse_databases, required=True),
                    "main_database_name": parse_main_database_name,
                    "extensions": parse_extensions,
                }
            ).parse(config)
        )
    except ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    if local_option:
        options = (
            *options,
            *(
                (ext_dict["name"], local_option)
                for ext_dict in config.get("extensions", ())
            ),
        )

    if not all(
        (sp.isnumeric())
        or sp == "+"
        or (sp.startswith(("+", "-")) and sp[1:].isnumeric())
        for _, sp in options
    ):
        click.secho(
            f"A migration/rollback specifier must match '+', 'n', '+r' or '-r', "
            "where 'n' and 'r' are positive integers and 'r' is nonzero.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    bot = Bot(
        config["final_prefix"],
        intents=discord.Intents(config["intents"]),  # type: ignore
        strip_after_prefix=True,
        owner_id=config.get("owner_id"),
        owner_ids=config.get("owner_ids"),
        config=config,
    )

    main_db_info_dict = None
    for db_info_dict in config["databases"]:
        if (
            "main_database_name" in config
            and db_info_dict["name"] == config["main_database_name"]
        ):
            main_db_info_dict = db_info_dict
            break
    else:
        main_db_info_dict = config["databases"][0]

    async def _run():
        nonlocal options
        try:
            main_db_dict = (await utils.load_databases([main_db_info_dict]))[0]
        except sqlalchemy.exc.SQLAlchemyError as error:
            click.secho(
                f"An error occured while establishing connection to main database: "
                f"{error.__class__.__name__}: {error}",
                fg="red",
            )
            raise click.Abort()

        engine = main_db_dict["engine"]
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database,"
                " must be 'sqlite' or 'postgresql'"
            )

        bot._main_database = main_db_dict

        if all_option:
            options = tuple(
                (name, all_option)
                for name in await utils.get_extension_data_names(main_db_dict)
            )

        await utils.initialize_pgcbots_db_schema(main_db_dict, config)
        successes = await cli_helpers.migrate_bot_extensions(
            bot, options, ignore_failures, quiet, yes
        )
        if not quiet:
            click.secho(
                f"\n{successes} bot extension database "
                "object migrations/rollbacks performed.",
                fg="green" if successes else "red",
            )
        await utils.unload_databases([main_db_dict])

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(log_level=logging.getLevelName(log_level)):
            asyncio.run(_run())
    else:
        asyncio.run(_run())


# fmt: off
@extensions.command("set")
@click.argument("extensions",  nargs=-1)
@click.option("-a", "--all", "all_extensions", is_flag=True, default=False,
              help="Apply the specified changes to all available bot extensions.")
@click.option("-l", "--local", "local_extensions", is_flag=True, default=False,
              help="Only apply the specified changes to locally available bot extensions.")
@click.option("-p", "--pragma", "pragma", type=(str, str), help="A pragma variable to set.", multiple=True)
@shared_options("config_path", "localconfig_path", "log_level", "ignore_failures", 
                "quiet", "help")
# fmt: on
def extensions_set(
    extensions: tuple[str, ...],
    all_extensions: bool,
    local_extensions: bool,
    pragma: tuple[tuple[str, str], ...],
    config_path: str | None,
    localconfig_path: str | None,
    log_level: str | None,
    ignore_failures: bool,
    quiet: bool,
):
    """Set bot extension runtime variables.
    These variables are stored on a per-extension basis in the primary database.

    Available pragma variables:
        - auto_migrate: boolean
            Whether to enable automatic migration of bot extension database objects (at runtime, upon being loaded).
    """

    config["_cli_args"] = dict(
        config_path=config_path,
        localconfig_path=localconfig_path,
        quiet=quiet,
    ) | (dict(log_level=log_level) if log_level else {})

    if all_extensions and local_extensions:
        click.secho(
            "Flags -a/--all and -l/--local are mutually exclusive.", err=True, fg="red"
        )
        raise click.Abort()

    pragmas = pragma

    if not pragmas:
        click.secho(
            f"No variables specified.",
            fg="red",
        )
        raise click.Abort()

    pragma_input_map = dict(pragmas)

    try:
        parsed_pragmas = ParserMapping(
            dict(
                auto_migrate=lambda key, auto_migrate, cfg: True
                if auto_migrate.lower() in ("t", "true", "y", "yes", "1")
                else False
                if auto_migrate.lower() in ("f", "false", "n", "no", "0")
                else raise_(
                    ParsingError(
                        "Pragma variable 'auto_migrate' must be set to a boolean value."
                    )
                ),
            ),
            reject_unknown=True,
        ).parse(pragma_input_map)

    except ParsingError as p:
        click.secho(f"Pragma parsing error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    load_config_files(config_path, localconfig_path, quiet)

    try:
        config.update(
            ParserMapping(
                {
                    "databases": PMValue(parse_databases, required=True),
                    "main_database_name": parse_main_database_name,
                    "extensions": parse_extensions,
                }
            ).parse(config)
        )
    except ParsingError as p:
        click.secho(f"  config error: {p.args[0]}", err=True, fg="red")
        raise click.Abort()

    main_db_info_dict = None
    for db_info_dict in config["databases"]:
        if (
            "main_database_name" in config
            and db_info_dict["name"] == config["main_database_name"]
        ):
            main_db_info_dict = db_info_dict
            break
    else:
        main_db_info_dict = config["databases"][0]

    async def _run():
        nonlocal extensions
        try:
            main_db_dict = (await utils.load_databases([main_db_info_dict]))[0]
        except sqlalchemy.exc.SQLAlchemyError as error:
            click.secho(
                f"An error occured while establishing connection to main database: "
                f"{error.__class__.__name__}: {error}",
                fg="red",
            )
            raise click.Abort()

        engine = main_db_dict["engine"]
        if engine.name not in ("sqlite", "postgresql"):
            raise RuntimeError(
                f"Unsupported database dialect '{engine.name}' for main database,"
                " must be 'sqlite' or 'postgresql'"
            )

        if all_extensions:
            extensions = await utils.get_extension_data_names(main_db_dict)
            if not extensions:
                click.secho(
                    f"No bot extension data could be found in the main database.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

        elif local_extensions:
            extensions = (
                *(ext_dict["name"] for ext_dict in config["extensions"]),
                *extensions,
            )
        elif not extensions:
            click.secho(f"No bot extensions specified.", err=True, fg="red")
            raise click.Abort()

        for extension_name in extensions:
            if not await utils.extension_data_exists(main_db_dict, extension_name):
                if not quiet:
                    click.secho(
                        f"No bot extension data could be found for '{extension_name}'",
                        fg="red",
                    )
                if ignore_failures:
                    continue

                raise click.Abort()

            await utils.update_extension_data(
                main_db_dict, extension_name, **parsed_pragmas
            )
            if not quiet:
                for varname in parsed_pragmas:
                    click.secho(
                        f"Updated pragma variable '{varname}' to "
                        f"'{parsed_pragmas[varname]}' for bot extension "
                        f"'{extension_name}'.",
                        fg="green",
                    )

        await utils.unload_databases([main_db_dict])

    log_level = log_level or config.get("log_level")
    if log_level is not None:  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(log_level), stdout=not quiet
        ):
            asyncio.run(_run())
            return

    asyncio.run(_run())


if __name__ == "__main__":
    main()
