"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, TypedDict
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from typing_extensions import NotRequired  # type: ignore


class _InputDatabaseDict(TypedDict):
    name: str
    url: str
    connect_args: NotRequired[dict[str, Any]]


class DatabaseDict(TypedDict):
    name: str
    engine: AsyncEngine
    url: NotRequired[str]
    connect_args: NotRequired[dict[str, Any]]


class ExtensionData(TypedDict):
    name: str
    last_session_version: str
    revision_number: int
    auto_migrate: bool
    db_table_prefix: str
    data: Optional[bytes]
