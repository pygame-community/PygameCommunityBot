import asyncio
import importlib
from logging import Logger
import os
import sys
import types
from typing import Any, Iterable, Optional, Sequence, Union

import discord
from discord.ext import commands
import snakecore
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.ext.asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncConnection


def import_module_from_path(module_name: str, file_path: str) -> types.ModuleType:
    abs_file_path = os.path.abspath(file_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_file_path)  # type: ignore
    if spec is None:
        raise ImportError(
            f"failed to generate module spec for module named '{module_name}' at '{abs_file_path}'"
        )
    module = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError as fnf:
        raise ImportError(
            f"failed to find code for module named '{module_name}' at '{abs_file_path}'"
        ) from fnf
    return module


async def load_databases(
    db_info_data: Sequence[dict[str, Union[str, dict[str, Any]]]],
    raise_exceptions: bool = True,
    logger: Optional[Logger] = None,
) -> list[dict[str, Union[str, dict, AsyncEngine]]]:
    dbs = []

    for db_info_dict in db_info_data:
        db_name = db_info_dict["name"]
        engine = None

        try:
            engine_kwargs = {}

            if "connect_args" in db_info_dict:
                engine_kwargs["connect_args"] = db_info_dict["connect_args"]

            engine = create_async_engine(db_info_dict["url"], **engine_kwargs)

            async with engine.connect() as conn:
                pass

        except sqlalchemy.exc.SQLAlchemyError as exc:
            if logger is not None:
                logger.error(
                    f"Failed to create engine and functioning connection "
                    + (
                        f"'{engine.name}+{engine.driver}' "
                        if engine is not None
                        else ""
                    )
                    + f"for database '{db_name}'",
                    exc_info=exc,
                )

            if raise_exceptions:
                raise
        else:
            dbs.append({"name": db_name, "engine": engine, "url": db_info_dict["url"]})

            if "connect_args" in db_info_dict:
                dbs[db_name]["connect_args"] = db_info_data["connect_args"]  # type: ignore

            if logger is not None:
                logger.info(
                    f"Successfully configured engine '{engine.name}+{engine.driver}' "
                    f"for database '{db_name}'"
                )

    return dbs


async def unload_databases(
    dbs: Iterable[dict[str, Union[str, dict, AsyncEngine]]],
    raise_exceptions: bool = True,
    logger: Optional[Logger] = None,
):
    for db_dict in dbs:
        db_name = db_dict["name"]
        if not isinstance(db_dict["engine"], AsyncEngine):
            raise TypeError(
                "db_dict['engine'] must be instance of AsnycEngine for all dicts in 'dbs'"
            )

        engine: AsyncEngine = db_dict["engine"]

        try:
            await engine.dispose()
        except sqlalchemy.exc.SQLAlchemyError as err:
            if logger is not None:
                logger.error(
                    f"Failed to dispose connection pool of engine '{engine.name}+{engine.driver}' of database '{db_name}'",
                    exc_info=err,
                )

            if raise_exceptions:
                raise
        else:
            if logger is not None:
                logger.info(
                    f"Successfully disposed connection pool of engine '{engine.name}+{engine.driver}' of database '{db_name}'"
                )


async def message_delete_reaction_listener(
    bot: commands.Bot,
    msg: discord.Message,
    invoker: Union[discord.Member, discord.User],
    emoji: Union[discord.Emoji, discord.PartialEmoji, str],
    role_whitelist: Optional[Sequence[int]] = None,
    timeout: Optional[float] = None,
):
    """Allows for a message to be deleted using a specific reaction.
    If any HTTP-related exceptions are raised by `discord.py` within this function,
    it will fail silently.

    Args:
        msg (discord.Message): The message to use.
        invoker (Union[discord.Member, discord.User]): The member/user who can delete
          a message.
        emoji (Union[discord.Emoji, discord.PartialEmoji, str]): The emoji to
          listen for.
        role_whitelist (Sequence[int], optional): A sequence (that supports `__contains__`) of
          role IDs whose reactions can also be picked up by this function.
        timeout (Optional[float], optional): A timeout for waiting, before automatically
          removing any added reactions and returning silently.

    Raises:
        TypeError: Invalid argument types.
    """

    role_whitelist = role_whitelist or ()

    if not isinstance(emoji, (discord.Emoji, discord.PartialEmoji, str)):
        raise TypeError("invalid emoji given as input")

    try:
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            return

        check = None
        await bot.is_owner(invoker)  # fetch and cache bot owners implicitly
        # fmt: off
        valid_user_ids = set((
            (invoker.id, *(
            (bot.owner_id,)
            if bot.owner_id else
            tuple(bot.owner_ids)
            if bot.owner_ids
            else ()),)
        ))
        # fmt: on
        if isinstance(invoker, discord.Member):
            check = (
                lambda event: event.message_id == msg.id
                and (event.guild_id == getattr(msg.guild, "id", None))
                and (
                    event.user_id in valid_user_ids
                    or any(
                        role.id in role_whitelist
                        for role in getattr(event.member, "roles", ())[1:]
                    )
                )
                and snakecore.utils.is_emoji_equal(event.emoji, emoji)
            )
        elif isinstance(invoker, discord.User):

            check = (
                lambda event: event.message_id == msg.id
                and (event.guild_id == getattr(msg.guild, "id", None))
                and (event.user_id in valid_user_ids)
                and snakecore.utils.is_emoji_equal(event.emoji, emoji)
            )
        else:
            raise TypeError(
                "argument 'invoker' expected discord.Member/.User, "
                f"not {invoker.__class__.__name__}"
            )

        event: discord.RawReactionActionEvent = await bot.wait_for(
            "raw_reaction_add", check=check, timeout=timeout
        )

        try:
            await msg.delete()
        except discord.HTTPException:
            pass

    except (asyncio.TimeoutError, asyncio.CancelledError) as a:
        try:
            await msg.clear_reaction(emoji)
        except discord.HTTPException:
            pass

        if isinstance(a, asyncio.CancelledError):
            raise a
