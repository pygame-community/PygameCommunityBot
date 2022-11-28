from typing import Union

import discord
from discord.ext import commands
from packaging.version import Version
import snakecore
from snakecore.commands.decorators import flagconverter_kwargs
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection, AsyncResult
from sqlalchemy.engine import Result
from sqlalchemy import text

from ... import __version__
from ...bot import PygameCommunityBot
from ..base import BaseCommandCog
from .constants import DB_TABLE_PREFIX
from .migrations import MIGRATIONS

BotT = PygameCommunityBot


class MyExt(BaseCommandCog, name="my-ext"):
    """..."""  # describe your extension

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        theme_color: Union[int, discord.Color] = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.bot: BotT = bot
        self.db_engine = db_engine

    # add event listeners, commands, state, interface with databases, etc.


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT, color: Union[int, discord.Color] = 0
):  # add more optional parameters as desired
    db_engine = bot.get_database()
    if not isinstance(db_engine, AsyncEngine):
        raise RuntimeError(
            "Could not find primary database interface of type "
            "'sqlalchemy.ext.asyncio.AsyncEngine'"
        )
    elif db_engine.name not in ("sqlite", "postgresql"):
        raise RuntimeError(f"Unsupported database engine: {db_engine.name}")

    first_setup = False
    try:
        extension_data = await bot.read_extension_data(__package__)
    except LookupError:
        first_setup = True
        extension_data = dict(name=__name__, db_table_prefix=DB_TABLE_PREFIX)
        await bot.create_extension_data(**extension_data, version=__version__)

    extension_version = Version(__version__)
    stored_version = Version("0.0.0" if first_setup else str(extension_data["version"]))
    if stored_version > extension_version:
        raise RuntimeError(
            f'Extension data found for "{__package__}" is incompatible: Stored data version "{stored_version}"'
            f' exceeds extension version "{extension_version}"'
        )

    elif stored_version < extension_version:
        conn: AsyncConnection
        async with db_engine.begin() as conn:
            for vi in MIGRATIONS[db_engine.name]:
                if Version(vi) > stored_version:
                    await conn.execute(text(MIGRATIONS[db_engine.name][f"{vi}"]))

        extension_data["version"] = __version__
        await bot.update_extension_data(**extension_data)

    await bot.add_cog(MyExt(bot, db_engine, theme_color=int(color)))
