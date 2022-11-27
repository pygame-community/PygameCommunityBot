import asyncio
from collections import deque
import datetime
import glob
import io
import logging
import logging.handlers
import os
import platform
import random
import re
import time
from typing import Optional, Union

import discord
from discord.utils import _ColourFormatter
from discord.ext import commands, tasks
import psutil
import snakecore
from snakecore.commands.converters import CodeBlock, DateTime
from snakecore.commands.decorators import flagconverter_kwargs

from pcbot import constants, PygameCommunityBot, __version__ as bot_version
from pcbot.utils import (
    ANSI_FORMATTER,
    DEFAULT_FORMATTER,
    DEFAULT_FORMATTER_REGEX,
    DummyHandler,
    QueuingFilter,
)

from .base import BaseCommandCog

BotT = PygameCommunityBot

_root_logger = logging.getLogger()
_logger = logging.getLogger(__name__)

process = psutil.Process(os.getpid())


def is_bot_manager():
    async def predicate(ctx: commands.Context[BotT]) -> bool:
        if not (
            (
                isinstance(ctx.author, discord.Member)
                and (manager_role_ids := ctx.bot.config.get("manager_role_ids", ()))
                and any(role.id in manager_role_ids for role in ctx.author.roles)
            )
            or await ctx.bot.is_owner(ctx.author)
        ):
            raise commands.NotOwner("You're not a manager or owner of this bot.")
        return True

    return commands.check(predicate)


