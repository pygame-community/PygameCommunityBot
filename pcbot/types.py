"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from __future__ import annotations
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    Literal,
    TypedDict,
)
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from typing_extensions import Required, NotRequired  # type: ignore

ellipsis = type(Ellipsis)


class ConfigDatabaseDict(TypedDict):
    name: str
    "The database name."
    url: str
    "The SQLAlchemy database connection URL."
    connect_args: NotRequired[dict[str, Any]]
    "Additional arguments to use when establishing a connection to the database."


class DatabaseDict(TypedDict):
    name: str
    engine: AsyncEngine
    url: str
    connect_args: NotRequired[dict[str, Any]]


class ExtensionData(TypedDict):
    name: str
    revision_number: int
    auto_migrate: bool
    db_prefix: str
    data: bytes | None


class ConfigAuthentication(TypedDict):
    client_id: NotRequired[int]
    token: str
    "Bot token."


class ConfigExtensionDict(TypedDict):
    name: str
    "Bot extension module name."
    package: NotRequired[str]
    "Bot extension module package name. Useful for relative imports"
    config: NotRequired[dict[str, Any]]
    "Bot extension configuration arguments, if supported by an extension."


class Config(TypedDict, total=False):
    """Helper ``TypedDict`` for defining bot configuration data."""

    authentication: Required[ConfigAuthentication | dict[str, Any]]
    intents: int

    owner_id: int | None
    owner_ids: Collection[int]
    owner_role_ids: Collection[int]
    manager_role_ids: Collection[int]

    command_prefix: str | list[str] | tuple[str, ...]
    mention_as_command_prefix: bool

    extensions: list[ConfigExtensionDict] | tuple[ConfigExtensionDict, ...]
    "Bot extensions."

    databases: list[ConfigDatabaseDict] | tuple[ConfigDatabaseDict, ...]
    """A sequence of configuration dictionaries to use for
    initializing database connections to access at runtime.
    The first dictionary represents the primary database.
    """
    main_database_name: str
    """The name of the primary database to be used at runtime.
    """
    auto_migrate: bool

    log_level: Literal[
        "CRITICAL",
        "FATAL",
        "ERROR",
        "WARN",
        "WARNING",
        "INFO",
        "DEBUG",
        "NOTSET",
    ]

    log_directory: str
    """The directory to store bot ``.log`` files to.
    """
    log_filename: str
    """The filename to use for bot ``.log`` files.
    Will be suffixed with ``.x.log``, where ``x`` represents
    a numeric label for the log file.
    """

    log_file_extension: str
    """The file extension to use for bot log files instead of ``.log``. 
    """

    dev_guild_id: int
    "The ID of the guild used for bot development."

    sync_app_commands: bool
    """Whether to sync all app commands with Discord.
    Only enable this if actual changes were made to app commands,
    and disable it after syncing. Beware of high rate limits.
    """
    copy_global_app_commands_to_dev_guild: bool
    """Whether to copy all global app commands to the guild with
    the ID specified under ``dev_guild_id``. Only works if ``sync_app_commands``
    is set to ``True``.
    """
    clear_global_app_commands: bool
    """Whether to clear all global app commands. Only works if ``sync_app_commands``
    is set to ``True``.
    """
    clear_dev_guild_app_commands: bool
    """Whether to clear all app commands synced to the guild with
    the ID specified under ``dev_guild_id``. Only works if ``sync_app_commands``
    is set to ``True``.
    """


class Revision(TypedDict):
    date: str
    description: str
    migrate: dict[str, list[str]]
    rollback: dict[str, list[str]]
    delete: NotRequired[dict[str, list[str]]]
