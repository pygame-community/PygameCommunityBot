import asyncio
import logging
import re
from typing import Any, Collection, TypedDict

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
import snakecore

from ...bot import PygameCommunityBot
from ...base import BaseExtensionCog
from .constants import DB_PREFIX

BotT = PygameCommunityBot

_logger = logging.getLogger(__name__)

# Hard cap to keep responses compact and within Discord embed limits.
MAX_INFO_KEYS = 5
# Combined title + description budget for each info embed.
MAX_INFO_EMBED_FIELDS = 2000

DISCORD_MESSAGE_URL_RE = re.compile(
    r"^https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)(?:/(\d+))?/?$"
)


class InfoEntryValue(TypedDict):
    """Cached payload for a single info entry."""

    thread_id: int
    name: str
    content: str


class InfoCacheEntryRow(TypedDict):
    """Row shape for cache_entries."""

    uid: str
    thread_id: int
    name: str
    content: str


class InfoCacheKeyRow(TypedDict):
    """Row shape for cache_keys."""

    uid: str
    key: str
    thread_id: int


def invocation_error(ctx, *args):
    return (
        app_commands.CommandInvokeError(
            ctx.interaction.command, app_commands.AppCommandError(*args)
        )
        if ctx.interaction
        else commands.CommandInvokeError(commands.CommandError(*args))
    )


