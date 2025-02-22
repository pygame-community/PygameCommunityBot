# Base class for common message validation logic
import re
from typing import Literal
import discord
from .utils import MISSING, URL_PATTERN, DiscordMessageRule, EnforceType, is_vcs_url


class ContentRule(DiscordMessageRule, name="content"):
    """A rule for validating if a Discord message contains only, any (the default), or no content."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: Literal["any", "only", "none"] = "any",
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of content according to the specified arguments."""

        has_content = bool(message.content)
        only_content = not has_content and not (message.attachments or message.embeds)

        if enforce_type == "always" and arg == "only" and not only_content:
            return (False, "Message must always contain only text content", None)

        if enforce_type == "always" and arg == "any" and not has_content:
            return (False, "Message must always contain text content", None)

        if enforce_type == "always" and arg == "none" and has_content:
            return (False, "Message must always contain no text content", None)

        if enforce_type == "never" and arg == "only" and only_content:
            return (False, "Message must never contain only text content", None)

        if enforce_type == "never" and arg == "any" and has_content:
            return (False, "Message must never contain text content", None)

        if enforce_type == "never" and arg == "none" and not has_content:
            return (False, "Message must never contain no text content", None)

        return (True, None, None)

    @staticmethod
    def validate_arg(arg: Literal["any", "only", "none"]) -> str | None:
        if arg not in (MISSING, "any", "only", "none"):
            return "Argument must be one of 'any', 'only', or 'none'"


class ContentLengthRule(DiscordMessageRule, name="content-length"):
    """A rule for validating if a Discord message contains text content within the specified length range."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: tuple[int, int],
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of text content within the specified length range."""

        if not isinstance(arg, tuple) or len(arg) != 2:
            raise ValueError("Argument must be a tuple of two integers")

        min_length, max_length = arg

        min_length = min_length or 0
        max_length = max_length or 4096

        if min_length > max_length:
            raise ValueError(
                "Minimum length must be less than or equal to maximum length"
            )

        content_length = len(message.content)

        if enforce_type == "always" and not (
            min_length <= content_length <= max_length
        ):
            return (
                False,
                f"Message must always contain text content within {min_length}-{max_length} characters",
                None,
            )

        if enforce_type == "never" and (min_length <= content_length <= max_length):
            return (
                False,
                f"Message must never contain text content within {min_length}-{max_length} characters",
                None,
            )

        return (True, None, None)

    @staticmethod
    def validate_arg(arg: tuple[int | None, int | None]) -> str | None:
        if (not isinstance(arg, (list, tuple))) or (
            isinstance(arg, (list, tuple)) and len(arg) != 2
        ):
            return "Argument must be a list/tuple of two integers"

        if arg[0] is not None and arg[1] is not None:
            if arg[0] > arg[1]:
                return "Minimum length must be less than or equal to maximum length"
        elif arg[0] is not None:
            if arg[0] < 0:
                return "Minimum length must be greater than or equal to 0"
        elif arg[1] is not None:
            if arg[1] < 0:
                return "Maximum length must be greater than or equal to 0"


class URLsRule(DiscordMessageRule, name="urls"):
    """A rule for validating if a Discord message contains only, at least one or no URLs."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: Literal["any", "only", "none"],
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of URLs according to the specified arguments."""

        search_obj = tuple(re.finditer(URL_PATTERN, message.content))
        links = tuple(match.group() for match in search_obj if match)
        any_urls = bool(links)
        only_urls = any_urls and sum(len(link) for link in links) == len(
            re.sub(r"\s", "", message.content)
        )
        no_urls = not any_urls

        if enforce_type == "always" and arg == "only" and not only_urls:
            return (False, "Message must always contain only URLs", None)

        if enforce_type == "always" and arg == "any" and not any_urls:
            return (False, "Message must always contain at least one URL", None)

        if enforce_type == "always" and arg == "none" and not no_urls:
            return (False, "Message must always contain no URLs", None)

        if enforce_type == "never" and arg == "only" and only_urls:
            return (False, "Message must never contain only URLs", None)

        if enforce_type == "never" and arg == "any" and any_urls:
            return (False, "Message must never contain at least one URL", None)

        if enforce_type == "never" and arg == "none" and no_urls:
            return (False, "Message must never contain no URLs", None)

        return (True, None, None)


