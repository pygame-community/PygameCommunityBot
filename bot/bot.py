"""This file should define the `discord.ext.commands.Bot` subclass to use for the project. 
"""

import asyncio
import datetime
import logging
from typing import Any, Type, Union

import discord
from discord.ext import commands
import snakecore

from . import utils

_logger = logging.getLogger(__name__)


class PygameBot(snakecore.commands.Bot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.bot_config: dict = {}
        self.launch_config: dict = {}
        self.recent_response_messages: dict[int, discord.Message] = {}

    async def setup_hook(self) -> None:
        snakecore.utils.hold_task(asyncio.create_task(self._setup_hook()))

    async def _setup_hook(self) -> None:
        """Helper method to circumvent potential deadlocks whilst awaiting
        ``wait_until_ready()``.
        """
        await self.wait_until_ready()
        for ext_dict in self.launch_config["extensions"]:
            try:
                await self.load_extension(
                    ext_dict["name"],
                    package=ext_dict.get("package"),
                    variables=ext_dict.get("variables"),
                )
            except (TypeError, commands.ExtensionFailed) as exc:
                _logger.error(
                    f"Failed to load extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch",
                    exc_info=exc,
                )
            except commands.ExtensionAlreadyLoaded:
                continue
            else:
                _logger.info(
                    f"Successfully loaded extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch"
                )

    async def get_context(
        self,
        origin: Union[discord.Message, discord.Interaction],
        /,
        *,
        cls: Type[commands.Context["PygameBot"]] = discord.utils.MISSING,
    ) -> commands.Context["PygameBot"]:
        new_ctx = await super().get_context(origin, cls=cls)
        setattr(new_ctx, "created_at", datetime.datetime.now(datetime.timezone.utc))
        return new_ctx

    async def on_command_error(
        self, ctx: commands.Context["PygameBot"], exception: commands.CommandError
    ) -> None:
        title = exception.__class__.__name__
        msg = exception.args[0]
        footer_text = exception.__class__.__name__

        log_exception = False
        has_cause = False

        if isinstance(exception, commands.CommandNotFound):
            return

        elif isinstance(exception, commands.BadArgument):
            title = "Invalid Argument(s)!"
            msg = (
                f"{msg}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.UserInputError):
            title = "Invalid Command Input(s)!"
            msg = (
                f"{msg}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.DisabledCommand):
            title = f"Cannot execute command! ({exception.args[0]})"
            msg = (
                f"The specified command has been temporarily blocked from "
                "running, while wizards are casting their spells on it!\n"
                "Please try running the command after the maintenance work "
                "has completed."
            )
        elif exception.__cause__ is not None:
            has_cause = True
            if isinstance(exception.__cause__, discord.HTTPException):
                title = footer_text = exception.__cause__.__class__.__name__
                msg = exception.__cause__.args[0] if exception.__cause__.args else ""
            else:
                log_exception = True
                has_cause = True
                title = "Unknown exception!"
                msg = (
                    "An unhandled exception occured while running the command!\n"
                    "This is most likely a bug in the bot itself, and `@Wizard 🝑`s will "
                    f"recast magical spells on it soon!\n\n"
                    f"```\n{exception.__cause__.args[0] if exception.__cause__.args else ''}```"
                )
                footer_text = exception.__cause__.__class__.__name__

        footer_text = f"{footer_text}\n(React with 🗑 to delete this exception message in the next 30s)"

        response_message = self.recent_response_messages.get(ctx.message.id)

        target_message = response_message

        try:
            (
                (
                    await snakecore.utils.embed_utils.replace_embed_at(
                        target_message,
                        title=title,
                        description=msg,
                        color=0xFF0000,
                        footer_text=footer_text,
                    )
                )
                if target_message is not None
                else (
                    target_message := await snakecore.utils.embed_utils.send_embed(
                        ctx.channel,
                        title=title,
                        description=msg,
                        color=0xFF0000,
                        footer_text=footer_text,
                    )
                )
            )
        except discord.NotFound:
            # response message was deleted, send a new message
            target_message = await snakecore.utils.embed_utils.send_embed(
                ctx.channel,
                title=title,
                description=msg,
                color=0xFF0000,
                footer_text=footer_text,
            )

        snakecore.utils.hold_task(
            asyncio.create_task(
                utils.message_delete_reaction_listener(
                    self,
                    target_message,
                    ctx.author,
                    emoji="🗑",
                    timeout=30,
                )
            )
        )

        main_exception = exception
        if log_exception:
            if has_cause:
                main_exception = exception.__cause__

            _logger.error(
                "An unhandled exception occured in command %s",
                ctx.invoked_with if ctx.invoked_with else ctx.command.qualified_name,
                exc_info=main_exception,
            )

    async def on_command_completion(self, ctx: commands.Context["PygameBot"]):
        if ctx.message.id in self.recent_response_messages:
            del self.recent_response_messages[ctx.message.id]
