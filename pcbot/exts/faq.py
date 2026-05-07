"""This file is a part of the source code for PygameCommunityBot.
This project has been licensed under the MIT license.
Copyright (c) 2022-present pygame-community.
"""

from __future__ import annotations

import asyncio
import io
import logging
import pickle
import re
from typing import Collection, Literal, TypedDict

import discord
from discord import app_commands
from discord.ext import commands
import snakecore

from ..base import BaseExtensionCog

BotT = snakecore.commands.Bot | snakecore.commands.AutoShardedBot
# Hard cap to keep responses compact and within Discord embed limits.
MAX_FAQ_KEYS = 5
# Combined title + description budget for each FAQ embed.
MAX_FAQ_EMBED_FIELDS = 2000


class FaqEntryValue(TypedDict):
    """Cached payload for a single FAQ entry."""

    thread_id: int
    name: str
    content: str


class FaqCacheEntry(TypedDict):
    """Cache item representing a primary FAQ entry."""

    type: Literal["entry"]
    value: FaqEntryValue


class FaqCacheIdentifierEntry(TypedDict):
    """Cache item representing an alias that points at a primary entry."""

    type: Literal["entry_key"]
    value: str  # primary key


class FaqCachePayload(TypedDict):
    """Top-level JSON payload stored in the cache attachment.

    Schema example:
    ```json
    {
        "channel_id": 123456789012345678,
        "cache": {
            "key1": {
                "type": "entry",
                "value": {
                    "thread_id": 123456789012345678,
                    "name": "Thread Title",
                    "content": "FAQ entry content from the thread starter message."
                }
            },
            "alias1": {
                "type": "entry_key",
                "value": "key1"
            }
        }
    }
    ```
    """

    channel_id: int
    cache: dict[str, FaqCacheEntry | FaqCacheIdentifierEntry]


def invocation_error(ctx, *args):
    return (
        app_commands.CommandInvokeError(
            ctx.interaction.command, app_commands.AppCommandError(*args)
        )
        if ctx.interaction
        else commands.CommandInvokeError(commands.CommandError(*args))
    )


logger = logging.getLogger(__name__)


