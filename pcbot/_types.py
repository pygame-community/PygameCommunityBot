"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any, Collection, Literal, Optional, TypedDict
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from typing_extensions import Required, NotRequired  # type: ignore

ellipsis = type(Ellipsis)


class ConfigDatabaseDict(TypedDict):
    name: str
    url: str
    connect_args: NotRequired[dict[str, Any]]


class DatabaseDict(TypedDict):
    name: str
    engine: AsyncEngine
    url: str
    connect_args: NotRequired[dict[str, Any]]


class ExtensionData(TypedDict):
    name: str
    last_session_version: str
    revision_number: int
    auto_migrate: bool
    db_table_prefix: str
    data: Optional[bytes]


class ConfigAuthentication(TypedDict):
    token: str


class ConfigExtensionDict(TypedDict):
    name: str
    package: NotRequired[str]
    config: dict[str, Any]


class Config(TypedDict, total=False):
    """Helper `TypedDict` for defining bot configuration data."""

    authentication: Required[ConfigAuthentication | dict[str, Any]]
    intents: int

    owner_id: int | None
    owner_ids: Collection[int]
    owner_role_ids: Collection[int]
    manager_role_ids: Collection[int]

    command_prefix: str | list[str] | tuple[str, ...]
    mention_as_command_prefix: bool

    extensions: list[ConfigExtensionDict] | tuple[ConfigExtensionDict, ...]

    databases: list[ConfigDatabaseDict] | tuple[ConfigDatabaseDict, ...]
    main_database_name: str

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
    log_filename: str
    log_file_extension: str
