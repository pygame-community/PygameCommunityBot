"""This file represents the main entry point into the bot application.
"""
import asyncio
import contextlib
import copy
import logging
from typing import Any, Optional, Union

import click
import discord
from discord.ext import commands
import snakecore

from . import utils
from .bot import (
    PygameBot as Bot,
)
from .exts.custom_help import CustomHelpCommand

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
    {"name": f"{__package__}.exts.debug_info"},
    #   {"name": f"{__package__}.exts.custom_help_old"},
    #   {"name": f"{__package__}.exts.custom_help"},
]


DEFAULT_BOTCONFIG: dict = {"intents": discord.Intents.default().value}
DEFAULT_LAUNCHCONFIG: dict = {
    "command_prefix": "!",
    "mention_as_command_prefix": False,
    "extensions": [],
}

botconfig: dict = copy.deepcopy(DEFAULT_BOTCONFIG)
launchconfig: dict = copy.deepcopy(DEFAULT_LAUNCHCONFIG)


def setup_logging(log_level: int = logging.INFO) -> None:
    discord.utils.setup_logging(level=log_level)


def clear_logging_handlers(logger: Optional[logging.Logger] = None):
    if logger is None:
        logger = logging.getLogger()

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


@contextlib.contextmanager
def logging_handling(log_level: int = logging.INFO):
    try:
        setup_logging(log_level=log_level)
        yield
    finally:
        clear_logging_handlers()


async def start_bot(bot: Bot) -> None:
    try:
        await snakecore.init(
            global_client=bot
        )  # TODO: Remove this if not using snakecore
        print(f"\nStarting bot ({bot.__class__.__name__})...")
        await bot.start(bot._botconfig["authentication"]["token"])
    except KeyboardInterrupt:
        pass
    finally:
        await close_bot(bot)


async def close_bot(bot: Bot) -> None:
    print("Closing bot...")
    await bot.close()
    await snakecore.quit()  # TODO: Remove this if not using snakecore


# fmt: off
@click.group(invoke_without_command=True, add_help_option=False)
@click.option("--config", "--config-path", "config_path", default="./config.py",
    show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'config.py' file to use for both configuring bot "
    "credentials and launching. This is resolved before '--botconfig-path' and "
    "'--launchconfig-path'. Failure will occur silently for an "
    "invalid/non-existing path.")
@click.option("--botconfig", "--botconfig-path", "botconfig_path",
    default="./botconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'botconfig.py' file to use for configuring bot credentials.")
@click.option("--launchconfig", "--launchconfig-path", "launchconfig_path",
    default="./launchconfig.py", show_default=True, type=click.Path(resolve_path=True),
    help="A path to the 'launchconfig.py' file to use for configuring bot launching.")
@click.option("--intents", type=str,
    help=("The integer of bot intents as bitwise flags to be used by the bot instead "
    f"of discord.py's defaults ({bin(DEFAULT_BOTCONFIG['intents'])}). "
    "It can be specified as a base 2, 8, 10 or 16 integer literal. Note that the "
    "message content intent (1 << 15) flag is not set by default. See more at "
    "https://discord.com/developers/docs/topics/gateway#list-of-intents"))
