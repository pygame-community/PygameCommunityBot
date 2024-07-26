from typing import Callable, overload

import discord

from .rules import RULE_MAPPING
from .utils import (
    MISSING,
    BadRuleSpecifier,
    RuleSpecifier,
    RuleSpecifierList,
    RuleSpecifierPair,
)


def dispatch_rule_specifier_dict_validator(
    specifier: RuleSpecifier | RuleSpecifierPair | RuleSpecifierList,
) -> (
    Callable[[RuleSpecifier], None]
    | Callable[[RuleSpecifierPair], None]
    | Callable[[RuleSpecifierList], None]
    | None
):
    """Dispatch the appropriate validator to use to validate the structure of a rule specifier."""

    if "mode" in specifier:
        if specifier["mode"] in ("and", "or"):
            return validate_rule_specifier_dict_pair
        elif specifier["mode"] in ("any", "all"):
            return validate_rule_specifier_dict_list
    else:
        return validate_rule_specifier_dict_single

    return None


def validate_rule_specifier_dict_single(
    specifier: RuleSpecifier,
    depth_viz: str = "RuleSpecifier",
) -> None:
    """Validate a single rule specifier's structure."""

    if specifier["name"] not in RULE_MAPPING:
        raise BadRuleSpecifier(
            f"{depth_viz}.name: Unknown rule '{specifier['name']}'"
        )  # type
    elif "enforce_type" not in specifier or specifier["enforce_type"].lower() not in (
        "always",
        "never",
    ):
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifier 'enforce_type' field must be set to 'always' or 'never'"
        )

    error_string = RULE_MAPPING[specifier["name"]].validate_arg(
        specifier.get("arg", MISSING)
    )

    if error_string is not None:
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifier 'arg' field validation failed: {error_string}"
        )


def validate_rule_specifier_dict_pair(
    specifier: RuleSpecifierPair,
    depth_viz: str = "RuleSpecifierPair",
) -> None:
    """Validate a rule specifier pair's structure."""

    if "mode" not in specifier or specifier["mode"] not in ("and", "or"):
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierPair 'mode' field must be 'and' or 'or'"
        )

    if "clause1" not in specifier or "clause2" not in specifier:
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierPair must have 'clause1' "
            "and 'clause2' fields pointing to RuleSpecifier or RuleSpecifierPair or RuleSpecifierList dicts"
        )

    dict_validator1 = dispatch_rule_specifier_dict_validator(specifier["clause1"])
    dict_validator2 = dispatch_rule_specifier_dict_validator(specifier["clause2"])

    if dict_validator1 is None:
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierPair 'clause1' field "
            "must be a RuleSpecifier or RuleSpecifierPair or RuleSpecifierList dict"
        )

    if dict_validator2 is None:
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierPair 'clause2' field "
            "must be a RuleSpecifier or RuleSpecifierPair or RuleSpecifierList dict"
        )

    dict_validator1(specifier["clause1"], depth_viz=f"{depth_viz}.clause1")  # type: ignore
    dict_validator2(specifier["clause2"], depth_viz=f"{depth_viz}.clause2")  # type: ignore


def validate_rule_specifier_dict_list(
    specifier: RuleSpecifierList,
    depth_viz: str = "RuleSpecifierList",
) -> None:
    """Validate a rule specifier list's structure."""

    if "mode" not in specifier or specifier["mode"] not in ("any", "all"):
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierList 'mode' field must be 'any' or 'all'"
        )

    if "clauses" not in specifier or not specifier["clauses"]:
        raise BadRuleSpecifier(
            f"{depth_viz}.RuleSpecifierList must have 'clauses' "
            "field pointing to a list of RuleSpecifier or RuleSpecifierPair or RuleSpecifierList dicts"
        )

    for i, clause in enumerate(specifier["clauses"]):
        dict_validator = dispatch_rule_specifier_dict_validator(clause)
        if dict_validator is None:
            raise BadRuleSpecifier(
                f"{depth_viz}.clauses.{i} field "
                "must be a RuleSpecifier or RuleSpecifierPair or RuleSpecifierList dict"
            )

        dict_validator(clause, depth_viz=f"{depth_viz}.clauses.{i}")  # type: ignore


def dispatch_rule_specifier_message_validator(
    specifier: RuleSpecifier | RuleSpecifierPair | RuleSpecifierList,
):
    """Dispatch the appropriate validator to use to enforce a rule specifier on a Discord message."""

    if "mode" in specifier:
        if specifier["mode"] in ("and", "or"):
            return rule_specifier_pair_validate_message
        elif specifier["mode"] in ("any", "all"):
            return rule_specifier_list_validate_message
    return rule_specifier_single_validate_message


def rule_specifier_single_validate_message(
    specifier: RuleSpecifier,
    message: discord.Message,
    depth_viz: str = "",
) -> tuple[bool, str | None]:
    """Validate a message according to a single rule specifier."""

    rule = RULE_MAPPING[specifier["name"]]

    if "arg" in specifier:
        result = rule.validate(specifier["enforce_type"], message, specifier["arg"])
    else:
        result = rule.validate(specifier["enforce_type"], message)

    if "description" in specifier:
        # insert description of rule specifier if present
        return (result[0], specifier["description"] if not result[0] else None)

    return result


def rule_specifier_pair_validate_message(
    specifier: RuleSpecifierPair,
    message: discord.Message,
) -> tuple[bool, str | None]:
    """Validate a message according to a rule specifier pair."""

    success = True
    failure_description = specifier.get("description")

    validator1 = dispatch_rule_specifier_message_validator(specifier["clause1"])
    validator2 = dispatch_rule_specifier_message_validator(specifier["clause2"])

    result1 = validator1(specifier["clause1"], message)  # type: ignore
    result2 = None

    success = result1[0]
    if (specifier["mode"] == "and" and success) or (
        specifier["mode"] == "or" and not success
    ):
        result2 = validator2(specifier["clause2"], message)  # type: ignore
        success = bool(result2[0])

    if not result1[0] and failure_description is None:
        failure_description = result1[1]
    elif result2 and not result2[0] and failure_description is None:
        failure_description = result2[1]

    return (success, failure_description if not success else None)


def rule_specifier_list_validate_message(
    specifier: RuleSpecifierList,
    message: discord.Message,
) -> tuple[bool, str | None]:
    """Validate a message according to a rule specifier list."""

    success = True
    failure_description = specifier.get("description")

    if specifier["mode"] == "all":
        for i, clause in enumerate(specifier["clauses"]):
            validator = dispatch_rule_specifier_message_validator(clause)
            result = validator(clause, message)  # type: ignore
            if not result[0]:
                success = False
                if failure_description is None:
                    failure_description = result[1]
                break

    elif specifier["mode"] == "any":
        for i, clause in enumerate(specifier["clauses"]):
            validator = dispatch_rule_specifier_message_validator(clause)
            result = validator(clause, message)  # type: ignore
            success = success or result[0]

        if not success and failure_description is None:
            failure_description = result[1]

    return (success, failure_description if not success else None)


def validate_message(
    message: discord.Message,
    specifier: RuleSpecifier | RuleSpecifierPair | RuleSpecifierList,
) -> tuple[bool, str | None]:
    """Validate a message according to a rule specifier."""

    validator = dispatch_rule_specifier_message_validator(specifier)
    result = validator(specifier, message)  # type: ignore

    return result
