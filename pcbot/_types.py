from typing import Any, TypedDict
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
