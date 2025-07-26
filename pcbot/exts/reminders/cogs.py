import asyncio
import datetime
import logging
import re
from typing import TypedDict, Any, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks
import snakecore
from snakecore.commands import flagconverter_kwargs
from snakecore.commands.converters import (
    DateTime,
    String,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.engine import Result, Row
from dateutil.rrule import (
    rrule,
    rrulestr,
    DAILY,
    WEEKLY,
    MONTHLY,
    YEARLY,
    MO,
    TU,
    WE,
    TH,
    FR,
    SA,
    SU,
)
from dateutil.relativedelta import relativedelta

from ...bot import PygameCommunityBot
from ...base import BaseExtensionCog
from .constants import DB_PREFIX


BotT = PygameCommunityBot

_logger = logging.getLogger(__name__)


class ReminderRow(TypedDict):
    """A row from the reminders table."""

    uid: str
    """The bot uid that this reminder belongs to."""

    rid: int
    """Reminder ID, auto-incremented primary key."""

    next_time: datetime.datetime
    """When the reminder should next fire."""

    rrule: str | None
    """RFC 5545 recurrence rule string for recurring reminders."""

    recurrences: int
    """Number of times this reminder has fired."""

    expires_at: datetime.datetime | None
    """When the reminder expires, can be null if reminder does not expire."""

    creation_message_id: str | None
    """The message that created the reminder (if applicable), must be converted to int before use."""

    creation_messageable_id: str
    """The messageable location where reminders should be sent (if dm is false). Must be converted to int before use."""

    user_id: int
    """The user who set the reminder, must be converted to int before use."""

    dm: bool
    """Whether the reminder should fire as a DM to the user who set it."""

    title: str
    """Title of the reminder."""

    message: str | None
    """Text to relay along with the reminder in a dedicated Discord message."""

    message_mentions: bool
    """Whether the reminder message should trigger mentions upon being sent along with the reminder."""


invocation_error = lambda ctx, *args: (
    app_commands.CommandInvokeError(
        ctx.interaction.command, app_commands.AppCommandError(*args)
    )
    if ctx.interaction
    else commands.CommandInvokeError(commands.CommandError(*args))
)


class RemindersCog(BaseExtensionCog, name="user-reminders"):
    """A cog for managing personal reminders."""

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        revision_number: int,
        theme_color: int | discord.Color = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.db_engine = db_engine
        self.revision_number = revision_number
        self._reminder_task_running = False

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        if not self._reminder_task_running:
            self.check_reminders.start()
            self._reminder_task_running = True

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded."""
        if self._reminder_task_running:
            self.check_reminders.stop()
            self._reminder_task_running = False

    @tasks.loop(seconds=30)  # Check every 30 seconds
    async def check_reminders(self) -> None:
        """Background task to check for due reminders."""
        try:
            conn: AsyncConnection
            async with self.db_engine.connect() as conn:
                # Get all due reminders
                result: Result = await conn.execute(
                    text(
                        f"SELECT * FROM '{DB_PREFIX}reminders' "
                        "WHERE next_time <= :current_time"
                    ),
                    {"current_time": datetime.datetime.now(datetime.timezone.utc)},
                )

                reminders = result.fetchall()

                for reminder in reminders:
                    try:
                        await self._process_due_reminder(reminder)
                    except Exception as e:
                        _logger.error(f"Error processing reminder {reminder.rid}: {e}")

        except Exception as e:
            _logger.error(f"Error in check_reminders task: {e}")

    async def _process_due_reminder(self, reminder_row: Row[Any]) -> None:
        """Process a due reminder by sending messages and handling recurrence."""
        try:
            user = self.bot.get_user(reminder_row.user_id)
            if not user:
                try:
                    user = await self.bot.fetch_user(reminder_row.user_id)
                except discord.NotFound:
                    _logger.warning(
                        f"User {reminder_row.user_id} not found, deleting reminder {reminder_row.rid}"
                    )
                    await self._delete_reminder(reminder_row.rid)
                    return

            # Create reminder embed (first message)
            reminder_embed = discord.Embed(
                title="⏰ Reminder",
                description=f"**{reminder_row.title}**",
                color=self.theme_color,
                timestamp=reminder_row.next_time,
            )

            if (
                reminder_row.creation_message_id
                and reminder_row.creation_messageable_id
            ):
                try:
                    messageable_id = int(reminder_row.creation_messageable_id)
                    if reminder_row.dm:
                        # For DM reminders, the messageable could be the DM channel
                        messageable = user.dm_channel or await user.create_dm()
                    else:
                        # For guild reminders, get the channel
                        messageable = self.bot.get_channel(messageable_id)
                        if not messageable:
                            messageable = await self.bot.fetch_channel(messageable_id)

                    creation_message_url = f"https://discord.com/channels/"
                    guild = getattr(messageable, "guild", None)
                    if guild:
                        creation_message_url += f"{guild.id}/"
                    else:
                        creation_message_url += "@me/"
                    creation_message_url += (
                        f"{messageable_id}/{reminder_row.creation_message_id}"
                    )

                    reminder_embed.add_field(
                        name="Original Message",
                        value=f"[Jump to message]({creation_message_url})",
                        inline=False,
                    )
                except (ValueError, discord.NotFound, discord.Forbidden):
                    # If we can't access the original message, that's okay
                    pass

            # Send reminder embed
            try:
                if reminder_row.dm:
                    dm_channel = user.dm_channel or await user.create_dm()
                    await dm_channel.send(embed=reminder_embed)
                else:
                    # Send to the original channel
                    messageable_id = int(reminder_row.creation_messageable_id)
                    channel = self.bot.get_channel(messageable_id)
                    if isinstance(
                        channel,
                        (
                            discord.TextChannel,
                            discord.DMChannel,
                            discord.VoiceChannel,
                            discord.StageChannel,
                            discord.Thread,
                        ),
                    ):
                        await channel.send(f"[{user.mention}] **Reminder**: {reminder_row.title}\n\n-# Reminder ID: {reminder_row.rid}")  # type: ignore
                    else:
                        # Fallback to DM if channel not found or not sendable
                        dm_channel = user.dm_channel or await user.create_dm()
                        await dm_channel.send(embed=reminder_embed)

            except discord.Forbidden:
                _logger.warning(
                    f"Cannot send reminder to user {user.id}, insufficient permissions"
                )

            # Send message content if provided (second message)
            if reminder_row.message:
                try:
                    # Determine where to send the message
                    if reminder_row.dm:
                        dm_channel = user.dm_channel or await user.create_dm()
                        await dm_channel.send(
                            reminder_row.message,
                            allowed_mentions=(
                                discord.AllowedMentions(
                                    everyone=False, users=True, roles=False
                                )
                                if reminder_row.message_mentions
                                else discord.AllowedMentions.none()
                            ),
                        )
                    else:
                        messageable_id = int(reminder_row.creation_messageable_id)
                        channel = self.bot.get_channel(messageable_id)
                        if isinstance(
                            channel,
                            (
                                discord.TextChannel,
                                discord.DMChannel,
                                discord.VoiceChannel,
                                discord.StageChannel,
                                discord.Thread,
                            ),
                        ):
                            await channel.send(  # type: ignore
                                reminder_row.message,
                                allowed_mentions=(
                                    discord.AllowedMentions(
                                        everyone=False, users=True, roles=False
                                    )
                                    if reminder_row.message_mentions
                                    else discord.AllowedMentions.none()
                                ),
                            )
                        else:
                            # Fallback to DM if channel not found or not sendable
                            dm_channel = user.dm_channel or await user.create_dm()
                            await dm_channel.send(
                                reminder_row.message,
                                allowed_mentions=(
                                    discord.AllowedMentions(
                                        everyone=False, users=True, roles=False
                                    )
                                    if reminder_row.message_mentions
                                    else discord.AllowedMentions.none()
                                ),
                            )

                except discord.Forbidden:
                    _logger.warning(
                        f"Cannot send reminder message to user {user.id}, insufficient permissions"
                    )

            # Handle recurrence or deletion
            if reminder_row.rrule:
                # This is a recurring reminder, schedule next occurrence
                await self._schedule_next_occurrence(reminder_row)
            else:
                # One-time reminder, delete it
                await self._delete_reminder(reminder_row.rid)

        except Exception as e:
            _logger.error(f"Error processing reminder {reminder_row.rid}: {e}")
            # If there's an error, delete the reminder to prevent infinite loops
            await self._delete_reminder(reminder_row.rid)

    async def _schedule_next_occurrence(self, reminder_row: Row[Any]) -> None:
        """Schedule the next occurrence of a recurring reminder using RFC 5545 rules."""
        # If no rrule, this is not a recurring reminder
        if not reminder_row.rrule:
            await self._delete_reminder(reminder_row.rid)
            return

        try:
            # Parse the RRULE
            rule = rrulestr(reminder_row.rrule, dtstart=reminder_row.next_time)

            # Get the next occurrence after the current time
            now = datetime.datetime.now(datetime.timezone.utc)
            next_occurrence = rule.after(now, inc=False)

            if next_occurrence is None:
                # No more occurrences, delete the reminder
                await self._delete_reminder(reminder_row.rid)
                return

            # Update the reminder with the new time and increment recurrences
            conn: AsyncConnection
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text(
                        f"UPDATE '{DB_PREFIX}reminders' "
                        "SET next_time = :next_time, recurrences = recurrences + 1 "
                        "WHERE rid = :rid"
                    ),
                    dict(next_time=next_occurrence, rid=reminder_row.rid),
                )
        except Exception as e:
            _logger.error(f"Error parsing RRULE for reminder {reminder_row.rid}: {e}")
            # Delete invalid reminder
            await self._delete_reminder(reminder_row.rid)

    def _generate_rrule(
        self, pattern: str, start_time: datetime.datetime
    ) -> str | None:
        """Generate an RFC 5545 RRULE string from a recurrence pattern."""
        # Normalize case for comparison
        pattern_lower = pattern.lower()
        if pattern_lower == "none":
            return None

        # Ensure minimum 24-hour interval for all recurring reminders
        now = datetime.datetime.now(datetime.timezone.utc)
        if start_time <= now + datetime.timedelta(hours=24):
            # Adjust start time to be at least 24 hours from now
            start_time = now + datetime.timedelta(hours=24)

        freq_map = {
            "daily": DAILY,
            "weekly": WEEKLY,
            "monthly": MONTHLY,
            "yearly": YEARLY,
        }

        if pattern_lower not in freq_map:
            return None

        freq = freq_map[pattern_lower]

        # Create the rrule
        rule_kwargs = {"freq": freq, "dtstart": start_time}

        rule = rrule(**rule_kwargs)
        return str(rule).replace("RRULE:", "")  # Remove the RRULE: prefix

    def _validate_24_hour_minimum(
        self, start_time: datetime.datetime, recurring: str
    ) -> tuple[bool, str | None]:
        """Validate that recurring reminders have at least 24 hours from now."""
        if recurring.lower() == "none":
            return True, None

        now = datetime.datetime.now(datetime.timezone.utc)
        min_time = now + datetime.timedelta(hours=24)

        if start_time <= min_time:
            return (
                False,
                f"Recurring reminders must be set at least 24 hours in the future. Please choose a time after {min_time.strftime('%Y-%m-%d %H:%M UTC')}.",
            )

        return True, None

    def _validate_24_hour_minimum_new(
        self, start_time: datetime.datetime
    ) -> tuple[bool, str | None]:
        """Validate that recurring reminders have at least 24 hours from now."""
        now = datetime.datetime.now(datetime.timezone.utc)
        min_time = now + datetime.timedelta(hours=24)

        if start_time <= min_time:
            return (
                False,
                f"Recurring reminders must be set at least 24 hours in the future. Please choose a time after {min_time.strftime('%Y-%m-%d %H:%M UTC')}.",
            )

        return True, None

    def _generate_rrule_new(
        self,
        start_time: datetime.datetime,
        interval: int | None,
        iunit: (
            Literal[
                "days", "weeks", "months", "years", "Days", "Weeks", "Months", "Years"
            ]
            | None
        ),
        weekdays: list[int] | None,
        monthday: int | None,
    ) -> str | None:
        """Generate an RFC 5545 RRULE string from the new recurrence parameters."""
        # If no recurrence parameters specified, this is a one-time reminder
        if not any([interval, iunit, weekdays, monthday]):
            return None

        # Ensure minimum 24-hour interval for all recurring reminders
        now = datetime.datetime.now(datetime.timezone.utc)
        if start_time <= now + datetime.timedelta(hours=24):
            # Adjust start time to be at least 24 hours from now
            start_time = now + datetime.timedelta(hours=24)

        # Handle interval and unit
        if interval and iunit:
            freq_map = {
                "days": DAILY,
                "weeks": WEEKLY,
                "months": MONTHLY,
                "years": YEARLY,
                "Days": DAILY,
                "Weeks": WEEKLY,
                "Months": MONTHLY,
                "Years": YEARLY,
            }
            freq = freq_map[iunit]

            # Build kwargs based on what's provided
            kwargs = {"freq": freq, "dtstart": start_time}
            if interval > 1:
                kwargs["interval"] = interval
            if weekdays:
                kwargs["byweekday"] = weekdays
            if monthday:
                kwargs["bymonthday"] = monthday

            rule = rrule(**kwargs)
        elif weekdays:
            # Weekly recurrence based on weekdays only
            rule = rrule(freq=WEEKLY, dtstart=start_time, byweekday=weekdays)
        elif monthday:
            # Monthly recurrence based on monthday only
            rule = rrule(freq=MONTHLY, dtstart=start_time, bymonthday=monthday)
        elif interval:
            # Default to daily with interval
            rule = rrule(freq=DAILY, interval=interval, dtstart=start_time)
        else:
            # This shouldn't happen since we check at the top, but just in case
            return None

        return str(rule).replace("RRULE:", "")  # Remove the RRULE: prefix

    async def _delete_reminder(self, reminder_id: int) -> None:
        """Delete a reminder from the database."""
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM '{DB_PREFIX}reminders' WHERE rid = :rid"),
                dict(rid=reminder_id),
            )

    @commands.guild_only()
    @commands.group(invoke_without_command=True)
    async def reminders(self, ctx: commands.Context[BotT]):
        """Commands for managing personal reminders."""
        pass

    reminders_app_cmd_group = app_commands.Group(
        name="reminders",
        description="Commands for managing personal reminders.",
        guild_only=True,
    )

    @reminders.command(
        name="show",
        description="List your reminders with pagination.",
        extras=dict(response_deletion_with_reaction=True),
    )
    async def reminders_show(
        self,
        ctx: commands.Context[BotT],
    ):
        """List your reminders with pagination.

        Shows all your reminders with interactive pagination buttons.
        """
        return await self.reminders_show_func(ctx)

    @reminders_app_cmd_group.command(
        name="show",
        description="List your reminders with pagination.",
    )
    async def reminders_show_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
    ):
        return await self.reminders_show_func(
            await commands.Context[BotT].from_interaction(interaction)
        )

    async def reminders_show_func(self, ctx: commands.Context[BotT]) -> None:
        """Core function for listing user's reminders with pagination."""
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        # Check if user is admin
        is_admin = ctx.author.guild_permissions.administrator

        reminders_per_page = 5

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            # Get total count - all reminders for admins, only user's for regular users
            if is_admin:
                count_result = await conn.execute(
                    text(f"SELECT COUNT(*) FROM '{DB_PREFIX}reminders'"),
                )
                total_reminders = count_result.scalar() or 0
                title_prefix = "All Server Reminders"
            else:
                count_result = await conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM '{DB_PREFIX}reminders' WHERE user_id = :user_id"
                    ),
                    dict(user_id=ctx.author.id),
                )
                total_reminders = count_result.scalar() or 0
                title_prefix = "Your Reminders"

            if total_reminders == 0:
                embed = discord.Embed(
                    title=f"📝 {title_prefix}",
                    description=(
                        "No reminders found."
                        if is_admin
                        else "You don't have any reminders set."
                    ),
                    color=self.theme_color,
                )
                if ctx.interaction:
                    await ctx.interaction.response.send_message(
                        embed=embed, ephemeral=True
                    )
                else:
                    await self.send_or_edit_response(ctx, embed=embed)
                return

            # Get all reminders for pagination
            if is_admin:
                all_result = await conn.execute(
                    text(
                        f"SELECT * FROM '{DB_PREFIX}reminders' "
                        "ORDER BY next_time ASC"
                    ),
                )
            else:
                all_result = await conn.execute(
                    text(
                        f"SELECT * FROM '{DB_PREFIX}reminders' "
                        "WHERE user_id = :user_id "
                        "ORDER BY next_time ASC"
                    ),
                    dict(user_id=ctx.author.id),
                )
            all_reminders = all_result.fetchall()

            # Create embeds for each page
            embeds = []
            total_pages = (
                total_reminders + reminders_per_page - 1
            ) // reminders_per_page

            for page_num in range(1, total_pages + 1):
                start_idx = (page_num - 1) * reminders_per_page
                end_idx = start_idx + reminders_per_page
                page_reminders = all_reminders[start_idx:end_idx]

                embed = discord.Embed(
                    title=f"📝 {title_prefix}",
                    color=self.theme_color,
                )

                for reminder in page_reminders:
                    next_time = datetime.datetime.fromisoformat(reminder.next_time)
                    recurrence_info = ""
                    if reminder.rrule:
                        recurrence_info = (
                            f" (Recurring: {reminder.recurrences + 1} times)"
                        )

                    # For admins, show who created the reminder
                    user_info = ""
                    if is_admin:
                        try:
                            user = self.bot.get_user(reminder.user_id)
                            if user:
                                user_info = f" - Created by {user.mention}"
                            else:
                                user_info = f" - Created by <@{reminder.user_id}>"
                        except:
                            user_info = f" - Created by User ID {reminder.user_id}"

                    embed.add_field(
                        name=f"ID {reminder.rid}: {reminder.title}",
                        value=f"⏰ {snakecore.utils.create_markdown_timestamp(next_time, 'f')}"
                        f"{snakecore.utils.create_markdown_timestamp(next_time, 'R')}{recurrence_info}{user_info}",
                        inline=False,
                    )

                embeds.append(embed)

            # Always use pagination function
            if ctx.interaction:
                await ctx.interaction.response.defer(ephemeral=True)

            await self.send_paginated_response_embeds(ctx, *embeds)

    @reminders.command(
        name="add",
        usage="<DateTime> <title: String> [message: String] [interval: int] [iunit: days|weeks|months|years] [weekdays: monday|tuesday...] [monthday: Range[1, 31]]",
        description="Create a new reminder.",
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def reminders_add(
        self,
        ctx: commands.Context[BotT],
        time: DateTime,
        *,
        title: String[100],
        message: String[2000] | None = None,
        interval: int | None = None,
        iunit: (
            Literal[
                "days", "Days", "weeks", "Weeks", "months", "Months", "years", "Years"
            ]
            | None
        ) = None,
        weekdays: (
            tuple[
                Literal[
                    "Monday",
                    "monday",
                    "Tuesday",
                    "tuesday",
                    "Wednesday",
                    "wednesday",
                    "Thursday",
                    "thursday",
                    "Friday",
                    "friday",
                    "Saturday",
                    "saturday",
                    "Sunday",
                    "sunday",
                ]
            ]
            | None
        ) = None,
        monthday: commands.Range[int, 1, 31] | None = None,
        dm: bool = True,
    ):
        """Create a new reminder.

        __**Parameters:**__

        **`<time: DateTime>`**
        > The absolute time when the reminder should first trigger.
        > Examples: "2024-12-25 15:30", "`<t:2345654323456>`", "November 18th, 2069 12:30:30.55 am"

        **`<title: String>`**
        > Short title for the reminder (max 100 characters).

        **`[message: String]`**
        > Optional message to include with the reminder.

        "**`[interval: Number]`**
        > Optional interval value for the reminder.

        **`[iunit: days|weeks|months|years]`**
        > Optional interval unit. Examples: "days", "weeks", "months", "years"
        > If specified, the reminder will repeat at this interval.

        **`[weekdays: monday|tuesday|wednesday|thursday|friday|saturday|sunday...]`**
        > Optional weekdays on which the reminder should reoccur. If specified, the reminder will repeat on these days.

        **`[monthday: Range[1, 31]]`**
        > Optional day of the month on which the reminder should reoccur. If specified, the reminder will repeat on this day each month.

        **`[dm: bool]`**
        > Whether to send the reminder as a DM (True) or in the current channel (False). Defaults to True (DM).
        """

        # Validate parameters
        if interval is not None and interval <= 0:
            raise commands.BadArgument("interval must be a positive number")

        # Parse weekdays if provided
        parsed_weekdays = None
        if weekdays:
            weekday_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            try:
                parsed_weekdays = []
                for day in weekdays:
                    day_lower = day.lower()
                    if day_lower in weekday_map:
                        parsed_weekdays.append(weekday_map[day_lower])
                    else:
                        raise commands.BadArgument(f"Invalid weekday: {day}")
            except Exception:
                raise commands.BadArgument("weekdays must be valid weekday names")

        return await self.reminders_add_func(
            ctx, time, title, message, interval, iunit, parsed_weekdays, monthday, dm
        )

    @reminders_app_cmd_group.command(
        name="add",
        description="Create a new reminder.",
    )
    @app_commands.describe(
        time="When to send the reminder (e.g., 'tomorrow 3pm', 'Jan 15 2024')",
        title="Short title for the reminder (max 100 characters)",
        message="The reminder message (optional, max 2000 characters)",
        interval="Repeat interval (e.g., 2 for 'every 2 days')",
        iunit="Interval unit for recurrence",
        weekdays="Space-separated weekdays (e.g., 'monday friday')",
        monthday="Day of month for monthly recurrence (1-31)",
        dm="Send as DM (True) or in current channel (False)",
    )
    @app_commands.choices(
        iunit=[
            app_commands.Choice(name="days", value="days"),
            app_commands.Choice(name="weeks", value="weeks"),
            app_commands.Choice(name="months", value="months"),
            app_commands.Choice(name="years", value="years"),
            app_commands.Choice(name="Days", value="Days"),
            app_commands.Choice(name="Weeks", value="Weeks"),
            app_commands.Choice(name="Months", value="Months"),
            app_commands.Choice(name="Years", value="Years"),
        ]
    )
    async def reminders_add_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
        time: str,
        title: str,
        message: str | None = None,
        interval: int | None = None,
        iunit: (
            Literal[
                "days", "Days", "weeks", "Weeks", "months", "Months", "years", "Years"
            ]
            | None
        ) = None,
        weekdays: str | None = None,
        monthday: app_commands.Range[int, 1, 31] | None = None,
        dm: bool = False,
    ):
        # Convert string inputs to proper types
        ctx = await commands.Context[BotT].from_interaction(interaction)

        # Parse time using DateTime converter
        from snakecore.commands.converters import DateTimeConverter

        when_converter = DateTimeConverter()

        try:
            parsed_when = await when_converter.convert(ctx, time)
        except Exception as e:
            raise invocation_error(ctx, f"Failed to parse time") from e

        # Parse weekdays if provided
        parsed_weekdays = None
        if weekdays:
            weekday_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }

            parsed_weekdays = []
            for day in weekdays.lower().split():
                if day in weekday_map:
                    parsed_weekdays.append(weekday_map[day])
                else:
                    raise invocation_error(ctx, f"❌ Invalid weekday: {day}")

        return await self.reminders_add_func(
            ctx,
            parsed_when,
            title,
            message,
            interval,
            iunit,
            parsed_weekdays,
            monthday,
            dm,
        )

    async def reminders_add_func(
        self,
        ctx: commands.Context[BotT],
        time: datetime.datetime,
        title: str,
        message: str | None,
        interval: int | None,
        iunit: (
            Literal[
                "days", "weeks", "months", "years", "Days", "Weeks", "Months", "Years"
            ]
            | None
        ),
        weekdays: list[int] | None,
        monthday: int | None,
        dm: bool,
    ) -> None:
        """Core function for adding a new reminder."""
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        # Validate title length
        if len(title) > 100:
            raise (invocation_error(ctx, "Title must be 100 characters or fewer."))

        # Validate message length
        if message and len(message) > 2000:
            raise (invocation_error(ctx, "Message must be 2000 characters or fewer."))

        # Check if this is a recurring reminder
        is_recurring = any([interval, iunit, weekdays, monthday])

        # Validate 24-hour minimum for recurring reminders
        if is_recurring:
            is_valid, error_msg = self._validate_24_hour_minimum_new(time)
            if not is_valid:
                raise (invocation_error(ctx, error_msg))

        # Generate RRULE if recurring
        rrule_str = self._generate_rrule_new(time, interval, iunit, weekdays, monthday)

        # Create the reminder
        conn: AsyncConnection
        async with self.db_engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"INSERT INTO '{DB_PREFIX}reminders' "
                    "(uid, next_time, rrule, creation_messageable_id, user_id, dm, title, message, message_mentions) "
                    "VALUES (:uid, :next_time, :rrule, :creation_messageable_id, :user_id, :dm, :title, :message, :message_mentions) "
                    "RETURNING rid"
                ),
                dict(
                    uid=str(self.bot.uid),  # type: ignore
                    next_time=time,
                    rrule=rrule_str,
                    creation_messageable_id=str(ctx.channel.id),
                    user_id=ctx.author.id,
                    dm=dm,
                    title=title,
                    message=message,
                    message_mentions=False,
                ),
            )
            reminder_id = result.scalar()

        # Send confirmation
        recurrence_text = ""
        if is_recurring:
            recurrence_parts = []
            if interval and iunit:
                recurrence_parts.append(f"every {interval} {iunit}")
            if weekdays:
                weekday_names = [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
                day_names = [weekday_names[i] for i in weekdays]
                recurrence_parts.append(f"on {', '.join(day_names)}")
            if monthday:
                recurrence_parts.append(f"on day {monthday} of month")
            recurrence_text = f" ({'; '.join(recurrence_parts)})"

        embed = discord.Embed(
            title="Reminder Created",
            description=f"**{title}**\n⏰ {snakecore.utils.create_markdown_timestamp(time, 'f')}{snakecore.utils.create_markdown_timestamp(time, 'R')}{recurrence_text}",
            color=self.theme_color,
        )
        embed.set_footer(text=f"Reminder ID: {reminder_id}")

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await self.send_or_edit_response(ctx, embed=embed)

    @reminders.command(
        name="edit",
        usage="<reminder_id> [time: DateTime] [title: String] [message: String] [interval: int] [iunit: days|weeks|months|years] [weekdays: monday|tuesday...] [monthday: Range[1, 31]]",
        description="Edit an existing reminder.",
        extras=dict(response_deletion_with_reaction=True),
    )
    @flagconverter_kwargs()
    async def reminders_edit(
        self,
        ctx: commands.Context[BotT],
        reminder_id: int,
        *,
        time: DateTime | None = None,
        title: String[100] | None = None,
        message: String[2000] | None = None,
        interval: int | None = None,
        iunit: (
            Literal[
                "days", "Days", "weeks", "Weeks", "months", "Months", "years", "Years"
            ]
            | None
        ) = None,
        weekdays: (
            tuple[
                Literal[
                    "Monday",
                    "monday",
                    "Tuesday",
                    "tuesday",
                    "Wednesday",
                    "wednesday",
                    "Thursday",
                    "thursday",
                    "Friday",
                    "friday",
                    "Saturday",
                    "saturday",
                    "Sunday",
                    "sunday",
                ]
            ]
            | None
        ) = None,
        monthday: commands.Range[int, 1, 31] | None = None,
        dm: bool | None = None,
    ):
        """Edit an existing reminder.

        __**Parameters:**__

        **`<reminder_id: int>`**
        > The ID of the reminder to edit. Use `{PREFIX}reminders show` to see your reminder IDs.

        **`[time: DateTime]`**
        > New time for the reminder (optional). Cannot be changed if the reminder has already run.

        **`[title: String]`**
        > New title for the reminder (optional).

        **`[message: String]`**
        > New message for the reminder (optional). Use empty quotes "" to clear the message.

        **`[interval: Number]`**
        > Optional interval value for the reminder.

        **`[iunit: days|weeks|months|years]`**
        > Optional interval unit. Examples: "days", "weeks", "months", "years"
        > If specified, the reminder will repeat at this interval.

        **`[weekdays: monday|tuesday|wednesday|thursday|friday|saturday|sunday...]`**
        > Optional weekdays on which the reminder should reoccur. If specified, the reminder will repeat on these days.

        **`[monthday: Range[1, 31]]`**
        > Optional day of the month on which the reminder should reoccur. If specified, the reminder will repeat on this day each month.

        **`[dm: yes|no]`**
        > Whether to send the reminder as a DM (True) or in the current channel (False). Optional.
        """
        # Validate parameters
        if interval is not None and interval <= 0:
            raise commands.BadArgument("interval must be a positive number")

        # Parse weekdays if provided
        parsed_weekdays = None
        if weekdays:
            weekday_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }

            parsed_weekdays = []
            for day in weekdays:
                day_lower = day.lower()
                if day_lower in weekday_map:
                    parsed_weekdays.append(weekday_map[day_lower])
                else:
                    raise invocation_error(
                        ctx, commands.BadArgument(f"Invalid weekday: {day}")
                    )

        return await self.reminders_edit_func(
            ctx,
            reminder_id,
            time,
            title,
            message,
            interval,
            iunit,
            parsed_weekdays,
            monthday,
            dm,
        )

    @reminders_app_cmd_group.command(
        name="edit",
        description="Edit an existing reminder.",
    )
    @app_commands.describe(
        reminder_id="ID of the reminder to edit",
        time="New time for the reminder (optional)",
        title="New title for the reminder (optional)",
        message="New message for the reminder (optional)",
        interval="Repeat interval (e.g., 2 for 'every 2 days')",
        iunit="Interval unit for recurrence",
        weekdays="Space-separated weekdays (e.g., 'monday friday')",
        monthday="Day of month for monthly recurrence (1-31)",
        dm="Send as DM (True) or in current channel (False)",
    )
    @app_commands.choices(
        iunit=[
            app_commands.Choice(name="days", value="days"),
            app_commands.Choice(name="weeks", value="weeks"),
            app_commands.Choice(name="months", value="months"),
            app_commands.Choice(name="years", value="years"),
            app_commands.Choice(name="Days", value="Days"),
            app_commands.Choice(name="Weeks", value="Weeks"),
            app_commands.Choice(name="Months", value="Months"),
            app_commands.Choice(name="Years", value="Years"),
        ]
    )
    async def reminders_edit_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
        reminder_id: int,
        time: str | None = None,
        title: str | None = None,
        message: str | None = None,
        interval: int | None = None,
        iunit: (
            Literal[
                "days", "Days", "weeks", "Weeks", "months", "Months", "years", "Years"
            ]
            | None
        ) = None,
        weekdays: str | None = None,
        monthday: app_commands.Range[int, 1, 31] | None = None,
        dm: bool | None = None,
    ):
        # Convert string inputs to proper types
        ctx = await commands.Context[BotT].from_interaction(interaction)

        parsed_when = None
        if time:
            from snakecore.commands.converters import DateTimeConverter

            when_converter = DateTimeConverter()

            try:
                parsed_when = await when_converter.convert(ctx, time)
            except Exception as e:
                raise invocation_error(ctx, f"Failed to parse time") from e

        # Parse weekdays if provided
        parsed_weekdays = None
        if weekdays:
            weekday_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }

            parsed_weekdays = []
            for day in weekdays.lower().split():
                if day in weekday_map:
                    parsed_weekdays.append(weekday_map[day])
                else:
                    raise invocation_error(ctx, f"❌ Invalid weekday: {day}")

        return await self.reminders_edit_func(
            ctx,
            reminder_id,
            parsed_when,
            title,
            message,
            interval,
            iunit,
            parsed_weekdays,
            monthday,
            dm,
        )

    async def reminders_edit_func(
        self,
        ctx: commands.Context[BotT],
        reminder_id: int,
        time: datetime.datetime | None,
        title: str | None,
        message: str | None,
        interval: int | None,
        iunit: (
            Literal[
                "days", "weeks", "months", "years", "Days", "Weeks", "Months", "Years"
            ]
            | None
        ),
        weekdays: list[int] | None,
        monthday: int | None,
        dm: bool | None,
    ) -> None:
        """Core function for editing an existing reminder."""
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        is_admin = ctx.author.guild_permissions.administrator

        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            if is_admin:
                result = await conn.execute(
                    text(f"SELECT * FROM '{DB_PREFIX}reminders' WHERE rid = :rid"),
                    dict(rid=reminder_id),
                )
            else:
                # Regular users can only edit their own reminders
                result = await conn.execute(
                    text(
                        f"SELECT * FROM '{DB_PREFIX}reminders' "
                        "WHERE rid = :rid AND user_id = :user_id"
                    ),
                    dict(rid=reminder_id, user_id=ctx.author.id),
                )
            existing_reminder = result.fetchone()

            if not existing_reminder:
                raise (
                    invocation_error(
                        ctx,
                        f"Reminder {reminder_id} not found or you don't have permission to edit it.",
                    )
                )

        # Build update query dynamically based on provided parameters
        updates = []
        params: dict[str, Any] = {"rid": reminder_id}

        if time:
            # Check if reminder has already run (recurrences > 0)
            if existing_reminder.recurrences > 0:
                raise (
                    invocation_error(
                        ctx,
                        f"Cannot change the time of reminder {reminder_id} because it has already run {existing_reminder.recurrences} time(s). Create a new reminder instead.",
                    )
                )

            # Validate 24-hour minimum for recurring reminders
            if (
                any(
                    param is not None for param in (interval, iunit, weekdays, monthday)
                )
                or existing_reminder.rrule
            ):
                is_valid, error_msg = self._validate_24_hour_minimum_new(time)
                if not is_valid:
                    raise (invocation_error(ctx, error_msg))

            updates.append("next_time = :next_time")
            params["next_time"] = time

            # Generate RRULE if recurrence parameters are provided
            if any(
                param is not None for param in (interval, iunit, weekdays, monthday)
            ):
                rrule_str = self._generate_rrule_new(
                    time, interval, iunit, weekdays, monthday
                )
                updates.append("rrule = :rrule")
                params["rrule"] = rrule_str

        if title:
            if len(title) > 100:
                raise (invocation_error(ctx, "Title must be 100 characters or fewer."))
            updates.append("title = :title")
            params["title"] = title

        if message is not None:  # Allow empty string to clear message
            if len(message) > 2000:
                raise (
                    invocation_error(ctx, "Message must be 2000 characters or fewer.")
                )
            updates.append("message = :message")
            params["message"] = message

        if dm is not None:
            updates.append("dm = :dm")
            params["dm"] = dm

        # Handle recurrence updates without time change
        if time is None and any(
            param is not None for param in (interval, iunit, weekdays, monthday)
        ):
            # Update recurrence without changing time
            rrule_str = self._generate_rrule_new(
                existing_reminder.next_time, interval, iunit, weekdays, monthday
            )
            updates.append("rrule = :rrule")
            params["rrule"] = rrule_str

        if not updates:
            raise (invocation_error(ctx, "No changes specified."))

        # Execute update
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE '{DB_PREFIX}reminders' SET {', '.join(updates)} WHERE rid = :rid"
                ),
                params,
            )

        embed = discord.Embed(
            title="Reminder Updated",
            description=f"Reminder {reminder_id} has been updated successfully.",
            color=self.theme_color,
        )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await self.send_or_edit_response(ctx, embed=embed)

    @reminders.command(
        name="delete",
        aliases=["remove"],
        usage="<reminder_id>",
        description="Delete an existing reminder.",
        extras=dict(response_deletion_with_reaction=True),
    )
    async def reminders_delete(
        self,
        ctx: commands.Context[BotT],
        reminder_id: int,
    ):
        """Delete an existing reminder.

        __**Parameters:**__

        **`<reminder_id>`**
        > The ID of the reminder to delete. Use `{PREFIX}reminders show` to see your reminder IDs.
        """
        return await self.reminders_delete_func(ctx, reminder_id)

    @reminders_app_cmd_group.command(
        name="delete",
        description="Delete an existing reminder.",
    )
    @app_commands.describe(
        reminder_id="ID of the reminder to delete",
    )
    async def reminders_delete_app_cmd(
        self,
        interaction: discord.Interaction[BotT],
        reminder_id: int,
    ):
        ctx = await commands.Context[BotT].from_interaction(interaction)
        return await self.reminders_delete_func(ctx, reminder_id)

    async def reminders_delete_func(
        self,
        ctx: commands.Context[BotT],
        reminder_id: int,
    ) -> None:
        """Core function for deleting an existing reminder."""
        assert ctx.guild and isinstance(ctx.author, discord.Member)

        # Check if user is admin
        is_admin = ctx.author.guild_permissions.administrator

        # Check if reminder exists and belongs to user (or user is admin)
        conn: AsyncConnection
        async with self.db_engine.connect() as conn:
            if is_admin:
                # Admins can delete any reminder
                result = await conn.execute(
                    text(f"SELECT * FROM '{DB_PREFIX}reminders' WHERE rid = :rid"),
                    dict(rid=reminder_id),
                )
            else:
                # Regular users can only delete their own reminders
                result = await conn.execute(
                    text(
                        f"SELECT * FROM '{DB_PREFIX}reminders' "
                        "WHERE rid = :rid AND user_id = :user_id"
                    ),
                    dict(rid=reminder_id, user_id=ctx.author.id),
                )
            existing_reminder = result.fetchone()

            if not existing_reminder:
                raise (
                    invocation_error(
                        ctx,
                        f"Reminder {reminder_id} not found or you don't have permission to delete it.",
                    )
                )

        # Delete the reminder
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM '{DB_PREFIX}reminders' WHERE rid = :rid"),
                dict(rid=reminder_id),
            )

        embed = discord.Embed(
            title="Reminder Deleted",
            description=f"Reminder {reminder_id} (**{existing_reminder.title}**) has been deleted successfully.",
            color=self.theme_color,
        )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await self.send_or_edit_response(ctx, embed=embed)