@click.option("--command-prefix", "--prefix", "command_prefix", multiple=True,
    show_default=True, type=str,
    help=("The command prefix(es) to use. "
    f"By default, {DEFAULT_LAUNCHCONFIG['command_prefix']} is used as a prefix."))
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
# TODO: Add more CLI options specific to your application.
@click.help_option("-h", "--help", "help")
@click.pass_context
# fmt: on
def main(
    ctx: click.Context,
    config_path: str,
    botconfig_path: str,
    launchconfig_path: str,
    command_prefix: tuple[str, ...],
    mention_as_command_prefix: bool,
    intents: Optional[int],
    ignore_extension: tuple[str, ...],
    ignore_all_extensions: bool,
    ignore_default_extensions: bool,
    ignore_extra_extensions: bool,
    log_level: Optional[str],
):
    """Launch this Discord bot application."""

    if ctx.invoked_subcommand is not None:
        return

    click.echo("Searching for configuration files...")
    config_loading_failed = False

    if config_path is not None:
        # load mandatory botconfig data and optional launchconfig data
        try:
            config_module = utils.import_module_from_path("config", config_path)
            try:
                botconfig.update(config_module.botconfig)
            except AttributeError:
                click.secho(
                    "  Could not find the 'botconfig' dictionary in the 'botconfig.py' "
                    f"file at '{botconfig_path}'.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
            else:
                click.secho(f"  Successfully loaded 'botconfig' from {config_path}")

            try:
                launchconfig.update(config_module.launchconfig)
            except AttributeError:
                click.echo(
                    "  No 'launchconfig' dictionary found in 'config.py', using "
                    "launch configuration defaults instead..."
                )
            else:
                click.echo(f"  Successfully loaded 'launchconfig' from {config_path}")
        except ImportError:
            config_loading_failed = True

    if config_path is None or config_loading_failed:
        # load mandatory botconfig data
        try:
            botconfig_module = utils.import_module_from_path(
                "botconfig", botconfig_path
            )
            try:
                botconfig.update(botconfig_module.botconfig)
            except AttributeError:
                click.secho(
                    "  Could not find the 'botconfig' dictionary in the 'botconfig.py' "
                    f"file at '{botconfig_path}'.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except ImportError:
            click.secho(f"  Could not find a 'botconfig.py' file.", err=True, fg="red")
            raise click.Abort()
        else:
            click.echo(f"  Successfully loaded 'botconfig' from {botconfig_path}")

        # load optional launchconfig data
        try:
            launchconfig_module = utils.import_module_from_path(
                "launchconfig", launchconfig_path
            )
            try:
                launchconfig.update(launchconfig_module.launchconfig)
            except AttributeError:
                click.secho(
                    "  Could not find the 'launchconfig' dictionary in the "
                    f"'launchconfig.py' file at '{launchconfig_path}'.",
                    err=True,
                    fg="red",
                )
                raise click.Abort()
        except ImportError:
            click.echo(
                "  No 'launchconfig.py' file found, using "
                "launch configuration defaults instead..."
            )
        else:
            click.echo(f"  Successfully loaded 'launchconfig' from {launchconfig_path}")

    click.echo("\nReading configuration data...")

    # -------------------------------------------------------------------------
    # botconfig.authentication
    ## botconfig.authentication.client_id
    ## botconfig.authentication.token

    if (
        (
            "authentication" not in botconfig
            or not isinstance(botconfig["authentication"], dict)
        )
        or (
            "client_id" not in botconfig["authentication"]
            or not isinstance(botconfig["authentication"]["client_id"], int)
        )
        or (
            "token" not in botconfig["authentication"]
            or not isinstance(botconfig["authentication"]["token"], str)
        )
    ):
        click.secho(
            "  botconfig error: 'authentication' variable must be of type 'dict' "
            "and must at least contain 'client_id' of type 'int' and "
            "'token' of type 'str'",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # botconfig.intents

    if intents is not None:
        botconfig["intents"] = intents

    if not isinstance(botconfig["intents"], int):
        intents_fail = False
        if isinstance(botconfig["intents"], str):
            try:
                botconfig["intents"] = int(
                    botconfig["intents"],
                    base=(
                        2
                        if (base_hint := botconfig["intents"][:2]) == "0b"
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
                "  botconfig error: 'intents' variable must be of type 'int' or 'str' (STRING) "
                "and must be interpretable as an integer.",
                err=True,
                fg="red",
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more botconfig variables as desired

    # -------------------------------------------------------------------------
    # launchconfig.command_prefix
    # launchconfig.mention_as_command_prefix

    final_prefix = None

    if command_prefix:
        launchconfig["command_prefix"] = command_prefix

    if (
        launchconfig["command_prefix"] is not None
        and not isinstance(launchconfig["command_prefix"], (str, list, tuple))
    ) or (
        isinstance(launchconfig["command_prefix"], (list, tuple))
        and not all(isinstance(pfx, str) for pfx in launchconfig["command_prefix"])
    ):
        click.secho(
            "  launchconfig error: Optional 'command_prefix' variable must be of type "
            "'str', of type 'list'/'tuple' containing strings or just None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    if mention_as_command_prefix:
        launchconfig["mention_as_command_prefix"] = mention_as_command_prefix

    if not isinstance(launchconfig["mention_as_command_prefix"], bool):
        click.secho(
            "  launchconfig error: 'mention_as_command_prefix' variable must be of type 'bool'.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    if (
        launchconfig["command_prefix"] is not None
        and launchconfig["mention_as_command_prefix"]
    ):
        final_prefix = commands.when_mentioned_or(
            *(
                (launchconfig["command_prefix"],)
                if isinstance(launchconfig["command_prefix"], str)
                else launchconfig["command_prefix"]
            )
        )
    elif launchconfig["command_prefix"] is not None:
        final_prefix = launchconfig["command_prefix"]
    elif launchconfig["mention_as_command_prefix"]:
        final_prefix = commands.when_mentioned
    else:
        click.secho(
            "  launchconfig error: 'mention_as_command_prefix' variable must be True if 'command_prefix' is None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # launchconfig.extensions

    if not isinstance(launchconfig["extensions"], (list, tuple)):
        click.secho(
            "  launchconfig error: 'exts' variable must be a container of type 'list'/'tuple' "
            "containing dictionaries that specify parameters for the extensions to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    elif launchconfig["extensions"] and not all(
        isinstance(ext_dict, dict) and "name" in ext_dict
        for ext_dict in launchconfig["extensions"]
    ):
        click.secho(
            "  launchconfig error: The objects in the 'exts' variable container must be of type 'dict' "
            "and must at least contain the 'name' key mapping to the string name of an extension to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # launchconfig.databases

    if "databases" in launchconfig:
        if not isinstance(launchconfig["databases"], list) or not all(
            isinstance(db_info_dict, dict)
            and "name" in db_info_dict
            and isinstance(db_info_dict["name"], str)
            and "url" in db_info_dict
            and isinstance(db_info_dict["url"], str)
            and isinstance(db_info_dict.get("connect_args", {}), dict)
            for db_info_dict in launchconfig["databases"]
        ):
            click.secho(
                "  launchconfig error: 'databases' variable must be of type "
                "'list' and must contain one or more database "
                "dictionaries.\n"
                "  Each of them must contain at least a 'name' key for the database "
                "name and a 'url' key mapping to an SQLAlchemy-compatible database "
                "URL string.\n"
                "  The 'connect_args' dictionary for setting up a database "
                "connection is driver-specific and optional.\n"
                "  The first database is always the primary one.\n\n"
                "  {\n"
                '      "...": {"...": ...},\n'
                '      "databases": [\n'
                '          "my_database": {\n'
                '              "name": "my_database",\n'
                '              "url": "engine+driver://path/to/my_database",\n'
                '              "connect_args": {"...": ...}\n'
                "          },\n"
                '          {"...": ..., }\n'
                "      ],\n"
                '      "...": ...,\n'
                "  }\n",
                err=True,
                fg="red",
            )
            raise click.Abort()

        if "main_database_name" in launchconfig:
            if not isinstance(launchconfig["main_database_name"], str):
                click.secho(
                    "  launchconfig error: 'main_database_name' variable must be of type "
                    "'str' and must be the name of a database specified in 'databases'",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

            for i in range(len(launchconfig["databases"])):
                if (
                    launchconfig["databases"][i]["name"]
                    == launchconfig["main_database_name"]
                ):
                    new_main_database = launchconfig["databases"].pop(i)
                    # move selected main db to front
                    launchconfig["databases"].insert(0, new_main_database)
                    break
            else:
                click.secho(
                    "  launchconfig error: 'main_database_name' variable must be "
                    "the name of a database specified in 'databases'",
                    err=True,
                    fg="red",
                )
                raise click.Abort()

    # -------------------------------------------------------------------------
    # launchconfig.log_level

    if (
        "log_level" not in launchconfig
    ):  # logging is disabled in the default configuration
        if log_level is not None:
            launchconfig["log_level"] = (log_level := log_level.upper())
        else:
            launchconfig["log_level"] = None

    elif (
        launchconfig["log_level"] is not None
        and launchconfig["log_level"] not in LOG_LEVEL_NAMES
    ):
        click.secho(
            "  launchconfig error: 'log_level' variable must be a valid log level name of type 'str' or None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more launchconfig variables as desired

    click.echo("  Finished reading configuration data")

    # handle extensions

    if ignore_all_extensions:
        launchconfig["extensions"] = []
    else:
        default_extensions = DEFAULT_EXTENSIONS
        extra_extensions = launchconfig["extensions"]
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

        launchconfig["extensions"] = final_extensions

    # pass configuration data to bot instance
    bot = Bot(
        final_prefix,
        intents=discord.Intents(botconfig["intents"]),  # type: ignore
        help_command=CustomHelpCommand(),
    )

    bot._botconfig = botconfig
    bot._launchconfig = launchconfig

    if (
        launchconfig["log_level"] is not None
    ):  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(launchconfig["log_level"])
        ):
            asyncio.run(start_bot(bot))
            return

    asyncio.run(start_bot(bot))


if __name__ == "__main__":
    main()
