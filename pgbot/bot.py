"""This file should define the `discord.ext.commands.Bot` subclass to use for the project. 
"""

import asyncio
import datetime
import logging
from typing import Type, Union

import discord
from discord.ext import commands
import snakecore

from . import utils

_logger = logging.getLogger(__name__)


class PygameBot(snakecore.commands.Bot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._botconfig: dict = {}
        self._launchconfig: dict = {}
        self._recent_error_messages: dict[int, discord.Message] = {}

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

    async def setup_hook(self) -> None:
        for ext_dict in self._launchconfig["extensions"]:
            try:
                await self.load_extension_with_config(
                    ext_dict["name"],
                    package=ext_dict.get("package"),
                    config=ext_dict.get("config"),
                )
            except commands.ExtensionAlreadyLoaded:
                continue

            except (TypeError, commands.ExtensionError) as exc:
                _logger.error(
                    f"Failed to load extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch",
                    exc_info=exc,
                )
            else:
                _logger.info(
                    f"Successfully loaded extension '{ext_dict.get('package', '')}{ext_dict['name']}' at launch"
                )

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("------")

    async def on_command_error(
        self, context: commands.Context["PygameBot"], exception: commands.CommandError
    ) -> None:

        send_error_message = True

        if self.extra_events.get("on_command_error", None):
            send_error_message = False

        command = context.command
        if command and command.has_error_handler():
            send_error_message = False

        cog = context.cog
        if cog and cog.has_error_handler():
            send_error_message = False

        title = exception.__class__.__name__
        msg = exception.args[0]
        if len(msg) > 3800:
            msg = msg[:3801] + "..."
        footer_text = exception.__class__.__name__

        log_exception = False
        has_cause = False

        if isinstance(
            exception, commands.CommandNotFound
        ):  # prevent potentially unintended command invocations
            return

        elif isinstance(exception, commands.BadArgument):
            title = "Invalid argument(s)!"
            msg = (
                f"{msg}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.UserInputError):
            title = "Invalid command input(s)!"
            msg = (
                f"{msg}\n\nFor help on bot commands, call `help <command>` with "
                "the correct prefix."
            )

        elif isinstance(exception, commands.DisabledCommand):
            title = f"Cannot execute command! ({exception.args[0]})"
            msg = (
                f"The specified command has been temporarily blocked from "
                "running, while the bot wizards are casting their spells on it!\n"
                "Please try running the command after the maintenance work "
                "has finished."
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

        if send_error_message:
            target_message = self._recent_error_messages.get(context.message.id)
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
                            context.channel,
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
                    context.channel,
                    title=title,
                    description=msg,
                    color=0xFF0000,
                    footer_text=footer_text,
                )

            self._recent_error_messages[
                context.message.id
            ] = target_message  # store updated message object

            snakecore.utils.hold_task(
                asyncio.create_task(
                    utils.message_delete_reaction_listener(
                        self,
                        target_message,
                        context.author,
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
                context.invoked_with
                if context.invoked_with
                else context.command.qualified_name,
                exc_info=main_exception,
            )

    async def on_command_completion(self, ctx: commands.Context):

        if ctx.message.id in self._recent_error_messages:
            try:
                await self._recent_error_messages[ctx.message.id].delete()
            except discord.NotFound:
                pass
            finally:
                del self._recent_error_messages[ctx.message.id]
