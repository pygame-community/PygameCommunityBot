import asyncio
from typing import Optional, Sequence, Union
import discord
from discord.ext import commands
import snakecore


async def message_delete_reaction_listener(
    bot: commands.Bot,
    msg: discord.Message,
    invoker: Union[discord.Member, discord.User],
    emoji: Union[discord.Emoji, discord.PartialEmoji, str],
    role_whitelist: Sequence[int] = None,
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
        role_whitelist (Sequence[int]): A sequence (that supports `__contains__`) of
          role IDs whose reactions can also be picked up by this function.
        timeout (Optional[float]): A timeout for waiting, before automatically
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
        valid_user_ids = set(
            (
                (
                    invoker.id,
                    *(
                        (bot.owner_id,)
                        if bot.owner_id
                        else tuple(bot.owner_ids)
                        if bot.owner_ids
                        else ()
                    ),
                )
            )
        )
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
                f"argument 'invoker' expected discord.Member/.User, not {invoker.__class__.__name__}"
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