class InfoChannelCog(BaseExtensionCog, name="info-channel"):
    """Lookup info entries stored as starter messages in forum threads or threads."""

    bot: BotT

    invoke_on_message_edit: bool = True

    def __init__(
        self,
        bot: BotT,
        db_engine: AsyncEngine,
        revision_number: int,
        info_channel_ids: Collection[int],
        info_entry_key_regexp: str,
        theme_color: int | discord.Color = 0,
    ) -> None:
        super().__init__(bot, theme_color)
        self.db_engine = db_engine
        self.revision_number = revision_number
        self.info_channel_ids = [int(channel_id) for channel_id in info_channel_ids]
        if not self.info_channel_ids:
            raise ValueError("At least one info channel id must be configured.")
        self._key_re = re.compile(info_entry_key_regexp)
        self._db_lock = asyncio.Lock()

    @staticmethod
    def _normalize_key(key: str) -> str:
        """Normalize keys for consistent cache keys."""
        return key.strip().lower()

    def _extract_keys(self, thread_name: str) -> list[str]:
        """Extract key(s) from thread titles using the configured regex.

        The regex is expected to capture bracketed keys like "[ key | alias ]".
        """
        match = self._key_re.search(thread_name)
        if not match:
            return []

        if match.groups():
            raw_value = next((g for g in match.groups() if g), match.group(0))
        else:
            raw_value = match.group(0)

        raw_value = raw_value.strip()
        if not raw_value:
            return []

        if "|" in raw_value:
            parts = [part.strip() for part in raw_value.split("|")]
            return [self._normalize_key(p) for p in parts if p]

        return [self._normalize_key(raw_value)]

    async def _fetch_info_channel(
        self,
        channel_id: int,
    ) -> discord.Thread | discord.ForumChannel | discord.TextChannel | None:
        """Resolve the configured info channel or thread."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

        if isinstance(
            channel, (discord.Thread, discord.ForumChannel, discord.TextChannel)
        ):
            return channel
        return None

    async def _iter_info_threads(
        self,
    ) -> list[tuple[int, discord.Thread]]:
        """Return active and archived threads for the configured info channels."""
        threads: list[tuple[int, discord.Thread]] = []
        for channel_id in self.info_channel_ids:
            channel = await self._fetch_info_channel(channel_id)
            if channel is None:
                continue

            if isinstance(channel, discord.Thread):
                threads.append((channel_id, channel))
                continue

            if isinstance(channel, (discord.ForumChannel, discord.TextChannel)):
                threads.extend(
                    (channel_id, thread)
                    for thread in channel.threads  # type: ignore[attr-defined]
                )
                if hasattr(channel, "archived_threads"):
                    try:
                        async for thread in channel.archived_threads(limit=1000):  # type: ignore[attr-defined]
                            threads.append((channel_id, thread))
                    except discord.HTTPException:
                        pass

        return threads

    async def _upsert_entry(
        self,
        conn: AsyncConnection,
        thread_id: int,
        name: str,
        content: str,
    ) -> None:
        await conn.execute(
            text(
                f"INSERT INTO '{DB_PREFIX}cache_entries' (uid, thread_id, name, content) "
                "VALUES (:uid, :thread_id, :name, :content) "
                "ON CONFLICT(thread_id) DO UPDATE SET name = excluded.name, content = excluded.content"
            ),
            dict(
                uid=str(self.bot.uid), thread_id=thread_id, name=name, content=content
            ),
        )

    async def _entry_exists(self, conn: AsyncConnection, thread_id: int) -> bool:
        result = await conn.execute(
            text(
                f"SELECT 1 FROM '{DB_PREFIX}cache_entries' "
                "WHERE uid = :uid AND thread_id = :thread_id"
            ),
            dict(uid=str(self.bot.uid), thread_id=thread_id),
        )
        return result.scalar() is not None

    @staticmethod
    def _build_sql_in_clause(
        prefix: str, values: Collection
    ) -> tuple[str, dict[str, Any]]:
        placeholders: list[str] = []
        params: dict[str, Any] = {}
        for index, value in enumerate(values):
            key = f"{prefix}{index}"
            placeholders.append(f":{key}")
            params[key] = value
        return ", ".join(placeholders), params

    async def _update_keys_for_thread(
        self,
        conn: AsyncConnection,
        thread_id: int,
        keys: list[str],
        channel_id: int,
    ) -> None:
        normalized_keys = [self._normalize_key(key) for key in keys]
        new_keys = set(normalized_keys)

        result = await conn.execute(
            text(
                f"SELECT key FROM '{DB_PREFIX}cache_keys' "
                "WHERE uid = :uid AND thread_id = :thread_id"
            ),
            dict(uid=str(self.bot.uid), thread_id=thread_id),
        )
        existing_keys = {row[0] for row in result.fetchall()}
        stale_keys = existing_keys - new_keys
        if stale_keys:
            # Drop keys that no longer map to this thread.
            placeholders, params = self._build_sql_in_clause("stale", stale_keys)
            params.update(dict(uid=str(self.bot.uid), thread_id=thread_id))
            await conn.execute(
                text(
                    f"DELETE FROM '{DB_PREFIX}cache_keys' "
                    f"WHERE uid = :uid AND thread_id = :thread_id AND key IN ({placeholders})"
                ),
                params,
            )

        for key in new_keys:
            row = await conn.execute(
                text(
                    f"SELECT thread_id FROM '{DB_PREFIX}cache_keys' "
                    "WHERE uid = :uid AND key = :key"
                ),
                dict(uid=str(self.bot.uid), key=key),
            )
            existing_thread = row.scalar()
            if existing_thread is not None and int(existing_thread) != thread_id:
                _logger.warning(
                    "Duplicate info key '%s' detected in channel %s; keeping the existing entry.",
                    key,
                    channel_id,
                )
                continue

            await conn.execute(
                text(
                    f"INSERT INTO '{DB_PREFIX}cache_keys' (uid, key, thread_id) "
                    "VALUES (:uid, :key, :thread_id) "
                    "ON CONFLICT(key) DO UPDATE SET thread_id = excluded.thread_id"
                ),
                dict(uid=str(self.bot.uid), key=key, thread_id=thread_id),
            )

    async def _fetch_entry_for_thread_id(
        self, conn: AsyncConnection, thread_id: int
    ) -> InfoCacheEntryRow | None:
        result = await conn.execute(
            text(
                f"SELECT uid, thread_id, name, content FROM '{DB_PREFIX}cache_entries' "
                "WHERE uid = :uid AND thread_id = :thread_id"
            ),
            dict(uid=str(self.bot.uid), thread_id=thread_id),
        )
        row = result.fetchone()
        if row is None:
            return None

        uid, thread_id_val, name, content = row
        return InfoCacheEntryRow(
            uid=str(uid),
            thread_id=int(thread_id_val),
            name=str(name),
            content=str(content or ""),
        )

    async def _fetch_key_for_value(
        self, conn: AsyncConnection, key: str
    ) -> InfoCacheKeyRow | None:
        result = await conn.execute(
            text(
                f"SELECT uid, key, thread_id FROM '{DB_PREFIX}cache_keys' "
                "WHERE uid = :uid AND key = :key"
            ),
            dict(uid=str(self.bot.uid), key=key),
        )
        row = result.fetchone()
        if row is None:
            return None

        uid, key_val, thread_id_val = row
        return InfoCacheKeyRow(
            uid=str(uid),
            key=str(key_val),
            thread_id=int(thread_id_val),
        )

    async def _fetch_entry_for_key(
        self, conn: AsyncConnection, key: str
    ) -> InfoEntryValue | None:
        key_row = await self._fetch_key_for_value(conn, key)
        if key_row is None:
            return None

        entry_row = await self._fetch_entry_for_thread_id(conn, key_row["thread_id"])
        if entry_row is None:
            return None

        entry = InfoEntryValue(
            thread_id=entry_row["thread_id"],
            name=entry_row["name"],
            content=entry_row["content"],
        )
        # handle redirections

        redirect = entry["content"].strip()
        match = DISCORD_MESSAGE_URL_RE.fullmatch(redirect)
        if not match:
            return entry

        target_thread_id = int(match.group(2))
        if target_thread_id == entry_row["thread_id"]:
            return entry

        redirected = await self._fetch_entry_for_thread_id(conn, target_thread_id)
        if redirected is None:
            return entry

        return InfoEntryValue(
            thread_id=target_thread_id,
            name=redirected["name"],
            content=redirected["content"],
        )

    async def _refresh_cache_from_threads(self) -> None:
        threads = await self._iter_info_threads()
        if not threads:
            return

        # Avoid repeated duplicate-key warnings in a single refresh pass.
        seen_keys: set[str] = set()
        async with self.db_engine.begin() as conn:
            for channel_id, thread in threads:
                keys = self._extract_keys(thread.name)
                if not keys:
                    continue

                try:
                    starter = thread.starter_message or await thread.fetch_message(
                        thread.id
                    )
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue

                if starter.channel.id != thread.id:
                    continue

                primary_key = keys[0]
                normalized_primary = self._normalize_key(primary_key)
                if normalized_primary in seen_keys:
                    continue
                seen_keys.add(normalized_primary)
                content = starter.content or ""

                row = await conn.execute(
                    text(
                        f"SELECT thread_id FROM '{DB_PREFIX}cache_keys' "
                        "WHERE uid = :uid AND key = :key"
                    ),
                    dict(uid=str(self.bot.uid), key=normalized_primary),
                )
                existing_key = row.scalar()
                if existing_key is not None and int(existing_key) != thread.id:
                    _logger.warning(
                        "Duplicate info key '%s' detected in channel %s; keeping the existing entry.",
                        primary_key,
                        channel_id,
                    )
                    continue

                await self._upsert_entry(conn, thread.id, thread.name, content)
                await self._update_keys_for_thread(conn, thread.id, keys, channel_id)

    async def _get_entry_for_key(self, key: str) -> InfoEntryValue | None:
        async with self.db_engine.connect() as conn:
            normalized = self._normalize_key(key)
            entry = await self._fetch_entry_for_key(conn, normalized)
            if entry is not None:
                return entry

        async with self._db_lock:
            await self._refresh_cache_from_threads()

        async with self.db_engine.connect() as conn:
            normalized = self._normalize_key(key)
            return await self._fetch_entry_for_key(conn, normalized)

    @staticmethod
    def _trim_text_to_limit(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3] + "..."

    @staticmethod
    def _split_entry_description_by_divider(text: str) -> list[str]:
        """Split description into pages using "---" while preserving the prefix."""
        divider_index = text.find("---")
        if divider_index == -1:
            return [text]

        prefix = text[: divider_index + 3]
        remainder = text[divider_index + 3 :]
        parts = remainder.split("---")
        return [prefix + part for part in parts]

    def _build_info_embed(
        self, ctx: commands.Context[BotT], title: str, description: str, thread_id: int
    ) -> list[discord.Embed]:
        title = self._trim_text_to_limit(title, MAX_INFO_EMBED_FIELDS)
        remaining = max(MAX_INFO_EMBED_FIELDS - len(title), 0)
        description = self._trim_text_to_limit(description, remaining)
        thread = self.bot.get_channel(thread_id)
        thread_parent = getattr(thread, "parent", None) if thread else None
        embed_author = (
            {
                "author": {
                    "name": f"#{thread_parent.name}",
                    "url": thread_parent.jump_url,
                }
            }
            if thread_parent
            else {}
        )
        embed_dict = {
            **embed_author,
            "title": title,
            "url": (
                f"https://discord.com/channels/{ctx.guild.id}/{thread_id}/{thread_id}"
                if ctx.guild
                else ""
            ),
            "description": description,
            "color": int(self.theme_color),
        }
        return [
            discord.Embed.from_dict(embed)
            for embed in snakecore.utils.embeds.split_embed_dict(embed_dict)
        ]

    async def _send_info_response(
        self, ctx: commands.Context[BotT], key_text: str
    ) -> None:
        key_text = key_text.strip()
        if not key_text:
            raise invocation_error(ctx, "You must provide a key.")

        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(thinking=True)

        entry = await self._get_entry_for_key(key_text)
        if entry is None:
            embeds = self._build_info_embed(
                ctx,
                "Not Found",
                f"No info entries were found for: {key_text}",
                self.info_channel_ids[0],
            )
        else:
            thread_id = entry["thread_id"]
            description = (
                entry.get("content", "") or "(No content found for this entry.)"
            )
            embeds: list[discord.Embed] = []
            for segment in self._split_entry_description_by_divider(description):
                embeds.extend(
                    self._build_info_embed(
                        ctx,
                        entry.get("name", "Info Entry"),
                        segment,
                        thread_id,
                    )
                )

        reply_member: discord.Member | None = None
        if ctx.message is not None:
            reference = ctx.message.reference
            if reference and isinstance(reference.resolved, discord.Message):
                if isinstance(reference.resolved.author, discord.Member):
                    reply_member = reference.resolved.author

        await self.send_paginated_response_embeds(
            ctx,
            *embeds,
            member=(
                [ctx.author, reply_member] if reply_member else ctx.author
            ),  # pyright: ignore[reportArgumentType]
        )

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if thread.parent_id not in self.info_channel_ids:
            return

        if thread.archived:
            return

        if thread.starter_message is None:
            return

        keys = self._extract_keys(thread.name)
        if not keys:
            return

        async with self._db_lock:
            try:
                starter = thread.starter_message or await thread.fetch_message(
                    thread.id
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

            try:
                await starter.pin(
                    reason="Pinning starter message for easier thread navigation."
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

            content = starter.content or ""

            async with self.db_engine.begin() as conn:
                await self._upsert_entry(
                    conn,
                    thread.id,
                    thread.name,
                    content,
                )
                await self._update_keys_for_thread(
                    conn,
                    thread.id,
                    keys,
                    thread.parent_id or thread.id,
                )

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if after.guild is None:
            return

        if not isinstance(after.channel, discord.Thread):
            return

        thread = after.channel
        parent_id = getattr(thread, "parent_id", None)
        if (
            thread.id not in self.info_channel_ids
            and parent_id not in self.info_channel_ids
        ):
            return

        if after.id != thread.id:
            return

        # Only refresh cache on starter message edits.
        keys = self._extract_keys(thread.name)
        async with self._db_lock:
            async with self.db_engine.begin() as conn:
                if not keys:
                    exists = await self._entry_exists(conn, thread.id)
                    if not exists:
                        return

                await self._upsert_entry(
                    conn,
                    thread.id,
                    thread.name,
                    after.content or "",
                )
                if keys:
                    await self._update_keys_for_thread(
                        conn, thread.id, keys, parent_id or thread.id
                    )

    @commands.guild_only()
    @commands.group(
        invoke_without_command=True,
        name="info",
        usage="<keys Text>...",
        description="Look up info entries by key.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    async def info(self, ctx: commands.Context[BotT], *keys: str):
        """Look up info entries by key.

        __**Parameters:**__

        **`<keys Text>...`**
        > One or more info entry keys separated by spaces.
        """
        await self._send_info_response(ctx, " ".join(keys))

    @app_commands.command(
        name="info",
        description="Look up info entries by key.",
    )
    @app_commands.describe(
        keys="One or more keys separated by spaces.",
    )
    async def info_app_command(
        self,
        interaction: discord.Interaction[BotT],
        keys: str,
    ):
        await self._send_info_response(
            await commands.Context[BotT].from_interaction(interaction),
            keys,
        )