class FAQChannelCog(BaseExtensionCog, name="faq-channel"):
    """Lookup FAQ entries stored as starter messages in forum threads or thread channels.

    The cache is stored as a JSON attachment on a designated message to avoid
    rescanning the forum for every request.
    """

    invoke_on_message_edit: bool = True

    def __init__(
        self,
        bot: BotT,
        faq_channel_id: int,
        faq_cache_channel_id: int,
        faq_cache_message_id: int,
        faq_entry_key_regexp: str,
        theme_color: int | discord.Color = 0,
    ) -> None:
        """Create the cog using FAQ source and cache channel configuration."""
        super().__init__(bot, theme_color)
        self.faq_channel_id = int(faq_channel_id)
        self.faq_cache_channel_id = int(faq_cache_channel_id)
        self.faq_cache_message_id = int(faq_cache_message_id)
        self._key_re = re.compile(faq_entry_key_regexp)

        self._cache_lock = asyncio.Lock()
        self._cache_loaded = False
        self._cache: dict[str, FaqCacheEntry | FaqCacheIdentifierEntry] = {}
        self._cache_message: discord.Message | None = None

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

    async def _resolve_cache_message(self) -> discord.Message | None:
        """Resolve the cache message that holds the JSON attachment.

        The cache message can live in any channel the bot can access.
        """
        if self._cache_message is not None:
            return self._cache_message

        cache_channel = await self._get_cache_channel()
        if cache_channel is None:
            return None

        try:
            self._cache_message = await cache_channel.fetch_message(
                self.faq_cache_message_id
            )
        except discord.NotFound:
            logger.warning(
                "FAQ cache message %s was not found in channel %s.",
                self.faq_cache_message_id,
                getattr(cache_channel, "id", "unknown"),
            )
            return None
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.error(
                "Failed to fetch FAQ cache message %s: %s",
                self.faq_cache_message_id,
                exc,
            )
            return None

        return self._cache_message

    async def _get_cache_channel(self) -> discord.abc.Messageable | None:
        """Resolve the channel used to store the FAQ cache message."""
        cache_channel = self.bot.get_channel(self.faq_cache_channel_id)
        if cache_channel is None:
            try:
                cache_channel = await self.bot.fetch_channel(self.faq_cache_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                logger.error(
                    "Failed to fetch FAQ cache channel %s: %s",
                    self.faq_cache_channel_id,
                    exc,
                )
                return None

        if not isinstance(cache_channel, discord.abc.Messageable):
            logger.error(
                "FAQ cache channel %s is not messageable.",
                self.faq_cache_channel_id,
            )
            return None

        return cache_channel

    async def _load_cache(self) -> None:
        """Load cache data from the JSON attachment on first use."""
        if self._cache_loaded:
            return

        async with self._cache_lock:
            if self._cache_loaded:
                return

            message = await self._resolve_cache_message()
            if message is None:
                self._cache_loaded = True
                return

            cache_attachment = next(
                (att for att in message.attachments if att.filename == "faq_cache"),
                None,
            )

            if cache_attachment is None:
                logger.info(
                    "No FAQ cache attachment found on message %s: will create one on next save.",
                    self.faq_cache_message_id,
                )
                self._cache_loaded = True
                return

            data = await cache_attachment.read()
            try:
                payload = pickle.loads(data)
            except Exception:
                logger.warning("Failed to decode FAQ cache attachment.", exc_info=True)
                self._cache_loaded = True
                return

            if isinstance(payload, dict) and isinstance(payload.get("cache"), dict):
                self._cache = payload["cache"]

            self._cache_loaded = True

    async def _save_cache(self) -> None:
        """Persist cache data to the configured JSON attachment."""
        payload: FaqCachePayload = {
            "channel_id": self.faq_channel_id,
            "cache": self._cache,
        }

        message = await self._resolve_cache_message()
        if message is None:
            logger.error(
                "FAQ cache message %s could not be resolved; cannot update cache attachment.",
                self.faq_cache_message_id,
            )
            return

        data = pickle.dumps(payload)
        with io.BytesIO(data) as buf:
            file = discord.File(buf, filename="faq_cache")
            try:
                await message.edit(attachments=[file])
            except discord.Forbidden as exc:
                logger.error(
                    "Missing permissions to edit the FAQ cache message: %s",
                    exc,
                )
            except discord.HTTPException as exc:
                logger.error("Failed to update FAQ cache message: %s", exc)

    async def _fetch_faq_channel(
        self,
    ) -> discord.Thread | discord.ForumChannel | discord.TextChannel | None:
        """Resolve the configured FAQ channel or thread."""
        channel = self.bot.get_channel(self.faq_channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(self.faq_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

        if isinstance(
            channel, (discord.Thread, discord.ForumChannel, discord.TextChannel)
        ):
            return channel
        return None

    async def _iter_faq_threads(
        self,
    ) -> list[discord.Thread]:
        """Return active and archived threads for the configured FAQ channel."""
        channel = await self._fetch_faq_channel()
        if channel is None:
            return []

        if isinstance(channel, discord.Thread):
            return [channel]

        threads: list[discord.Thread] = []
        if isinstance(channel, (discord.ForumChannel, discord.TextChannel)):
            threads.extend(channel.threads)  # type: ignore[attr-defined]
            if hasattr(channel, "archived_threads"):
                try:
                    # Include archived threads to keep the cache complete.
                    threads.extend(
                        [
                            thread
                            async for thread in channel.archived_threads(limit=1000)  # type: ignore[attr-defined]
                        ]
                    )
                except discord.HTTPException:
                    pass

        return threads

    async def _refresh_cache_from_threads(self) -> None:
        """Refresh cache entries by scanning available FAQ threads."""
        threads = await self._iter_faq_threads()
        if not threads:
            return

        for thread in threads:
            keys = self._extract_keys(thread.name)
            if not keys:
                continue

            try:
                starter = thread.starter_message or await thread.fetch_message(
                    thread.id
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

            # The FAQ entry content must come from the thread starter message.
            if starter.channel.id != thread.id:
                continue

            primary_key = keys[0]
            content = starter.content or ""
            entry_value: FaqEntryValue = {
                "thread_id": thread.id,
                "name": thread.name,
                "content": content,
            }

            if (
                primary_key not in self._cache
                or self._cache[primary_key]["type"] != "entry"
            ):
                self._cache[primary_key] = {
                    "type": "entry",
                    "value": entry_value,
                }

            for alias in keys[1:]:
                self._cache[alias] = {
                    "type": "entry_key",
                    "value": primary_key,
                }

    def _resolve_entry(self, key: str) -> tuple[str, FaqEntryValue] | None:
        """Resolve keys to their primary entry and data payload."""
        entry = self._cache.get(key)
        if entry is None:
            return None

        if entry["type"] == "entry":
            return key, entry["value"]

        primary = entry["value"]
        primary_entry = self._cache.get(primary)
        if primary_entry and primary_entry["type"] == "entry":
            return primary, primary_entry["value"]

        return None

    async def _get_entries_for_keys(
        self, keys: list[str]
    ) -> tuple[list[tuple[str, FaqEntryValue]], list[str]]:
        """Return resolved entries and a list of missing keys."""
        await self._load_cache()

        resolved: list[tuple[str, FaqEntryValue]] = []
        missing: list[str] = []
        seen_primary: set[str] = set()

        for key in keys:
            normalized = self._normalize_key(key)
            entry = self._resolve_entry(normalized)
            if entry is None:
                missing.append(key)
                continue
            primary_id, value = entry
            if primary_id in seen_primary:
                continue
            seen_primary.add(primary_id)
            resolved.append((primary_id, value))

        if missing:
            # Cache miss: rescan threads and retry lookups once
            async with self._cache_lock:
                await self._refresh_cache_from_threads()
                await self._save_cache()

            still_missing = []
            for key in missing:
                normalized = self._normalize_key(key)
                entry = self._resolve_entry(normalized)
                if entry is None:
                    still_missing.append(key)
                    continue
                primary_id, value = entry
                if primary_id in seen_primary:
                    continue
                seen_primary.add(primary_id)
                resolved.append((primary_id, value))

            missing = still_missing

        return resolved, missing

    @staticmethod
    def _trim_text_to_limit(text: str, limit: int) -> str:
        """Trim text to fit a character limit while keeping an ellipsis."""
        if len(text) <= limit:
            return text
        if limit <= 3:
            return text[:limit]
        return text[: limit - 3] + "..."

    def _build_faq_embed(
        self, ctx: commands.Context[BotT], title: str, description: str, thread_id: int
    ) -> list[discord.Embed]:
        """Build FAQ embeds respecting title+description size constraints."""
        title = self._trim_text_to_limit(title, MAX_FAQ_EMBED_FIELDS)
        remaining = max(MAX_FAQ_EMBED_FIELDS - len(title), 0)
        description = self._trim_text_to_limit(description, remaining)
        embed_dict = {
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

    async def _send_faq_response(
        self, ctx: commands.Context[BotT], keys: Collection[str]
    ) -> None:
        """Send FAQ response embeds and enforce 'key' constraints."""
        if not keys:
            raise invocation_error(ctx, "You must provide at least one key.")

        if len(keys) > MAX_FAQ_KEYS:
            raise invocation_error(
                ctx,
                f"You can only request up to {MAX_FAQ_KEYS} keys at once.",
            )

        resolved, missing = await self._get_entries_for_keys(list(keys))

        if not resolved:
            raise invocation_error(
                ctx,
                "No FAQ entries were found for the provided keys.",
            )

        embeds: list[discord.Embed] = []
        for _, entry in resolved:
            description = (
                entry.get("content", "") or "(No content found for this entry.)"
            )
            embeds.extend(
                self._build_faq_embed(
                    ctx,
                    entry.get("name", "FAQ Entry"),
                    description,
                    entry.get("thread_id", self.faq_channel_id),
                )
            )

        if missing:
            embeds.extend(
                self._build_faq_embed(
                    ctx,
                    "Not Found",
                    "No FAQ entries were found for: " + ", ".join(missing),
                    self.faq_channel_id,
                )
            )

        if ctx.interaction:
            await ctx.interaction.response.send_message(embeds=embeds[:10])
            if len(embeds) > 10:
                for i in range(10, len(embeds), 10):
                    await ctx.interaction.followup.send(embeds=embeds[i : i + 10])
            return

        await self.send_or_edit_response(ctx, embeds=embeds[:10])

    @commands.guild_only()
    @commands.group(
        invoke_without_command=True,
        name="faq",
        usage="<keys>...",
        description="Look up FAQ entries by key.",
        extras=dict(
            response_deletion_with_reaction=True,
        ),
    )
    async def faq(self, ctx: commands.Context[BotT], *keys: str):
        """Look up FAQ entries by key.

        __**Parameters:**__

        **`<keys>...`**
        > One or more faq entry keys separated by spaces.
        """
        await self._send_faq_response(ctx, keys)

    @app_commands.command(
        name="faq",
        description="Look up FAQ entries by key.",
    )
    @app_commands.describe(
        keys="One or more keys separated by spaces.",
    )
    async def faq_app_command(
        self,
        interaction: discord.Interaction[BotT],
        keys: str,
    ):
        parts = [part.strip() for part in re.split(r"[\s,]+", keys) if part.strip()]
        await self._send_faq_response(
            await commands.Context[BotT].from_interaction(interaction),
            parts,
        )


@snakecore.commands.decorators.with_config_kwargs
async def setup(
    bot: BotT,
    faq_channel_id: int,
    faq_cache_channel_id: int,
    faq_cache_message_id: int,
    faq_entry_key_regexp: str = r"(?:[a-z\d\-]+(?:\s*\|\s*[a-z\d\-]+)*)",
    theme_color: int | discord.Color = 0xFFD868,
):
    await bot.add_cog(
        FAQChannelCog(
            bot,
            faq_channel_id,
            faq_cache_channel_id,
            faq_cache_message_id,
            faq_entry_key_regexp,
            theme_color=theme_color,
        )
    )
