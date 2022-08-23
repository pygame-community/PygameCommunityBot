"""This file represents the main entry point into the bot application.
"""
import asyncio
import contextlib
import copy
import importlib.util
import logging
import os
import os.path
import sys
import types
from typing import Optional

import click
import discord
from discord.ext import commands
import snakecore  # TODO: Remove this if not using snakecore

from .bot import (
    TemplateBot as Bot,
)  # TODO: Rename TemplateBot according to your bot application.

try:
    import uvloop  # type: ignore
except ImportError:
    pass
else:
    # uvloop replaces the default Python event loop with a cythonized version.
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

log_levels: set[str] = {
    "CRITICAL",
    "FATAL",
    "ERROR",
    "WARN",
    "WARNING",
    "INFO",
    "DEBUG",
    "NOTSET",
}

DEFAULT_BOT_CONFIG: dict = {"intents": discord.Intents.default().value}
DEFAULT_LAUNCH_CONFIG: dict = {
    "command_prefix": "!",
    "mention_as_command_prefix": False,
    "extensions": [
        {
            "name": f"{__package__}.exts.ping_pong"
        },  # TODO: Remove sample extension entry from default if it was deleted
    ],  # load default extension
}

BOT_CONFIG: dict = copy.deepcopy(DEFAULT_BOT_CONFIG)
LAUNCH_CONFIG: dict = copy.deepcopy(DEFAULT_LAUNCH_CONFIG)


def import_module_from_path(module_name: str, file_path: str) -> types.ModuleType:
    abs_file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_file_path)
    if spec is None:
        raise ImportError(
            f"failed to generate module spec for module named '{module_name}' at '{abs_file_path}'"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError as fnf:
        raise ImportError(
            f"failed to find code for module named '{module_name}' at '{abs_file_path}'"
        ) from fnf
    return module


def setup_logging(log_level: int = logging.INFO) -> None:
    discord.utils.setup_logging(level=log_level)


def clear_logging_handlers(logger: Optional[logging.Logger] = None):
    if logger is None:
        logger = logging.getLogger()

    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)


@contextlib.contextmanager
def logging_handling(log_level: int = logging.INFO) -> None:
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
        print(f"Starting bot ({bot.__class__.__name__})...")
        await bot.start(bot.bot_config["auth"]["token"])
    except KeyboardInterrupt:
        pass
    finally:
        await close_bot(bot)


async def close_bot(bot: Bot) -> None:
    print("Closing bot...")
    await bot.close()
    await snakecore.quit()  # TODO: Remove this if not using snakecore


# fmt: off
@click.command(add_help_option=False)
@click.option("--bot-config", "bot_config_path", default="./bot_config.py",
    type=click.Path(resolve_path=True),
    help="A path to the 'bot_config.py' file to use for configuring bot credentials.")
@click.option("--launch-config", "launch_config_path", default="./launch_config.py",
    type=click.Path(resolve_path=True),
    help="A path to the 'launch_config.py' file to use for configuring bot launching.")
@click.option("--intents", type=str,
    help=("The integer of bot intents as bitwise flags to be used by the bot instead "
    f"of discord.py's defaults ({bin(DEFAULT_BOT_CONFIG['intents'])}). "
    "It can be specified as a base 2, 8, 10 or 16 integer literal. Note that the "
    "message content intent (1 << 15) flag is not set by default. See more at "
    "https://discord.com/developers/docs/topics/gateway#list-of-intents"))
@click.option("--prefix", "--command-prefix", "command_prefix", multiple=True,
    show_default=True, type=str,
    help=("The command prefix(es) to use. "
    f"By default, {DEFAULT_LAUNCH_CONFIG['command_prefix']} is used as a prefix."))
@click.option("--mention-as-prefix", "--mention-as-command-prefix", "mention_as_command_prefix",
    is_flag=True, help="Enable the usage of bot mentions as a prefix.")
@click.option("--disable-ext", "--disable-extension", "disable_extension",
    multiple=True, type=str,
    help="The qualified name(s) of the extension(s) to disable upon startup.")
