import asyncio
import logging
import re
from typing import Collection, TypedDict

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


class InfoEntryValue(TypedDict):
    """Cached payload for a single info entry."""

    name: str
    content: str


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

        If the match contains '/' or '|', split into separate keys.
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

        if "/" in raw_value or "|" in raw_value:
            parts = [part.strip() for part in re.split(r"[\/|]", raw_value)]
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
        prefix: str, values: Collection[str]
    ) -> tuple[str, dict[str, int | str]]:
        placeholders: list[str] = []
        params: dict[str, int | str] = {}
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

    async def _fetch_entry_for_key(
        self, conn: AsyncConnection, key: str
    ) -> tuple[int, InfoEntryValue] | None:
        result = await conn.execute(
            text(
                f"SELECT ck.key, ce.thread_id, ce.name, ce.content "
                f"FROM '{DB_PREFIX}cache_keys' ck "
                f"JOIN '{DB_PREFIX}cache_entries' ce ON ck.thread_id = ce.thread_id "
                "WHERE ck.uid = :uid AND ck.key = :key"
            ),
            dict(uid=str(self.bot.uid), key=key),
        )
        row = result.fetchone()
        if row is None:
            return None

        return int(row.thread_id), {"name": row.name, "content": row.content or ""}

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

    async def _get_entries_for_keys(
        self, keys: list[str]
    ) -> tuple[list[tuple[int, InfoEntryValue]], list[str]]:
        resolved: list[tuple[int, InfoEntryValue]] = []
        missing: list[str] = []
        seen_primary: set[int] = set()

        async with self.db_engine.connect() as conn:
            for key in keys:
                normalized = self._normalize_key(key)
                entry = await self._fetch_entry_for_key(conn, normalized)
                if entry is None:
                    missing.append(key)
                    continue
                thread_id, value = entry
                if thread_id in seen_primary:
                    continue
                seen_primary.add(thread_id)
                resolved.append((thread_id, value))

        if missing:
            async with self._db_lock:
                await self._refresh_cache_from_threads()

            still_missing: list[str] = []
            async with self.db_engine.connect() as conn:
                for key in missing:
                    normalized = self._normalize_key(key)
                    entry = await self._fetch_entry_for_key(conn, normalized)
                    if entry is None:
                        still_missing.append(key)
                        continue
                    thread_id, value = entry
                    if thread_id in seen_primary:
                        continue
                    seen_primary.add(thread_id)
                    resolved.append((thread_id, value))

            missing = still_missing

        return resolved, missing

    @staticmethod
    def _trim_text_to_limit(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3] + "..."

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
            "url": f"https://discord.com/channels/{ctx.guild.id}/{thread_id}/{thread_id}"
            if ctx.guild
            else "",
            "description": description,
            "color": int(self.theme_color),
        }
        return [
            discord.Embed.from_dict(embed)
            for embed in snakecore.utils.embeds.split_embed_dict(embed_dict)
        ]

    async def _send_info_response(
        self, ctx: commands.Context[BotT], keys: Collection[str]
    ) -> None:
        if not keys:
            raise invocation_error(ctx, "You must provide at least one key.")

        if len(keys) > MAX_INFO_KEYS:
            raise invocation_error(
                ctx,
                f"You can only request up to {MAX_INFO_KEYS} keys at once.",
            )

        resolved, missing = await self._get_entries_for_keys(list(keys))

        if not resolved:
            raise invocation_error(
                ctx,
                "No info entries were found for the provided keys.",
            )

        embeds: list[discord.Embed] = []
        for thread_id, entry in resolved:
            description = (
                entry.get("content", "") or "(No content found for this entry.)"
            )
            embeds.extend(
                self._build_info_embed(
                    ctx,
                    entry.get("name", "Info Entry"),
                    description,
                    thread_id,
                )
            )

        if missing:
            embeds.extend(
                self._build_info_embed(
                    ctx,
                    "Not Found",
                    "No info entries were found for: " + ", ".join(missing),
                    self.info_channel_ids[0],
                )
            )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embeds=embeds[:10])
            if len(embeds) > 10:
                for i in range(10, len(embeds), 10):
                    await ctx.interaction.followup.send(embeds=embeds[i : i + 10])
            return

        await self.send_or_edit_response(ctx, embeds=embeds[:10])

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
        usage="<keys>...",
        description="Look up info entries by key.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    async def info(self, ctx: commands.Context[BotT], *keys: str):
        """Look up info entries by key.

        __**Parameters:**__

        **`<keys>...`**
        > One or more info entry keys separated by spaces.
        """
        await self._send_info_response(ctx, keys)

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
        parts = [part.strip() for part in re.split(r"[\s,]+", keys) if part.strip()]
        await self._send_info_response(
            await commands.Context[BotT].from_interaction(interaction),
            parts,
        )