# Rule for validating VCS URLs
class VCSURLsRule(DiscordMessageRule, name="vcs-urls"):
    """A rule for validating if a Discord message contains only, at least one (the default), or no valid VCS URLs."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: Literal["any", "all", "none"] = "any",
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of VCS URLs according to the specified arguments."""

        search_obj = tuple(re.finditer(URL_PATTERN, message.content or ""))
        links = tuple(match.group() for match in search_obj if match)
        any_vcs_urls = links and any(is_vcs_url(link) for link in links)
        no_vcs_urls = not any_vcs_urls
        all_vcs_urls = not any(not is_vcs_url(link) for link in links)

        if enforce_type == "always" and arg == "all" and not all_vcs_urls:
            return (False, "Message must always contain only valid VCS URLs", None)

        if enforce_type == "always" and arg == "any" and not any_vcs_urls:
            return (
                False,
                "Message must always contain at least one valid VCS URL",
                None,
            )

        if enforce_type == "always" and arg == "none" and not no_vcs_urls:
            return (False, "Message must always contain no valid VCS URLs", None)

        if enforce_type == "never" and arg == "all" and all_vcs_urls:
            return (False, "Message must never contain only valid VCS URLs", None)

        if enforce_type == "never" and arg == "any" and any_vcs_urls:
            return (
                False,
                "Message must never contain at least one valid VCS URL",
                None,
            )

        if enforce_type == "never" and arg == "none" and no_vcs_urls:
            return (False, "Message must never contain no valid VCS URLs", None)

        return (True, None, None)

    @staticmethod
    def validate_arg(arg: Literal["any", "all", "none"]) -> str | None:
        if arg not in (MISSING, "any", "all", "none"):
            return "Argument must be one of 'any', 'all', or 'none'"


class AttachmentsRule(DiscordMessageRule, name="attachments"):
    """A rule for validating if a Discord message contains only, at least one or no attachments."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: Literal["any", "only", "none"],
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of attachments according to the specified arguments."""

        any_attachments = bool(message.attachments)
        only_attachments = any_attachments and not (message.content or message.embeds)
        no_attachments = not any_attachments

        if enforce_type == "always" and arg == "only" and not only_attachments:
            return (False, "Message must always contain only attachments", None)

        if enforce_type == "always" and arg == "any" and not any_attachments:
            return (False, "Message must always contain at least one attachment", None)

        if enforce_type == "always" and arg == "none" and not no_attachments:
            return (False, "Message must always contain no attachments", None)

        if enforce_type == "never" and arg == "only" and only_attachments:
            return (False, "Message must never contain only attachments", None)

        if enforce_type == "never" and arg == "any" and any_attachments:
            return (False, "Message must never contain at least one attachment", None)

        if enforce_type == "never" and arg == "none" and no_attachments:
            return (False, "Message must never contain no attachments", None)

        return (True, None, None)


class EmbedsRule(DiscordMessageRule, name="embeds"):
    """A rule for validating if a Discord message contains only, at least one or no embeds."""

    @staticmethod
    def validate(
        enforce_type: EnforceType,
        message: discord.Message,
        arg: Literal["any", "only", "none"],
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        """Validate a message for the presence of embeds according to the specified arguments."""

        any_embeds = bool(message.embeds)
        only_embeds = any_embeds and not (message.content or message.attachments)
        no_embeds = not any_embeds

        if enforce_type == "always" and arg == "only" and not only_embeds:
            return (False, "Message must always contain only embeds", None)

        if enforce_type == "always" and arg == "any" and not any_embeds:
            return (False, "Message must always contain at least one embed", None)

        if enforce_type == "always" and arg == "none" and not no_embeds:
            return (False, "Message must always contain no embeds", None)

        if enforce_type == "never" and arg == "only" and only_embeds:
            return (False, "Message must never contain only embeds", None)

        if enforce_type == "never" and arg == "any" and any_embeds:
            return (False, "Message must never contain at least one embed", None)

        if enforce_type == "never" and arg == "none" and no_embeds:
            return (False, "Message must never contain no embeds", None)

        return (True, None, None)


RULE_MAPPING: dict[str, type[DiscordMessageRule]] = {
    "content": ContentRule,
    "content-length": ContentLengthRule,
    "urls": URLsRule,
    "vcs-urls": VCSURLsRule,
    "attachments": AttachmentsRule,
    "embeds": EmbedsRule,
}
