# ABC for rules
from abc import ABC, abstractmethod
import re
from typing import Any, Literal, NotRequired, TypedDict
import discord

EnforceType = Literal["always", "never"]

MISSING: Any = object()


URL_PATTERN = re.compile(
    r"(?P<scheme>\w+):\/\/(?:(?P<userinfo>[\w_.-]+(?::[\w_.-]+)?)@)?(?P<host>(?:(?P<subdomain>[\w_-]+(?:\.[\w_-]+)*)\.)?(?P<domain>(?P<second_level_domain>[\w_-]+)\.(?P<tld>\w+))|(?P<plain_host>[\w_-]+))(?:\:(?P<port>\d+))?(?P<path>\/[\w.,@?^=%&:\/~+-]*)?(?:\?(?P<query>[\w.,@?^=%&:\/~+-]*))?(?:#(?P<fragment>[\w@?^=%&\/~+#-]*))?"
)


def is_vcs_url(url: str) -> bool:
    """Check if a URL points to a known VCS SaaS (e.g. GitHub, GitLab, Bitbucket)."""
    return bool(
        (match_ := (re.match(URL_PATTERN, url)))
        and match_.group("scheme") in ("https", "http")
        and match_.group("domain") in ("github.com", "gitlab.com", "bitbucket.org")
    )


class RuleSpecifier(TypedDict):
    name: str
    enforce_type: EnforceType
    arg: NotRequired[Any]
    description: NotRequired[str]


class RuleSpecifierPair(TypedDict):
    mode: Literal["and", "or"]
    clause1: "RuleSpecifier | RuleSpecifierPair | RuleSpecifierList"
    clause2: "RuleSpecifier | RuleSpecifierPair | RuleSpecifierList"
    description: NotRequired[str]


class RuleSpecifierList(TypedDict):
    mode: Literal["any", "all"]
    clauses: list["RuleSpecifier | RuleSpecifierPair | RuleSpecifierList"]
    description: NotRequired[str]


class BadRuleSpecifier(Exception):
    """Exception raised when a rule specifier is invalid."""

    pass


class DiscordMessageRule(ABC):
    name: str

    def __init_subclass__(cls, name: str) -> None:
        cls.name = name

    @staticmethod
    @abstractmethod
    def validate(
        enforce_type: EnforceType, message: discord.Message, arg: Any = None
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        ...

    @staticmethod
    def validate_arg(arg: Any) -> str | None:
        ...


class AsyncDiscordMessageRule(DiscordMessageRule, name="AsyncDiscordMessageRule"):
    @staticmethod
    @abstractmethod
    async def validate(
        enforce_type: EnforceType, message: discord.Message, arg: Any = None
    ) -> tuple[Literal[False], str, str | None] | tuple[Literal[True], None, None]:
        ...