@click.option("--log-level", "--bot-log-level", "log_level",
    show_default=True, type=click.Choice(
        ('NOTSET', 'DEBUG', 'INFO', 'WARNING', 'WARN', 'ERROR', 'FATAL', 'CRITICAL')),
    help="The log level to use for the bot's default logging system.")
# TODO: Add more CLI options specific to your application.
@click.help_option("-h", "--help", "help")
# fmt: on
def main(
    bot_config_path: str,
    launch_config_path: str,
    command_prefix: tuple[str, ...],
    mention_as_command_prefix: bool,
    intents: Optional[int],
    disable_extension: tuple[str, ...],
    log_level: Optional[str],
):
    """Launch this Discord bot application."""

    # load mandatory BOT_CONFIG data
    try:
        bot_config = import_module_from_path("bot_config", bot_config_path)
        try:
            BOT_CONFIG.update(bot_config.BOT_CONFIG)
        except AttributeError:
            click.echo(
                "Could not find the 'BOT_CONFIG' dictionary in the 'bot_config.py' "
                f"file at '{bot_config_path}'.",
                err=True,
            )
            raise click.Abort()
    except ImportError:
        click.echo(f"Could not find a 'bot_config.py' file.", err=True)
        raise click.Abort()

    # load optional LAUNCH_CONFIG data
    try:
        launch_config = import_module_from_path("launch_config", launch_config_path)
        try:
            LAUNCH_CONFIG.update(launch_config.LAUNCH_CONFIG)
        except AttributeError:
            click.echo(
                "Could not find the 'LAUNCH_CONFIG' dictionary in the "
                f"'launch_config.py' file at '{launch_config_path}'.",
                err=True,
            )
            raise click.Abort()
    except ImportError:
        click.echo("No 'launch_config.py' file found, using defaults instead...")

    # -------------------------------------------------------------------------
    # BOT_CONFIG.auth
    ## BOT_CONFIG.auth.client_id
    ## BOT_CONFIG.auth.token

    if (
        ("auth" not in BOT_CONFIG or not isinstance(BOT_CONFIG["auth"], dict))
        or (
            "client_id" not in BOT_CONFIG["auth"]
            or not isinstance(BOT_CONFIG["auth"]["client_id"], int)
        )
        or (
            "token" not in BOT_CONFIG["auth"]
            or not isinstance(BOT_CONFIG["auth"]["token"], str)
        )
    ):
        click.echo(
            "BOT_CONFIG error: 'auth' variable must be of type 'dict' "
            "and must at least contain 'client_id' of type 'int' and "
            "'token' of type 'str'",
            err=True,
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # BOT_CONFIG.intents

    if intents is not None:
        BOT_CONFIG["intents"] = intents

    if not isinstance(BOT_CONFIG["intents"], int):
        intents_fail = False
        if isinstance(BOT_CONFIG["intents"], str):
            try:
                BOT_CONFIG["intents"] = int(
                    BOT_CONFIG["intents"],
                    base=(
                        2
                        if (base_hint := BOT_CONFIG["intents"][:2]) == "0b"
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
            click.echo(
                "BOT_CONFIG error: 'intents' variable must be of type 'int' or 'str' "
                "and must be interpretable as an integer.",
                err=True,
            )
            raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more BOT_CONFIG variables as desired

    # -------------------------------------------------------------------------
    # LAUNCH_CONFIG.command_prefix
    # LAUNCH_CONFIG.mention_as_command_prefix

    final_prefix = None

    if command_prefix:
        LAUNCH_CONFIG["command_prefix"] = command_prefix

    if (
        LAUNCH_CONFIG["command_prefix"] is not None
        and not isinstance(LAUNCH_CONFIG["command_prefix"], (str, list, tuple))
    ) or (
        isinstance(LAUNCH_CONFIG["command_prefix"], (list, tuple))
        and not all(isinstance(pfx, str) for pfx in LAUNCH_CONFIG["command_prefix"])
    ):
        click.echo(
            "LAUNCH_CONFIG error: Optional 'command_prefix' variable must be of type "
            "'str', of type 'list'/'tuple' containing strings or just None.",
            err=True,
        )
        raise click.Abort()

    if mention_as_command_prefix:
        LAUNCH_CONFIG["mention_as_command_prefix"] = mention_as_command_prefix

    if not isinstance(LAUNCH_CONFIG["mention_as_command_prefix"], bool):
        click.echo(
            "LAUNCH_CONFIG error: 'mention_as_command_prefix' variable must be of type 'bool'.",
            err=True,
        )
        raise click.Abort()

    if (
        LAUNCH_CONFIG["command_prefix"] is not None
        and LAUNCH_CONFIG["mention_as_command_prefix"]
    ):
        final_prefix = commands.when_mentioned_or(
            *(
                (LAUNCH_CONFIG["command_prefix"],)
                if isinstance(LAUNCH_CONFIG["command_prefix"], str)
                else LAUNCH_CONFIG["command_prefix"]
            )
        )
    elif LAUNCH_CONFIG["command_prefix"] is not None:
        final_prefix = LAUNCH_CONFIG["command_prefix"]
    elif LAUNCH_CONFIG["mention_as_command_prefix"]:
        final_prefix = commands.when_mentioned
    else:
        click.echo(
            "LAUNCH_CONFIG error: 'mention_as_command_prefix' variable must be True if 'command_prefix' is None.",
            err=True,
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # LAUNCH_CONFIG.exts

    if not isinstance(LAUNCH_CONFIG["extensions"], (list, tuple)):
        click.echo(
            "LAUNCH_CONFIG error: 'exts' variable must be a container of type 'list'/'tuple' "
            "containing dictionaries that specify parameters for the extensions to load.",
            err=True,
        )
        raise click.Abort()

    elif LAUNCH_CONFIG["extensions"] and not all(
        isinstance(ext_dict, dict) and "name" in ext_dict
        for ext_dict in LAUNCH_CONFIG["extensions"]
    ):
        click.echo(
            "LAUNCH_CONFIG error: The objects in the 'exts' variable container must be of type 'dict' "
            "and must at least contain the 'name' key mapping to the string name of an extension to load.",
            err=True,
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # LAUNCH_CONFIG.log_level

    if (
        "log_level" not in LAUNCH_CONFIG
    ):  # logging is disabled in the default configuration
        if log_level is not None:
            LAUNCH_CONFIG["log_level"] = (log_level := log_level.upper())
        else:
            LAUNCH_CONFIG["log_level"] = None

    elif (
        LAUNCH_CONFIG["log_level"] is not None
        and LAUNCH_CONFIG["log_level"] not in log_levels
    ):
        click.echo(
            "LAUNCH_CONFIG error: 'log_level' variable must be a valid log level name of type 'str' or None.",
            err=True,
        )
        raise click.Abort()

    # -------------------------------------------------------------------------
    # TODO: Add support for more LAUNCH_CONFIG variables as desired

    # remove disabled extensions
    if disable_extension:
        disable_extension = set(disable_extension)
        LAUNCH_CONFIG["extensions"] = [
            ext_dict
            for ext_dict in LAUNCH_CONFIG["extensions"]
            if ext_dict["name"] not in disable_extension
        ]

    # pass configuration data to bot instance
    bot = Bot(final_prefix, intents=discord.Intents(BOT_CONFIG["intents"]))
    bot.bot_config = BOT_CONFIG
    bot.launch_config = LAUNCH_CONFIG

    if (
        LAUNCH_CONFIG["log_level"] is not None
    ):  #  not specifying a logging level disables logging
        with logging_handling(
            log_level=logging.getLevelName(LAUNCH_CONFIG["log_level"])
        ):
            asyncio.run(start_bot(bot))
            return

    asyncio.run(start_bot(bot))


if __name__ == "__main__":
    main()
