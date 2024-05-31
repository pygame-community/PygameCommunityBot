"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.

This file defines functionality used to parse bot configuration files.
"""

from importlib.util import resolve_name
import os
from typing import Any, Collection, MutableMapping

from discord.ext import commands
import click

from pcbot import constants
from pcbot.utils import raise_
from pcbot.utils.parsermapping import ParserMapping, PMValue, ParsingError


def parse_intents(key: str, intents: int, cfg: MutableMapping[str, Any]) -> int:
    if (
        "_cli_args" in cfg
        and "intents" in cfg["_cli_args"]
        and cfg["_cli_args"]["intents"] is not None
    ):
        intents = cfg["_cli_args"]["intents"]

    if not isinstance(intents, int):
        fail = False
        if isinstance(intents, str):
            try:
                intents = int(
                    intents,
                    base=(
                        2
                        if (base_hint := intents[:2]) == "0b"
                        else 8
                        if base_hint == "0o"
                        else 16
                        if base_hint == "0x"
                        else 10
                    ),
                )
            except ValueError:
                fail = True
        else:
            fail = True

        if fail:
            raise ParsingError(
                "'intents' variable must be of type 'int' or 'str' (STRING) "
                "and must be interpretable as an integer."
            )

    return intents


def parse_command_prefix(
    key: str, command_prefix: Any, cfg: MutableMapping[str, Any]
) -> Any:
    if "_cli_args" in cfg and "command_prefix" in cfg["_cli_args"]:
        command_prefix = cfg["_cli_args"]["command_prefix"]

    if (
        command_prefix is not None
        and not isinstance(command_prefix, (str, list, tuple))
    ) or (
        isinstance(command_prefix, (list, tuple))
        and not all(isinstance(pfx, str) for pfx in command_prefix)
    ):
        raise ParsingError(
            "Optional 'command_prefix' variable must be of type "
            "'str', of type 'list'/'tuple' containing strings or just None.",
        )

    if not isinstance(cfg["mention_as_command_prefix"], bool):
        raise ParsingError(
            "'mention_as_command_prefix' variable must be of type 'bool'.",
        )

    if command_prefix is not None and cfg["mention_as_command_prefix"]:
        cfg["final_prefix"] = commands.when_mentioned_or(
            *((command_prefix,) if isinstance(command_prefix, str) else command_prefix)
        )
    elif command_prefix is not None:
        cfg["final_prefix"] = command_prefix
    elif cfg["mention_as_command_prefix"]:
        cfg["final_prefix"] = commands.when_mentioned
    else:
        raise ParsingError(
            "'mention_as_command_prefix' variable must be True if 'command_prefix' is None.",
        )

    return command_prefix


def parse_extensions(
    key: str, extensions: Any, cfg: MutableMapping[str, Any]
) -> list[dict[str, Any]]:
    if not isinstance(extensions, (list, tuple)):
        raise ParsingError(
            "'extensions' variable must be a container of type "
            "'list'/'tuple' containing dictionaries that specify "
            "parameters for the extensions to load."
        )

    elif extensions and not all(
        isinstance(ext_dict, dict) and "name" in ext_dict for ext_dict in extensions
    ):
        raise ParsingError(
            "The objects in the 'extensions' variable container "
            "must be of type 'dict' and must at least contain the 'name' key "
            "that maps to the string name of an extension to load."
        )

    # handle extension dicts

    ignore_all_extensions = False
    ignore_default_extensions = False
    ignore_extra_extensions = False
    ignore_all_extensions = False
    ignore_extension = None

    if "_cli_args" in cfg:
        ignore_all_extensions = cfg["_cli_args"].get("ignore_all_extensions", False)
        ignore_default_extensions = cfg["_cli_args"].get(
            "ignore_default_extensions", False
        )
        ignore_extra_extensions = cfg["_cli_args"].get("ignore_extra_extensions", False)
        ignore_all_extensions = cfg["_cli_args"].get("ignore_all_extensions", False)
        ignore_extension = cfg["_cli_args"].get("ignore_extension", None)

    if ignore_all_extensions:
        extensions = []
    else:
        default_extensions = constants.DEFAULT_EXTENSIONS
        extra_extensions = extensions
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
            extensions = list(
                {
                    resolve_name(dct["name"], dct["package"])
                    if "package" in dct
                    else dct["name"]: dct
                    for dct in final_extensions
                }.values()
            )  # allow extension dicts to overwrite each other by their qualified name
        except Exception as e:
            raise ParsingError(
                "Internal error while processing 'extension' "
                f"variable: {e.__class__.__name__}: {e}"
            )

    return extensions


def parse_databases(
    key: str, databases: Any, cfg: MutableMapping[str, Any]
) -> list[dict[str, Any]]:
    if not (
        databases
        and isinstance(databases, list)
        and all(
            isinstance(db_info_dict, dict)
            and "name" in db_info_dict
            and isinstance(db_info_dict["name"], str)
            and "url" in db_info_dict
            and isinstance(db_info_dict["url"], str)
            and isinstance(db_info_dict.get("connect_args", {}), dict)
            for db_info_dict in databases
        )
    ):
        raise ParsingError(
            "'databases' variable must be of type "
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
            "  }\n"
        )

    return databases


def parse_main_database_name(
    key: str, main_database_name: Any, cfg: MutableMapping[str, Any]
) -> str:
    if not isinstance(main_database_name, str):
        raise ParsingError(
            "'main_database_name' variable must be of type "
            "'str' and must be the name of a database specified in 'databases'"
        )

    for i in range(len(cfg["databases"])):
        if cfg["databases"][i]["name"] == main_database_name:
            new_main_database = cfg["databases"].pop(i)
            # move selected main db to front
            cfg["databases"].insert(0, new_main_database)
            break
    else:
        raise ParsingError(
            "'main_database_name' variable must be "
            "the name of a database specified in 'databases'"
        )

    return main_database_name


def parse_log_level(
    key: str, log_level: str | None, cfg: MutableMapping[str, Any]
) -> str | None:
    if "_cli_args" in cfg and "log_level" in cfg["_cli_args"]:
        log_level = cfg["_cli_args"]["log_level"]

    log_level = log_level.upper() if log_level else log_level

    if log_level is not None and log_level not in constants.LOG_LEVEL_NAMES:
        raise ParsingError(
            "'log_level' variable must be a valid log level name of "
            "type 'str', or None."
        )

    return log_level


def parse_owner_ids(
    key: str, owner_ids: Any, cfg: MutableMapping[str, Any]
) -> Collection[int]:
    if "owner_id" in cfg and cfg["owner_id"] is not None:
        raise ParsingError(
            "'owner_id' and 'owner_ids' variables cannot be " "specified together."
        )
    try:
        if not (owner_ids and all(isinstance(role_id, int) for role_id in owner_ids)):
            raise ParsingError(
                "'owner_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing."
            )
    except TypeError:
        raise ParsingError(
            "'owner_ids' variable must be a container "
            "(preferably a 'set' object) of 'int's that supports membership testing."
        )

    return owner_ids


def parse_owner_role_ids(
    key: str, owner_role_ids: Any, cfg: MutableMapping[str, Any]
) -> Collection[int]:
    try:
        if not (
            owner_role_ids
            and all(isinstance(role_id, int) for role_id in owner_role_ids)
        ):
            click.secho(
                "'owner_role_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing.",
                err=True,
                fg="red",
            )
            raise click.Abort()
    except TypeError:
        raise ParsingError(
            "'owner_role_ids' variable must be a container "
            "(preferably a 'set' object) of 'int's that supports membership testing."
        )

    return owner_role_ids


def parse_manager_role_ids(
    key: str, manager_role_ids: Any, cfg: MutableMapping[str, Any]
) -> Collection[int]:
    try:
        if not (all(isinstance(role_id, int) for role_id in manager_role_ids)):
            raise ParsingError(
                "'manager_role_ids' variable must be a container "
                "(preferably a 'set' object) of 'int's that supports membership testing."
            )
    except TypeError:
        raise ParsingError(
            "'manager_role_ids' variable must be a container "
            "(preferably a 'set' object) of 'int's that supports membership testing."
        )

    return manager_role_ids


parser_mapping = ParserMapping(
    {
        "authentication": PMValue(
            ParserMapping(
                {
                    "token": (
                        lambda k, v, m: v
                        if isinstance(v, str)
                        else raise_(
                            ParsingError(
                                "Required 'authentication' variable must be of type 'dict' "
                                "and must at least contain 'token' of type 'str'"
                            )
                        )
                    )
                },
                require_all=True,
            ),
            required=True,
        ),
        "intents": parse_intents,
        "mention_as_command_prefix": (
            lambda key, value, cfg: value
            if isinstance(
                (
                    value := cfg["_cli_args"][key]
                    if "_cli_args" in cfg and key in cfg["_cli_args"]
                    else value
                ),
                bool,
            )
            else raise_(
                ParsingError(
                    "'mention_as_command_prefix' variable must be of type 'bool'."
                )
            )
        ),
        "command_prefix": parse_command_prefix,
        "extensions": parse_extensions,
        "databases": parse_databases,
        "auto_migrate": bool,
        "log_level": parse_log_level,
        "log_directory": (
            lambda key, log_directory, cfg: log_directory
            if isinstance(log_directory, str) and os.path.isdir(log_directory)
            else raise_(
                ParsingError(
                    "'log_directory' variable must be a valid 'str' path "
                    "to a directory."
                )
            )
        ),
        "log_filename": (
            lambda key, log_filename, cfg: log_filename
            if isinstance(log_filename, str)
            else raise_(
                ParsingError(
                    "'log_filename' variable must be a valid file name."
                )
            )
        ),
        "log_file_extension": (
            lambda key, log_file_extension, cfg: log_file_extension
            if isinstance((log_file_extension := log_file_extension.strip(".")), str)
            else raise_(
                ParsingError(
                    "'log_file_extension' variable must be a 'str'"
                    "representing a file extension."
                )
            )
        ),
        "owner_id": (
            lambda k, v, cfg: v
            if isinstance(v, int | None)
            else raise_(
                ParsingError(
                    "'owner_id' variable must be either an 'int' object or 'None'."
                )
            )
        ),
        "owner_ids": parse_owner_ids,
        "owner_role_ids": parse_owner_role_ids,
        "manager_role_ids": parse_manager_role_ids,
    }
)
