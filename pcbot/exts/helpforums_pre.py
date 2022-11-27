from __future__ import annotations
import asyncio
import datetime
import itertools
import pickle
import re
import time

from typing import TYPE_CHECKING, Optional, TypedDict, Union

import discord
from discord.ext import commands, tasks
from packaging.version import Version
import snakecore
from sqlalchemy.ext.asyncio import AsyncEngine

from .. import __version__
from .base import BaseCommandCog
from ..bot import PygameCommunityBot

if TYPE_CHECKING:
    from typing_extensions import NotRequired

BotT = PygameCommunityBot

DB_TABLE_PREFIX = f"{__name__}:"


CAUTION_WHILE_MESSAGING_COOLDOWN: int = 900
THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY: int = 300
THREAD_TITLE_MINIMUM_LENGTH: int = 16
FORUM_THREAD_TAG_LIMIT = 5


class BadHelpThreadData(TypedDict):
    thread_id: int
    last_cautioned_ts: float
    alert_message_ids: set[int]


class InactiveHelpThreadData(TypedDict):
    thread_id: int
    last_active_ts: float
    alert_message_id: NotRequired[int]


HELP_FORUM_CHANNEL_IDS = {
    "newbies": 1022292223708110929,  # newbies-help-🔰
    "regulars": 1019741232810954842,  # regulars-pygame-help
    "python": 1022244052088934461,  # python-help
}

INVALID_HELP_THREAD_TITLE_TYPES = {
    "thread_title_too_short",
    "member_asking_for_help",
    "member_exclaiming_about_not_working_code",
    "member_asking_for_code",
    "member_asking_about_problem_with_code",
}