class BotManagement(BaseCommandCog, name="bot-management"):
    invoke_on_message_edit: bool = True

    def __init__(
        self,
        bot: BotT,
        theme_color: Union[int, discord.Color] = 0,
        log_directory: Optional[Union[str, os.PathLike]] = None,
        log_filename: Optional[str] = None,
        log_file_extension: Optional[str] = None,
        log_filename_glob: Optional[str] = None,
        status_channel_id: Optional[int] = None,
        invocation_log_channel_id: Optional[int] = None,
    ) -> None:
        super().__init__(bot, theme_color)
        self.bot: BotT = bot
        self.dummy_handler = DummyHandler()  # helper handler for queuing filters
        self.short_log_record_filter = QueuingFilter(maxlen=200)
        self.log_record_error_filter = QueuingFilter(
            queue_level=logging.ERROR, maxlen=100
        )

        if log_directory and not os.path.exists(log_directory):
            raise FileNotFoundError(
                f"The log directory '{log_directory}' does not exist"
            )

        self.log_directory = log_directory or self.bot.config.get("log_directory")
        self.log_filename = log_filename or self.bot.config.get(
            "log_filename", self.bot.__class__.__name__.lower()
        )
        self.log_file_extension = log_file_extension or self.bot.config.get(
            "log_file_extension", "log"
        )
        self.log_filename_glob = (
            log_filename_glob or f"{self.log_filename}*{self.log_file_extension}"
        )
        self.platform_info = platform.platform()
        self.short_log_record_queue = self.short_log_record_filter.queue
        self.short_log_record_error_queue = self.log_record_error_filter.queue
        self.status_channel: Optional[discord.TextChannel] = None
        self.status_channel_id = status_channel_id
        self.invocation_log_channel: Optional[discord.TextChannel] = None
        self.invocation_log_channel_id = invocation_log_channel_id
        self.status_message: Optional[discord.Message] = None
        self.bot_was_ready = False

    async def cog_load(self) -> None:
        if not self.log_directory:
            # delay log call to make it appear
            # in self.short_log_record_queue, after cog loading is complete
            asyncio.get_running_loop().call_later(
                0.5,
                lambda: _logger.warning(
                    "No log directory provided to BotManagement cog instance "
                    f"{hex(id(self))}: All bot commands involving log output "
                    "will be internally disabled."
                ),
            )
            self.logs.enabled = False
        _root_logger.addHandler(self.dummy_handler)
        self.dummy_handler.addFilter(self.short_log_record_filter)
        self.dummy_handler.addFilter(self.log_record_error_filter)
        self.bot_was_ready = self.bot.is_ready()

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context[BotT]):
        if not self.invocation_log_channel:
            return

        log_txt_file = None
        escaped_cmd_text = discord.utils.escape_markdown(ctx.message.content)
        if len(escaped_cmd_text) > 4095:
            with io.StringIO(ctx.message.content) as log_buffer:
                log_txt_file = discord.File(log_buffer, filename="command.txt")  # type: ignore

        await self.invocation_log_channel.send(
            embed=discord.Embed.from_dict(
                dict(
                    author=dict(
                        name=str(ctx.author),
                        icon_url=str(ctx.author.avatar or ctx.author.default_avatar),
                    ),
                    title=f"New Command Invocation (<t:{int(ctx.message.created_at.timestamp())}:f>)",
                    description=escaped_cmd_text
                    if len(escaped_cmd_text) <= 4095
                    else escaped_cmd_text[:2044] + "...",
                    color=int(self.theme_color),
                    fields=[
                        dict(
                            name="\u200b",
                            value=f"by {ctx.author.mention} "
                            f"(ID: {ctx.author.id})\n"
                            f"**[View Original]({ctx.message.jump_url})**",
                            inline=False,
                        ),
                    ],
                )
            ),
            file=log_txt_file,  # type: ignore
        )

    @tasks.loop(seconds=60, reconnect=False)
    async def update_status_message(self):
        next_refresh = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(seconds=60)

        recent_records = tuple(self.short_log_record_queue)
        first_record_dt = datetime.datetime.fromtimestamp(recent_records[0].created)
        last_record_dt = datetime.datetime.fromtimestamp(recent_records[-1].created)
        if self.status_message:
            await self.status_message.edit(
                embed=discord.Embed(
                    description="*Next log refresh (last updated on "
                    f"<t:{int((self.status_message.edited_at or self.status_message.created_at).timestamp())}:f>):* "  # type: ignore
                    f"**<t:{int(next_refresh.timestamp())}:R>**",  # type: ignore
                    color=0x36393F,
                ),
                attachments=[
                    discord.File(
                        io.StringIO(
                            "\n".join(
                                DEFAULT_FORMATTER.format(record)
                                for record in recent_records
                            )
                        ),  # type: ignore
                        filename=f"{self.log_filename}_"
                        f"{first_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}"
                        f"--{last_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}.log",
                    ),
                    discord.File(
                        io.StringIO(
                            "\n".join(
                                ANSI_FORMATTER.format(record)
                                for record in recent_records
                            )
                        ),  # type: ignore
                        filename=f"{self.log_filename}_"
                        f"{first_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}"
                        f"--{last_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}.log.ansi",
                    ),
                ],
            )
        else:
            self.status_message = await self.status_channel.send(  # type: ignore
                content="```ansi\n\u001b[1;32mBot Application Running\u001b[0m\n```"
                "```ansi\n"
                f"- Account: \u001b[0;33m{self.bot.user}\u001b[0m (ID: {self.bot.user.id})\n"  # type: ignore
                f"- Machine: \u001b[0;34m{self.platform_info}\u001b[0m\n"
                "```\n"
                "__**Logs**__\n",
                embed=discord.Embed(
                    description="*Next log refresh:* "
                    f"**<t:{int(next_refresh.timestamp())}:R>**",  # type: ignore
                    color=0x36393F,
                ),
                files=[
                    discord.File(
                        io.StringIO(
                            "\n".join(
                                DEFAULT_FORMATTER.format(record)
                                for record in recent_records
                            )
                        ),  # type: ignore
                        filename=f"{self.log_filename}_"
                        f"{first_record_dt.strftime('%Y-%m-%d %H-%M-%S')}"
                        f"--{last_record_dt.strftime('%Y-%m-%d %H-%M-%S')}.log",
                    ),
                    discord.File(
                        io.StringIO(
                            "\n".join(
                                ANSI_FORMATTER.format(record)
                                for record in recent_records
                            )
                        ),  # type: ignore
                        filename=f"{self.log_filename}_"
                        f"{first_record_dt.strftime('%Y-%m-%d %H-%M-%S')}"
                        f"--{last_record_dt.strftime('%Y-%m-%d %H-%M-%S')}.log.ansi",
                    ),
                ],
            )

        while self.short_log_record_error_queue:
            await self.status_message.reply(  # announce errors in extra separate messages
                content=f"```ansi\n{ANSI_FORMATTER.format(self.short_log_record_error_queue.popleft())}\n```"
            )

    async def prepare_status_reporting(self):
        if self.invocation_log_channel_id:
            self.invocation_log_channel = self.bot.get_channel(
                self.invocation_log_channel_id
            ) or await self.bot.fetch_channel(
                self.invocation_log_channel_id
            )  # type: ignore
            if not isinstance(
                self.invocation_log_channel, (discord.TextChannel, discord.Thread)
            ):
                raise TypeError(
                    "Command invocation log channel ID does not belong to a Discord guild text channel or thread"
                )
        if self.status_channel_id:
            self.status_channel = self.bot.get_channel(
                self.status_channel_id
            ) or await self.bot.fetch_channel(
                self.status_channel_id
            )  # type: ignore
            if not isinstance(
                self.status_channel, (discord.TextChannel, discord.Thread)
            ):
                raise TypeError(
                    "Status channel ID does not belong to a Discord guild text channel or thread"
                )
            self.update_status_message.start()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.bot_was_ready:
            self.bot_was_ready = True
            await self.prepare_status_reporting()

    @commands.Cog.listener()
    async def on_close(self):
        if self.status_message:
            self.status_message = await self.status_message.edit(
                content="```ansi\n\u001b[1;31mBot Application Closed\u001b[0m\n```"
                "```ansi\n"
                f"- Account: \u001b[0;33m{self.bot.user}\u001b[0m (ID: {self.bot.user.id})\n"  # type: ignore
                f"- Machine: \u001b[0;34m{self.platform_info}\u001b[0m\n"
                "```\n"
                "__**Logs**__\n"
            )
            await self.update_status_message()

    @commands.command()
    async def version(self, ctx: commands.Context[BotT]):
        """Get the current bot application version."""
        await ctx.send(
            embed=discord.Embed(
                title="Bot Version",
                description=f"`{bot_version}`",
                color=constants.DEFAULT_EMBED_COLOR,
            ),
        )

    @commands.is_owner()
    @commands.command(aliases=["stop"], hidden=True)
    async def shutdown(self, ctx: commands.Context[BotT]):
        await ctx.send(
            embed=discord.Embed(
                title="Shutting down...",
                description="Change da world,\nMy final message,\nGoodbye.",
                color=int(self.theme_color),
            )
        )
        snakecore.utils.hold_task(asyncio.create_task(ctx.bot.close()))

    @is_bot_manager()
    @commands.command(aliases=["heap"], hidden=True)
    async def memory(self, ctx: commands.Context[BotT]):
        mem = process.memory_info().rss
        await ctx.send(
            embed=discord.Embed(
                title="Total memory used:",
                description=f"**{snakecore.utils.format_byte(mem, 4)}**\n({mem} B)",
                color=int(self.theme_color),
            )
        )

    @commands.is_owner()
    @commands.command(hidden=True)
    async def eval(self, ctx: commands.Context[BotT], code: CodeBlock):
        try:
            script = compile(code.code, "<string>", "eval")  # compile script
            script_start = time.perf_counter()
            eval_output = eval(script)  # pylint: disable = eval-used
            total = time.perf_counter() - script_start
        except Exception as ex:
            raise commands.CommandInvokeError(
                commands.CommandError(
                    "An exception occured:\n"
                    + snakecore.utils.code_block(
                        type(ex).__name__ + ": " + ", ".join(map(str, ex.args))
                    )
                ),
            )
        await ctx.send(
            embed=discord.Embed(
                title=f"Return output (code executed in "
                f"{snakecore.utils.format_time_by_units(total)}):",
                description=snakecore.utils.code_block(repr(eval_output)),
                color=int(self.theme_color),
            ),
        )

    @is_bot_manager()
    @commands.command(
        usage="[flags [after: DateTime] [before: DateTime] [limit: Integer]]",
        extras=dict(invoke_on_message_edit=False),
        hidden=True,
    )
    @flagconverter_kwargs()
    async def logs(
        self,
        ctx: commands.Context[BotT],
        *,
        after: Optional[DateTime] = None,
        before: Optional[DateTime] = None,
        limit: Optional[int] = None,
    ):
        """Get the current log information of this bot application.

        **Parameters:**
            **`<flags ... >`**
                Flags for filtering the returned log records. If omitted, all log records are returned in files, each ≤ 8 MiB.

                • `[after: DateTime]`
                > A flag to limit log records to those newer than the specified date.

                • `[before: DateTime]`
                > A flag to limit log records to those older than the specified date.

                • `[limit: integer]`
                > A total limit on the amount of log records to retrieve.
        """
        if not self.log_directory:
            raise commands.CommandInvokeError(
                commands.CommandError("No log data was found.")
            )
        filenames = glob.glob(
            os.path.join(self.log_directory, self.log_filename_glob)
        )  # detect currently available log files
        if not filenames:
            raise commands.CommandInvokeError(
                commands.CommandError("No log data was found.")
            )

        if before is not None or after is not None or limit is not None:
            defer_writes = before is None and after is None and limit is not None
            inf = float("inf")
            before_ts = before.timestamp() if before else inf
            after_ts = after.timestamp() if after else 0.0
            strio = io.StringIO()
            record_strings = []
            record_matches = []
            _limit = limit or inf
            first_record_dt = None
            last_record_dt = None
            iso_dt = None

            total_record_writes = 0
            last_selected_match = None

            for filename in sorted(
                filenames,
                reverse=True,
            ):  # read oldest backups to newest
                with open(filename, "r", encoding="utf-8") as log_file:
                    maxtell = log_file.seek(0, io.SEEK_END)
                    log_file.seek(0)
                    previous_match_was_selected = False

                    while log_file.tell() < maxtell:
                        line = log_file.readline()
                        if match := re.match(DEFAULT_FORMATTER_REGEX, line):
                            iso_dt = datetime.datetime.fromisoformat(
                                match.group(1)
                            )  # read timestamp from line

                            if defer_writes:
                                record_strings.append(line)
                                record_matches.append(match)
                                last_selected_match = match
                                previous_match_was_selected = True
                            elif (
                                previous_match_was_selected := after_ts
                                < iso_dt.timestamp()
                                < before_ts
                            ):
                                if total_record_writes + 1 > _limit:
                                    break
                                strio.write(line)  # include line as it's within range
                                total_record_writes += 1
                                if not first_record_dt:
                                    first_record_dt = iso_dt

                                last_selected_match = match
                        elif previous_match_was_selected:
                            # line is from a trail of record-related text
                            # (e.g. error traceback), include it
                            if defer_writes:
                                record_strings[-1] += line
                            else:
                                strio.write(line)

            if (
                defer_writes and record_strings and record_matches
            ):  # record strings are sliced to
                # record string list is sliced to only pick x newest entries, where x equals a specified limit
                for string in record_strings[-limit:]:  # type: ignore
                    strio.write(string)
                    total_record_writes += 1

                if not first_record_dt:
                    first_record_dt = datetime.datetime.fromisoformat(
                        record_matches[-limit].group(1)  # type: ignore
                    )

            if last_selected_match:
                last_record_dt = datetime.datetime.fromisoformat(
                    last_selected_match.group(1)
                )

            if not strio.tell():
                raise commands.CommandInvokeError(
                    commands.CommandError(
                        "No log data was found for the specified range."
                    )
                )

            strio.seek(0)

            await ctx.send(
                content=f"Bot logs from **<t:{int(first_record_dt.timestamp())}:f>** "  # type: ignore
                f"to **<t:{int(last_record_dt.timestamp())}:f>** "  # type: ignore
                f"(**{total_record_writes}** total) :",
                file=discord.File(
                    strio,  # type: ignore
                    filename=f"{self.log_filename}_"
                    f"{first_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}"  # type: ignore
                    f"--{last_record_dt.strftime('%Y-%m-%d_%H-%M-%S')}.log",  # type: ignore
                ),
            )
        else:
            for filename in sorted(
                filenames, reverse=True, key=lambda fname: (len(fname), fname)
            ):  # sort by length, followed by size
                await ctx.send(
                    file=discord.File(filename),
                )

    @commands.command()
    async def ping(
        self,
        ctx: commands.Context[BotT],
    ):
        """Get the ping of the bot, including the current Discord API latency."""

        response_embed = discord.Embed(
            title=random.choice(("Pingy Pongy", "Pong!")),
            color=constants.DEFAULT_EMBED_COLOR,
        )

        response_message = await self.send_or_edit_response(ctx, embed=response_embed)

        timedelta = (response_message.edited_at or response_message.created_at) - (  # type: ignore
            ctx.message.edited_at or ctx.message.created_at
        )

        sec = timedelta.total_seconds()
        sec2 = self.bot.latency

        response_embed.description = (
            "The currently measured bot ping is "
            f"`{snakecore.utils.format_time_by_units(sec, decimal_places=0)}`\n"
            f"The Discord API latency is "
            f"`{snakecore.utils.format_time_by_units(sec2, decimal_places=0)}`"
        )

        await response_message.edit(embed=response_embed)


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    color: Union[int, discord.Color] = constants.DEFAULT_EMBED_COLOR,
    log_directory: Optional[Union[str, os.PathLike]] = None,
    log_filename: Optional[str] = None,
    log_file_extension: Optional[str] = None,
    log_filename_glob: Optional[str] = None,
    status_channel_id: Optional[int] = None,
    invocation_log_channel_id: Optional[int] = None,
):
    await bot.add_cog(
        BotManagement(
            bot,
            theme_color=color,
            log_directory=os.path.abspath(log_directory) if log_directory else None,
            log_filename=log_filename,
            log_file_extension=log_file_extension,
            log_filename_glob=log_filename_glob,
            status_channel_id=status_channel_id,
            invocation_log_channel_id=invocation_log_channel_id,
        )
    )
