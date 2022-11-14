"""This file represents the main entry point into the bot application.
"""
import asyncio
import contextlib
import copy
import logging
import os
from typing import Any, Optional, Union

import click
import discord
from discord.ext import commands
import snakecore

from . import constants, utils
from .bot import (
    PygameCommunityBot as Bot,
)

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
    {
        "name": f"{__package__}.exts.docs_pre",
        "config": {"color": constants.DEFAULT_EMBED_COLOR},
    },
    {
        "name": f"{__package__}.exts.help",
        "config": {"color": constants.DEFAULT_EMBED_COLOR},
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

config: dict = copy.deepcopy(DEFAULT_CONFIG)


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
    "will occur.")
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
):
    """Launch this Discord bot application."""

    if ctx.invoked_subcommand is not None:
        return

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
            click.echo("  No 'localconfig.py' file found, continuing...")
        else:
            click.echo(f"  Successfully loaded 'localconfig' from {localconfig_path}")

    click.echo("Reading configuration data...")

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
            "  config error: 'authentication' variable must be of type 'dict' "
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
            "  config error: 'exts' variable must be a container of type 'list'/'tuple' "
            "containing dictionaries that specify parameters for the extensions to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    elif config["extensions"] and not all(
        isinstance(ext_dict, dict) and "name" in ext_dict
        for ext_dict in config["extensions"]
    ):
        click.secho(
            "  config error: The objects in the 'exts' variable container must be of type 'dict' "
            "and must at least contain the 'name' key mapping to the string name of an extension to load.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # config.databases

    if "databases" in config:
        if not isinstance(config["databases"], list) or not all(
            isinstance(db_info_dict, dict)
            and "name" in db_info_dict
            and isinstance(db_info_dict["name"], str)
            and "url" in db_info_dict
            and isinstance(db_info_dict["url"], str)
            and isinstance(db_info_dict.get("connect_args", {}), dict)
            for db_info_dict in config["databases"]
        ):
            click.secho(
                "  config error: 'databases' variable must be of type "
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

    # -------------------------------------------------------------------------
    # config.main_database_name

    # -------------------------------------------------------------------------
    # config.log_level

    if "log_level" not in config:  # logging is disabled in the default configuration
        if log_level is not None:
            config["log_level"] = (log_level := log_level.upper())
        else:
            config["log_level"] = None

    elif config["log_level"] is not None and config["log_level"] not in LOG_LEVEL_NAMES:
        click.secho(
            "  config error: 'log_level' variable must be a valid log level name of type 'str' or None.",
            err=True,
            fg="red",
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more config variables as desired

    click.echo("  Finished reading configuration data")

    # handle extensions

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

        config["extensions"] = final_extensions

    # pass configuration data to bot instance
    bot = Bot(final_prefix, intents=discord.Intents(config["intents"]), strip_after_prefix=True)  # type: ignore

    bot._config = config

    if (
        config["log_level"] is not None
    ):  #  not specifying a logging level disables logging
        with logging_handling(log_level=logging.getLevelName(config["log_level"])):
            asyncio.run(start_bot(bot))
            return

    asyncio.run(start_bot(bot))


if __name__ == "__main__":
    main()