INVALID_HELP_THREAD_TITLE_SCANNING_ENABLED = {
    "thread_title_too_short": True,
    "member_asking_for_help": True,
    "member_exclaiming_about_not_working_code": True,
    "member_asking_for_code": True,
    "member_asking_about_problem_with_code": True,
}
INVALID_HELP_THREAD_TITLE_REGEX_PATTERNS = {
    "thread_title_too_short": re.compile(
        r"^(.){1," f"{THREAD_TITLE_MINIMUM_LENGTH-1}" r"}$", flags=re.IGNORECASE
    ),
    "member_asking_for_help": re.compile(
        r"[\s]*(^help\s*|help\?*?$|(can|does|is\s+)?(pl(ease|s)|(some|any)(one|body)|you|(need|want)|(can|(want|available|around|willing|ready)(\s*to)))\s*help)(?!(s|ed|er|ing))(\s*me(\s*please)?|pl(ease|s)|with)?\s*",
        re.IGNORECASE,
    ),
    "member_exclaiming_about_not_working_code": re.compile(
        r"[\s]*((why\s+)?(is('nt)?|does(\s+not|'nt)?)?\s*(my|the|this)?)\s*(this|code|game|pygame(\s*(game|program|code|project|assignment)?))\s*(((is|does)(\s*not|n't)?|not)\s*work(s|ed|ing)?)",
        re.IGNORECASE,
    ),
    "member_asking_for_code": re.compile(
        r"(?<!How\s)(?<!How\sdo\s)(?<!How\sdoes\s)(?<!I\s)((can('t|not)?|will)\s+)?(?<!How\scan\s)(please|pls|(some|any)(one|body)|(available|around|willing|ready|want)(\s*to))(\s*help(\s*me)?)?\s*(write|make|create|code|program|fix|correct|implement)(?!ing|ed)(\s*(a|my|the|this))?\s*(this|code|game|pygame(\s*(game|program|code)?))?\s*(for)?\s*(me(\s*please)?|please)?\s*",
        re.IGNORECASE,
    ),
    "member_asking_about_problem_with_code": re.compile(
        r"[\s]*((why|what('s)?\s+)(is('nt)?|does(\s+not|'nt)|am\s*i\s*(doing|having))?\s*((wrong|the\s*(problem|issue))?\s*(with(in)?|in(side)?)\s*)?(my|the|this)?)\s*(this|code|game|pygame(\s*(game|program|code)?))\s*",
        re.IGNORECASE,
    ),
}
INVALID_HELP_THREAD_TITLE_EMBEDS = {
    "thread_title_too_short": {
        "title": "Whoops, your post title must be at least "
        f"{THREAD_TITLE_MINIMUM_LENGTH} characters long (excluding numbers)",
        "description": "Your post title must be at least "
        f"**{THREAD_TITLE_MINIMUM_LENGTH}** characters long, so I'm "
        "forced to put a slowmode delay of "
        f"{THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY//60} minute{'s'*(THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY > 60)} "
        " on your post (sorry) <:pg_sad:863165920038223912>.\n\n"
        "To make changes to your post's title, either right-click on it "
        "(desktop/web) or click and hold on it (mobile), then click on "
        "**'Edit Post'**. Use the input field called 'POST TITLE' in the "
        "post settings menu to change your post title. Remember to save "
        "your changes.\n\n"
        "**Thank you for helping us maintain clean help forum channels "
        "<:pg_robot:837389387024957440>**\n\n"
        "This alert and the slowmode should disappear after you have made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_for_help": {
        "title": "Please don't ask for help in your post title (no need to). "
        "We'd love to help you either way!",
        "description": "Instead of asking for help or mentioning that you need "
        "help, please write a post title and starter message "
        "that describes the actual issue you're having in more detail.\n"
        "Also send code snippets (no code screenshots), screenshots and "
        "other media, error messages, etc."
        "\n\n**[Here's why!](https://www.dontasktoask.com)**\n\n"
        "To make changes to your post's title, either right-click on it "
        "(desktop/web) or click and hold on it (mobile), then click on "
        "**'Edit Post'**. Use the input field called 'POST TITLE' in the "
        "post settings menu to change your post title. Remember to save "
        "your changes.\n\n"
        "This alert should disappear after you have made appropriate changes.",
        "color": 0x36393F,
    },
    "member_exclaiming_about_not_working_code": {
        "title": "Something doesn't work? Please tell us what.",
        "description": "Edit your help post title and your starter message "
        "to describe the problem that led to that diagnosis. What made your code "
        "stop working? What are you trying to do?\n"
        "Remember to send along code snippets (no code screenshots), screenshots "
        "and other media, error messages, etc.\n\n"
        "To make changes to your post's title, either right-click on it "
        "(desktop/web) or click and hold on it (mobile), then click on "
        "**'Edit Post'**. Use the input field called 'POST TITLE' in the "
        "post settings menu to change your post title. Remember to save "
        "your changes.\n\n"
        "This alert should disappear after you have made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_for_code": {
        "title": "Please don't ask if anybody can, wants to, or will fix, correct "
        "or write your code, game, project or assignment for you.",
        "description": "All helpers here are volunteers, who show people how to "
        "improve or implement things in their code by themselves. They don't do "
        "all the work for them. Show us what you are working on, what you've "
        "tried, as well as where you got stuck. "
        "Remember to send along code snippets (no code screenshots), screenshots "
        "and other media, error messages, etc.\n\n"
        "To make changes to your post's title, either right-click on it "
        "(desktop/web) or click and hold on it (mobile), then click on "
        "**'Edit Post'**. Use the input field called 'POST TITLE' in the "
        "post settings menu to change your post title. Remember to save "
        "your changes.\n\n"
        "This alert should disappear after you have made appropriate changes.",
        "color": 0x36393F,
    },
    "member_asking_about_problem_with_code": {
        "title": "There's a problem with your code, game, project or assignment? "
        "Please tell us what are you struggling with.",
        "description": "Use your help post title and your starter message "
        "to describe how the problems with it came up. What made your code stop "
        "working? What are you trying to do? "
        "Remember to send along code snippets (no code screenshots), screenshots "
        "and other media, error messages, etc.\n\n"
        "To make changes to your post's title, either right-click on it "
        "(desktop/web) or click and hold on it (mobile), then click on "
        "**'Edit Post'**. Use the input field called 'POST TITLE' in the "
        "post settings menu to change your post title. Remember to save "
        "your changes.\n\n"
        "This alert should disappear after you have made appropriate changes.",
        "color": 0x36393F,
    },
}


class HelpForumsPre(BaseCommandCog, name="helpforums-pre"):
    def __init__(self, bot: BotT, theme_color: Union[int, discord.Color] = 0) -> None:
        super().__init__(bot, theme_color=theme_color)
        self.bot: BotT
        self.bad_help_thread_data: dict[int, BadHelpThreadData] = {}
        self.inactive_help_thread_data: dict[int, InactiveHelpThreadData] = {}

    async def cog_load(self) -> None:
        help_thread_data = await self.bot.read_extension_data(__name__)
        self.bad_help_thread_data = help_thread_data.get("bad_help_thread_data", {})  # type: ignore
        self.inactive_help_thread_data = help_thread_data.get("bad_help_thread_data", {})  # type: ignore

    async def cog_unload(self) -> None:
        self.inactive_help_thread_alert.stop()
        self.force_help_thread_archive_after_timeout.stop()
        self.delete_help_threads_without_starter_message.stop()

        task_objs = []
        for task_obj in (
            self.inactive_help_thread_alert.get_task(),
            self.force_help_thread_archive_after_timeout.get_task(),
            self.delete_help_threads_without_starter_message.get_task(),
        ):
            if task_obj:
                task_objs.append(task_obj)

        if task_objs:
            await asyncio.gather(*task_objs, return_exceptions=True)

        dumped_help_thread_data = pickle.dumps(
            {
                "bad_help_thread_data": self.bad_help_thread_data,
                "inactive_help_thread_data": self.inactive_help_thread_data,
            }
        )
        await self.bot.update_extension_data(__name__, data=dumped_help_thread_data)

    @commands.Cog.listener()
    async def on_ready(self):
        for task_loop in (
            self.inactive_help_thread_alert,
            self.force_help_thread_archive_after_timeout,
            self.delete_help_threads_without_starter_message,
        ):
            if not task_loop.is_running():
                task_loop.start()

    @commands.Cog.listener()
    async def on_message_delete(self, msg: discord.Message):
        if (
            isinstance(msg.channel, discord.Thread)
            and msg.channel.parent_id in HELP_FORUM_CHANNEL_IDS.values()
            and msg.id == msg.channel.id  # OP deleted starter message
        ):
            await self.help_thread_deletion_checks(msg.channel)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id in HELP_FORUM_CHANNEL_IDS.values():
            caution_messages: list[discord.Message] = []
            issues_found = False
            thread_edits = {}
            try:
                await (
                    thread.starter_message
                    if thread.starter_message and thread.starter_message.id == thread.id
                    else (await thread.fetch_message(thread.id))
                ).pin()

                parent = (
                    thread.parent
                    or self.bot.get_channel(thread.parent_id)
                    or await self.bot.fetch_channel(thread.parent_id)
                )

                if (
                    len((applied_tags := thread.applied_tags)) < FORUM_THREAD_TAG_LIMIT
                    or len(applied_tags) == FORUM_THREAD_TAG_LIMIT
                    and any(
                        tag.name.lower().startswith("solved") for tag in applied_tags
                    )
                ):
                    new_tags = [
                        tag
                        for tag in applied_tags
                        if not tag.name.lower().startswith("solved")
                    ]

                    for tag in parent.available_tags:  # type: ignore
                        if tag.name.lower().startswith("unsolved"):
                            new_tags.insert(0, tag)  # mark help post as unsolved
                            break

                    thread_edits["applied_tags"] = new_tags

                if caution_types := self.get_help_forum_channel_thread_name_cautions(
                    thread
                ):
                    issues_found = True
                    caution_messages.extend(
                        await self.caution_about_help_forum_channel_thread_name(
                            thread, *caution_types
                        )
                    )
                    if "thread_title_too_short" in caution_types:
                        thread_edits.update(
                            dict(
                                slowmode_delay=THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY,
                                reason="Slowmode penalty for the title of this help post being too short.",
                            )
                        )
                if thread.parent_id == HELP_FORUM_CHANNEL_IDS["regulars"]:
                    if not self.validate_regulars_help_forum_channel_thread_tags(
                        thread
                    ):
                        issues_found = True
                        caution_messages.append(
                            await self.caution_about_regulars_help_forum_channel_thread_tags(
                                thread
                            )
                        )

                if issues_found and thread.id not in self.bad_help_thread_data:
                    self.bad_help_thread_data[thread.id] = {
                        "thread_id": thread.id,
                        "last_cautioned_ts": time.time(),
                        "alert_message_ids": set(msg.id for msg in caution_messages),
                    }

                owner_id_suffix = f" | {thread.owner_id}"
                if not (
                    thread.name.endswith(owner_id_suffix)
                    or str(thread.owner_id) in thread.name
                ):
                    thread_edits["name"] = (
                        thread.name
                        if len(thread.name) < 72
                        else thread.name[:72] + "..."
                    ) + owner_id_suffix

                if thread_edits:
                    await thread.edit(**thread_edits)

            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if after.parent_id in HELP_FORUM_CHANNEL_IDS.values():
            try:
                assert self.bot.user
                owner_id_suffix = f" | {after.owner_id}"
                if not (after.archived or after.locked):
                    thread_edits = {}
                    caution_messages: list[discord.Message] = []
                    bad_thread_name = False
                    bad_thread_tags = False

                    updater_id = None

                    async for action in after.guild.audit_logs(
                        limit=20, action=discord.AuditLogAction.thread_update
                    ):
                        if (target := action.target) and target.id == after.id:
                            if action.user:
                                updater_id = action.user.id
                                break

                    if before.name != after.name and updater_id != self.bot.user.id:  # type: ignore
                        if caution_types := self.get_help_forum_channel_thread_name_cautions(
                            after
                        ):
                            bad_thread_name = True
                            caution_messages.extend(
                                await self.caution_about_help_forum_channel_thread_name(
                                    after, *caution_types
                                )
                            )
                            if (
                                "thread_title_too_short" in caution_types
                                and after.slowmode_delay
                                < THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY
                            ):
                                thread_edits.update(
                                    dict(
                                        slowmode_delay=THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY,
                                        reason="Slowmode penalty for the title of this "
                                        "help post being too short.",
                                    )
                                )
                            elif (
                                after.slowmode_delay
                                == THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY
                            ):
                                thread_edits.update(
                                    dict(
                                        slowmode_delay=(
                                            after.parent
                                            or self.bot.get_channel(after.parent_id)
                                            or await self.bot.fetch_channel(
                                                after.parent_id
                                            )
                                        ).default_thread_slowmode_delay,  # type: ignore
                                        reason="This help post's title is not too short anymore.",
                                    )
                                )

                    elif (
                        before.applied_tags != after.applied_tags
                        and updater_id != self.bot.user.id
                    ):
                        if after.parent_id == HELP_FORUM_CHANNEL_IDS["regulars"]:
                            if not self.validate_regulars_help_forum_channel_thread_tags(
                                after
                            ):
                                bad_thread_tags = True
                                caution_messages.append(
                                    await self.caution_about_regulars_help_forum_channel_thread_tags(
                                        after
                                    )
                                )

                    if bad_thread_name or bad_thread_tags:
                        if after.id not in self.bad_help_thread_data:
                            self.bad_help_thread_data[after.id] = {
                                "thread_id": after.id,
                                "last_cautioned_ts": time.time(),
                                "alert_message_ids": set(
                                    msg.id for msg in caution_messages
                                ),
                            }
                        self.bad_help_thread_data[after.id][
                            "last_cautioned_ts"
                        ] = time.time()
                        self.bad_help_thread_data[after.id]["alert_message_ids"].update(
                            (msg.id for msg in caution_messages)
                        )
                    else:
                        if (
                            after.id in self.bad_help_thread_data
                            and updater_id != self.bot.user.id
                        ):
                            if (
                                after.slowmode_delay
                                == THREAD_TITLE_TOO_SHORT_SLOWMODE_DELAY
                            ):
                                thread_edits.update(
                                    dict(
                                        slowmode_delay=(
                                            after.parent
                                            or self.bot.get_channel(after.parent_id)
                                            or await self.bot.fetch_channel(
                                                after.parent_id
                                            )
                                        ).default_thread_slowmode_delay,  # type: ignore
                                        reason="This help post's title is not invalid anymore.",
                                    )
                                )

                            for msg_id in tuple(
                                self.bad_help_thread_data[after.id]["alert_message_ids"]
                            ):
                                try:
                                    await after.get_partial_message(msg_id).delete()
                                except discord.NotFound:
                                    pass

                            if (
                                after.id in self.bad_help_thread_data
                            ):  # fix concurrency bugs where key was already deleted
                                del self.bad_help_thread_data[after.id]

                        solved_in_before = any(
                            tag.name.lower().startswith("solved")
                            for tag in before.applied_tags
                        )
                        solved_in_after = any(
                            tag.name.lower().startswith("solved")
                            for tag in after.applied_tags
                        )
                        if not solved_in_before and solved_in_after:
                            new_tags = [
                                tag
                                for tag in after.applied_tags
                                if not tag.name.lower().startswith("unsolved")
                            ]
                            await self.send_help_thread_solved_alert(after)
                            thread_edits.update(
                                dict(
                                    auto_archive_duration=60,
                                    reason="This help post was marked as solved.",
                                    applied_tags=new_tags,
                                )
                            )

                            if after.id in self.inactive_help_thread_data:
                                try:
                                    if alert_message_id := self.inactive_help_thread_data[
                                        after.id
                                    ].get(
                                        "alert_message_id", None
                                    ):
                                        try:
                                            await after.get_partial_message(
                                                alert_message_id
                                            ).delete()
                                        except discord.NotFound:
                                            pass
                                finally:
                                    del self.inactive_help_thread_data[after.id]

                        elif solved_in_before and not solved_in_after:
                            parent = (
                                after.parent
                                or self.bot.get_channel(after.parent_id)
                                or await self.bot.fetch_channel(after.parent_id)
                            )  # type: ignore

                            new_tags = after.applied_tags
                            if len(new_tags) < FORUM_THREAD_TAG_LIMIT:
                                for tag in parent.available_tags:
                                    if tag.name.lower().startswith("unsolved"):
                                        new_tags.insert(
                                            0, tag
                                        )  # mark help post as unsolved
                                        break

                            slowmode_delay = discord.utils.MISSING
                            if (
                                after.slowmode_delay == 60
                            ):  # no custom slowmode override
                                slowmode_delay = parent.default_thread_slowmode_delay

                            thread_edits.update(
                                dict(
                                    auto_archive_duration=parent.default_auto_archive_duration,
                                    slowmode_delay=slowmode_delay,
                                    reason="This help post was unmarked as solved.",
                                    applied_tags=new_tags,
                                )
                            )

                    if thread_edits:
                        await asyncio.sleep(5)
                        await after.edit(
                            **thread_edits
                        )  # apply edits in a batch to save API calls

                elif after.archived and not after.locked:
                    if any(
                        tag.name.lower().startswith("solved")
                        for tag in after.applied_tags
                    ):
                        thread_edits = {}
                        parent: discord.ForumChannel = (
                            after.parent
                            or self.bot.get_channel(after.parent_id)
                            or await self.bot.fetch_channel(after.parent_id)
                        )  # type: ignore
                        if (
                            after.slowmode_delay == parent.default_thread_slowmode_delay
                        ):  # no custom slowmode override
                            thread_edits["slowmode_delay"] = 60

                        if not (
                            after.name.endswith(owner_id_suffix)
                            or str(after.owner_id) in after.name
                        ):  # wait for a few event loop iterations, before doing a second,
                            # check, to be sure that a bot edit hasn't already occured
                            thread_edits["name"] = (
                                after.name
                                if len(after.name) < 72
                                else after.name[:72] + "..."
                            ) + owner_id_suffix

                        if thread_edits:
                            await after.edit(archived=False)
                            await asyncio.sleep(5)
                            thread_edits["archived"] = True
                            await after.edit(**thread_edits)

            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent):
        if payload.thread_id in self.inactive_help_thread_data:
            del self.inactive_help_thread_data[payload.thread_id]

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        try:
            if not snakecore.utils.is_emoji_equal(payload.emoji, "✅"):
                return

            channel = self.bot.get_channel(
                payload.channel_id
            ) or await self.bot.fetch_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread):
                return

            msg = await channel.fetch_message(payload.message_id)
            if (
                channel.parent_id in HELP_FORUM_CHANNEL_IDS.values()
                and not channel.flags.pinned
            ):

                white_check_mark_reaction = discord.utils.find(
                    lambda r: isinstance(r.emoji, discord.PartialEmoji)
                    and snakecore.utils.is_emoji_equal(r.emoji, "✅"),
                    msg.reactions,
                )

                by_op = payload.user_id == channel.owner_id
                by_admin = (
                    payload.member and payload.member.guild_permissions.administrator
                )
                if not msg.pinned and (
                    by_op
                    or payload.member
                    and payload.member.guild_permissions.administrator
                ):
                    await msg.pin(
                        reason="The owner of this message's thread has marked it as helpful."
                        if by_op
                        else "An admin has marked this message as helpful."
                    )
                elif payload.user_id == msg.author.id and msg.id != channel.id:
                    await msg.remove_reaction("✅", msg.author)

                elif not msg.pinned and (
                    white_check_mark_reaction and white_check_mark_reaction.count >= 4
                ):
                    await msg.pin(
                        reason="Multiple members of this message's thread "
                        "have marked it as helpful."
                    )

                if (
                    msg.id == channel.id
                    and (by_op or by_admin)
                    and channel.applied_tags
                    and not any(
                        tag.name.lower() in ("solved", "invalid")
                        for tag in channel.applied_tags
                    )
                ) and len(
                    channel.applied_tags
                ) < FORUM_THREAD_TAG_LIMIT:  # help post should be marked as solved
                    for tag in (
                        channel.parent
                        or self.bot.get_channel(channel.parent_id)
                        or await self.bot.fetch_channel(channel.parent_id)
                    ).available_tags:  # type: ignore
                        if tag.name.lower().startswith("solved"):
                            new_tags = [
                                tg
                                for tg in channel.applied_tags
                                if tg.name.lower() != "unsolved"
                            ]
                            new_tags.append(tag)

                            await channel.edit(
                                reason="This help post was marked as solved by "
                                + ("the OP" if by_op else "an admin")
                                + " (via a ✅ reaction).",
                                applied_tags=new_tags,
                            )
                            break

        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        try:
            if not snakecore.utils.is_emoji_equal(payload.emoji, "✅"):
                return

            channel = self.bot.get_channel(
                payload.channel_id
            ) or await self.bot.fetch_channel(payload.channel_id)
            if not isinstance(channel, discord.Thread):
                return

            msg = await channel.fetch_message(payload.message_id)
            if (
                isinstance(msg.channel, discord.Thread)
                and msg.channel.parent_id in HELP_FORUM_CHANNEL_IDS.values()
            ):
                if not snakecore.utils.is_emoji_equal(payload.emoji, "✅"):
                    return

                white_check_mark_reaction = discord.utils.find(
                    lambda r: isinstance(r.emoji, discord.PartialEmoji)
                    and snakecore.utils.is_emoji_equal(r.emoji, "✅"),
                    msg.reactions,
                )

                by_op = payload.user_id == channel.owner_id
                by_admin = (
                    payload.member and payload.member.guild_permissions.administrator
                )

                if msg.pinned and (
                    (
                        not white_check_mark_reaction
                        or white_check_mark_reaction
                        and (
                            white_check_mark_reaction.count < 4
                            or white_check_mark_reaction.count < 2
                            and by_admin
                        )
                    )
                ):
                    await msg.unpin(
                        reason="Multiple members of this message's thread "
                        "have unmarked it as helpful."
                    )

                if (
                    msg.id == msg.channel.id
                    and (by_op or by_admin)
                    and msg.channel.applied_tags
                    and any(
                        tag.name.lower().startswith("solved")
                        for tag in msg.channel.applied_tags
                    )
                ):  # help post should be unmarked as solved
                    for tag in (
                        msg.channel.parent
                        or self.bot.get_channel(msg.channel.parent_id)
                        or await self.bot.fetch_channel(msg.channel.parent_id)
                    ).available_tags:  # type: ignore
                        if tag.name.lower().startswith("solved"):
                            await msg.channel.remove_tags(
                                tag,
                                reason="This help post was unmarked as solved by "
                                + ("the OP" if by_op else "an admin")
                                + " (via removing a ✅ reaction).",
                            )
                            break
        except discord.HTTPException:
            pass

    @tasks.loop(hours=1, reconnect=True)
    async def inactive_help_thread_alert(self):
        for forum_channel in [
            self.bot.get_channel(fid) or (await self.bot.fetch_channel(fid))
            for fid in HELP_FORUM_CHANNEL_IDS.values()
        ]:
            if not isinstance(forum_channel, discord.ForumChannel):
                return

            now_ts = time.time()
            for help_thread in itertools.chain(
                forum_channel.threads,
                [thr async for thr in forum_channel.archived_threads(limit=20)],
            ):
                try:
                    if not help_thread.created_at:
                        continue
                    last_active_ts = help_thread.created_at.timestamp()

                    if not (help_thread.locked or help_thread.flags.pinned) and not any(
                        tag.name.lower().startswith("solved")
                        for tag in help_thread.applied_tags
                    ):
                        last_active_ts = (
                            await self.fetch_last_thread_activity_dt(help_thread)
                        ).timestamp()

                        if (now_ts - last_active_ts) > (3600 * 23 + 1800):  # 23h30m
                            if (
                                help_thread.id not in self.inactive_help_thread_data
                                or self.inactive_help_thread_data[help_thread.id][
                                    "last_active_ts"
                                ]
                                < last_active_ts
                            ):
                                alert_message = await help_thread.send(
                                    f"help-post-inactive(<@{help_thread.owner_id}>, **{help_thread.name}**)",
                                    embed=discord.Embed(
                                        title="Your help post has gone inactive... 💤",
                                        description=f"Your help post was last active **<t:{int(last_active_ts)}:R>** ."
                                        "\nHas your issue been solved? If so, mark it as **Solved** by "
                                        "doing one of these:\n\n"
                                        "  **• React on your starter message with ✅**.\n"
                                        "  **• Right-click on your post (click and hold on mobile), "
                                        "go to 'Edit Tags', select the `✅ Solved` tag and save your changes.**\n\n"
                                        "**Mark all messages you find helpful here with a ✅ reaction please** "
                                        "<:pg_robot:837389387024957440>\n\n"
                                        "*If your issue has't been solved, you may "
                                        "either wait for help or close this post.*",
                                        color=0x888888,
                                    ),
                                )
                                self.inactive_help_thread_data[help_thread.id] = {
                                    "thread_id": help_thread.id,
                                    "last_active_ts": alert_message.created_at.timestamp(),
                                    "alert_message_id": alert_message.id,
                                }
                        elif (
                            help_thread.id in self.inactive_help_thread_data
                            and (
                                alert_message_id := self.inactive_help_thread_data[
                                    help_thread.id
                                ].get("alert_message_id", None)
                            )
                        ) and (
                            (
                                partial_alert_message := help_thread.get_partial_message(
                                    alert_message_id
                                )
                            ).created_at.timestamp()
                            < last_active_ts  # someone messaged into the channel
                        ):
                            try:
                                last_message = await self.fetch_last_thread_message(
                                    help_thread
                                )
                                if last_message and not last_message.is_system():
                                    try:
                                        await partial_alert_message.delete()
                                    except discord.NotFound:
                                        pass
                                    finally:
                                        del self.inactive_help_thread_data[
                                            help_thread.id
                                        ]["alert_message_id"]
                            except discord.NotFound:
                                pass

                except discord.HTTPException:
                    pass

    @tasks.loop(hours=1, reconnect=True)
    async def delete_help_threads_without_starter_message(self):
        for forum_channel in [
            self.bot.get_channel(fid) or (await self.bot.fetch_channel(fid))
            for fid in HELP_FORUM_CHANNEL_IDS.values()
        ]:
            for help_thread in itertools.chain(
                forum_channel.threads,  # type: ignore
                [thr async for thr in forum_channel.archived_threads(limit=20)],  # type: ignore
            ):
                try:
                    starter_message = (
                        help_thread.starter_message
                        or await help_thread.fetch_message(help_thread.id)
                    )
                except discord.NotFound:
                    pass
                else:
                    continue  # starter message still exists, skip
                snakecore.utils.hold_task(
                    asyncio.create_task(self.help_thread_deletion_checks(help_thread))
                )

    @tasks.loop(hours=1, reconnect=True)
    async def force_help_thread_archive_after_timeout(self):
        for forum_channel in [
            self.bot.get_channel(fid) or (await self.bot.fetch_channel(fid))
            for fid in HELP_FORUM_CHANNEL_IDS.values()
        ]:
            if not isinstance(forum_channel, discord.ForumChannel):
                return

            now_ts = time.time()
            for help_thread in forum_channel.threads:
                try:
                    if not help_thread.created_at:
                        continue

                    if not (
                        help_thread.archived
                        or help_thread.locked
                        or help_thread.flags.pinned
                    ):
                        last_active_ts = (
                            await self.fetch_last_thread_activity_dt(help_thread)
                        ).timestamp()
                        if (
                            now_ts - last_active_ts
                        ) / 60.0 > help_thread.auto_archive_duration:

                            thread_edits = {}
                            thread_edits["archived"] = True

                            if (
                                any(
                                    tag.name.lower().startswith("solved")
                                    for tag in help_thread.applied_tags
                                )
                                and help_thread.slowmode_delay
                                == forum_channel.default_thread_slowmode_delay
                            ):
                                # solved and no overridden slowmode
                                thread_edits["slowmode_delay"] = 60  # seconds

                            if not (
                                help_thread.name.endswith(
                                    owner_id_suffix := f" | {help_thread.owner_id}"
                                )
                                or str(help_thread.owner_id) in help_thread.name
                            ):  # wait for a few event loop iterations, before doing a second,
                                # check, to be sure that a bot edit hasn't already occured
                                thread_edits["archived"] = False
                                thread_edits["name"] = (
                                    help_thread.name
                                    if len(help_thread.name) < 72
                                    else help_thread.name[:72] + "..."
                                ) + owner_id_suffix

                            await help_thread.edit(
                                reason="This help thread has been closed "
                                "after exceeding its inactivity timeout.",
                                **thread_edits,
                            )
                except discord.HTTPException:
                    pass

    @staticmethod
    async def help_thread_deletion_checks(thread: discord.Thread):
        member_msg_count = 0
        try:
            async for thread_message in thread.history(
                limit=max(thread.message_count, 60)
            ):
                if (
                    not thread_message.author.bot
                    and thread_message.type == discord.MessageType.default
                ):
                    member_msg_count += 1
                    if member_msg_count > 29:
                        break

            if member_msg_count < 30:
                await thread.send(
                    embed=discord.Embed(
                        title="Post scheduled for deletion",
                        description=(
                            "Someone deleted the starter message of this post.\n\n"
                            "Since it contains less than 30 messages sent by "
                            "server members, it will be deleted "
                            f"**<t:{int(time.time()+300)}:R>**."
                        ),
                        color=0x551111,
                    )
                )
                await asyncio.sleep(300)
                await thread.delete()
        except discord.HTTPException:
            pass

    @staticmethod
    def validate_help_forum_channel_thread_name(thread: discord.Thread) -> bool:
        return any(
            (
                INVALID_HELP_THREAD_TITLE_SCANNING_ENABLED[caution_type]
                and INVALID_HELP_THREAD_TITLE_REGEX_PATTERNS[caution_type].search(
                    thread.name.replace(f" | {thread.owner_id}", "")
                )
                is not None
                for caution_type in INVALID_HELP_THREAD_TITLE_TYPES
            )
        )

    @staticmethod
    def get_help_forum_channel_thread_name_cautions(
        thread: discord.Thread,
    ) -> tuple[str, ...]:
        return tuple(
            (
                caution_type
                for caution_type in INVALID_HELP_THREAD_TITLE_TYPES
                if INVALID_HELP_THREAD_TITLE_SCANNING_ENABLED[caution_type]
                and INVALID_HELP_THREAD_TITLE_REGEX_PATTERNS[caution_type].search(
                    " ".join(thread.name.replace(f" | {thread.owner_id}", "").split())
                )  # normalize whitespace
                is not None
            )
        )

    @staticmethod
    async def caution_about_help_forum_channel_thread_name(
        thread: discord.Thread, *caution_types: str
    ) -> list[discord.Message]:
        caution_messages = []
        for caution_type in caution_types:
            caution_messages.append(
                await thread.send(
                    content=f"help-post-alert(<@{thread.owner_id}>, **{thread.name}**)",
                    embed=discord.Embed.from_dict(
                        INVALID_HELP_THREAD_TITLE_EMBEDS[caution_type]
                    ),
                )
            )

        return caution_messages

    @staticmethod
    def validate_regulars_help_forum_channel_thread_tags(
        thread: discord.Thread,
    ) -> bool:
        applied_tags = thread.applied_tags
        valid = True
        if applied_tags and not any(
            tag.name.lower().startswith(("solved", "invalid")) for tag in applied_tags
        ):
            issue_tags = tuple(
                tag for tag in applied_tags if tag.name.lower().startswith("issue")
            )
            aspect_tags = tuple(
                tag
                for tag in applied_tags
                if not tag.name.lower().startswith(("issue", "unsolved"))
            )
            if not len(issue_tags) or len(issue_tags) > 1 or not aspect_tags:
                valid = False

        return valid

    @staticmethod
    async def caution_about_regulars_help_forum_channel_thread_tags(
        thread: discord.Thread,
    ) -> discord.Message:
        return await thread.send(
            content=f"help-post-alert(<@{thread.owner_id}>, **{thread.name}**)",
            embed=discord.Embed(
                title="Your tag selection is incomplete",
                description=(
                    "Please pick exactly **1 issue tag** and **1-3 aspect tags**.\n\n"
                    "**Issue Tags** look like this: **(`issue: ...`)**.\n"
                    "**Aspect Tags** are all non-issue tags in lowercase, e.g. **(`💥 collisions`)**\n\n"
                    "**Example tag combination for reworking collisions:\n"
                    "(`🪛 issue: rework/optim.`) (`💥 collisions`)**.\n\n"
                    f"See the Post Guidelines of <#{thread.parent_id}> for more details.\n\n"
                    "To make changes to your post's tags, either right-click on "
                    "it (desktop/web) or click and hold on it (mobile), then click "
                    "on **'Edit Tags'** to see a tag selection menu. Remember to save "
                    "your changes after selecting the correct tag(s).\n\n"
                    "Thank you for helping us maintain clean help forum channels "
                    "<:pg_robot:837389387024957440>\n\n"
                    "This alert should disappear after you have made appropriate changes."
                ),
                color=0x36393F,
            ),
        )

    @staticmethod
    async def send_help_thread_solved_alert(thread: discord.Thread):
        await thread.send(
            content="help-post-solved",
            embed=discord.Embed(
                title="Post marked as solved",
                description=(
                    "This help post has been marked as solved.\n"
                    "It will now close with a 1 minute slowmode "
                    "after 1 hour of inactivity.\nFor the sake of the "
                    "OP, please avoid sending any further messages "
                    "that aren't essential additions to the currently "
                    "accepted answers.\n\n"
                    "**Mark all messages you find helpful here with a ✅ reaction "
                    "please** <:pg_robot:837389387024957440>\n\n"
                    "The slowmode and archive timeout will both be reverted "
                    "if this post is unmarked as solved."
                ),
                color=0x00AA00,
            ),
        )

    @staticmethod
    async def fetch_last_thread_activity_dt(
        thread: discord.Thread,
    ) -> datetime.datetime:
        """Get the last time this thread was active. This is usually
        the creation date of the most recent message.

        Args:
            thread (discord.Thread): The thread.

        Returns:
            datetime.datetime: The time.
        """
        last_active = thread.created_at
        last_message = thread.last_message
        if last_message is None:
            last_message_found = False
            if thread.last_message_id is not None:
                try:
                    last_message = await thread.fetch_message(thread.last_message_id)
                    last_message_found = True
                except discord.NotFound:
                    pass

            if not last_message_found:
                try:
                    last_messages = [msg async for msg in thread.history(limit=1)]
                    if last_messages:
                        last_message = last_messages[0]
                except discord.HTTPException:
                    pass

        if last_message is not None:
            last_active = last_message.created_at

        return last_active  # type: ignore

    @staticmethod
    async def fetch_last_thread_message(
        thread: discord.Thread,
    ) -> Optional[discord.Message]:
        """Get the last message sent in the given thread.

        Args:
            thread (discord.Thread): The thread.

        Returns:
            Optional[discord.Message]: The message, if it exists.
        """
        last_message = thread.last_message
        if last_message is None:
            last_message_found = False
            if thread.last_message_id is not None:
                try:
                    last_message = await thread.fetch_message(thread.last_message_id)
                    last_message_found = True
                except discord.NotFound:
                    pass

            if not last_message_found:
                try:
                    last_messages = [msg async for msg in thread.history(limit=1)]
                    if last_messages:
                        last_message = last_messages[0]
                except discord.HTTPException:
                    pass

        return last_message


@snakecore.commands.decorators.with_config_kwargs
async def setup(bot: BotT, color: Union[int, discord.Color] = 0):
    first_setup = False
    try:
        extension_data = await bot.read_extension_data(__name__)
    except LookupError:
        first_setup = True
        extension_data = dict(
            name=__name__,
            version=__version__,
            db_table_prefix=DB_TABLE_PREFIX,
            initial_data=pickle.dumps(
                {"bad_help_thread_data": {}, "inactive_help_thread_data": {}}
            ),
        )
        await bot.create_extension_data(**extension_data)  # type: ignore

    extension_version = Version(__version__)
    stored_version = Version("0.0.0" if first_setup else str(extension_data["version"]))
    if stored_version > extension_version:
        raise RuntimeError(
            f'Extension data is incompatible: Stored data version "{stored_version}"'
            f' exceeds extension version "{extension_version}"'
        )

    elif stored_version < extension_version:
        await bot.update_extension_data(__name__, version=__version__)  # type: ignore

    await bot.add_cog(HelpForumsPre(bot, theme_color=int(color)))
