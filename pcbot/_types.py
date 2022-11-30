"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from typing import Any, Optional, TypedDict
from typing_extensions import NotRequired

from sqlalchemy.ext.asyncio import AsyncEngine


class _InputDatabaseDict(TypedDict):
    name: str
    url: str
    connect_args: NotRequired[dict[str, Any]]


class _DatabaseDict(TypedDict):
    name: str
    engine: AsyncEngine
    url: NotRequired[str]
    connect_args: NotRequired[dict[str, Any]]


class ExtensionData(TypedDict):
    name: str
    version: str
    db_table_prefix: str
    data: Optional[bytes]
