"""Three-tier permission gate for the GENESIS hands module.

Verdict for an action dict {"kind", "target", "risk"} is one of
"allow" | "ask" | "deny".

An action may also carry "command_text": the real payload for kinds that
execute one (e.g. run_command's joined argv). Rules may then include an
optional "command" glob matched against command_text. This closes the
bypass where a never-tier rule matched only "target" while the backend
executed params.command.

Rules live in permissions.json with three tiers: auto / ask / never.
Evaluation order is fixed:
    1. "never" tier matches -> "deny" (always wins, including over auto)
    2. "auto" tier matches  -> "allow"
    3. "ask" tier matches   -> "ask"
    4. nothing matches      -> "ask"   (FAIL-CLOSED)

Rule fields are optional glob patterns; a missing field matches anything.
Matching is case-insensitive (casefold) so "FORMAT C:" cannot dodge a
"format *" rule on any platform.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Literal

Verdict = Literal["allow", "ask", "deny"]

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_RULES_PATH = _PACKAGE_DIR / "permissions.json"

_REQUIRED_ACTION_FIELDS = ("kind", "target", "risk")
_OPTIONAL_ACTION_FIELDS = ("command_text",)
_VALID_RISKS = ("low", "medium", "high")
_TIER_NAMES = ("auto", "ask", "never")
_RULE_FIELDS = ("kind", "target", "risk", "command")


class GateConfigError(ValueError):
    """Raised when permissions.json or an action dict is malformed."""


def load_rules(path: str | Path | None = None) -> dict:
    """Load and validate the tier rules.

    Fail-closed on bad config: raises GateConfigError instead of silently
    allowing everything.
    """
    rules_path = Path(path) if path else _DEFAULT_RULES_PATH
    try:
        with open(rules_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateConfigError(
            f"cannot load permission rules from {rules_path}: {exc}"
        ) from exc

    tiers = data.get("tiers")
    if not isinstance(tiers, dict):
        raise GateConfigError("permissions.json must contain a 'tiers' object")
    for tier in _TIER_NAMES:
        rules = tiers.get(tier)
        if not isinstance(rules, list):
            raise GateConfigError(f"tier '{tier}' must be a list of rules")
        for rule in rules:
            _validate_rule(rule, tier)
    return data


def _validate_rule(rule: object, tier: str) -> None:
    if not isinstance(rule, dict):
        raise GateConfigError(f"rule in tier '{tier}' must be an object")
    for field in _RULE_FIELDS:
        if field in rule:
            value = rule[field]
            if not isinstance(value, str):
                raise GateConfigError(
                    f"rule field '{field}' in tier '{tier}' must be a string"
                )
            if field == "risk" and value not in _VALID_RISKS and value != "*":
                raise GateConfigError(
                    f"invalid risk value in tier '{tier}': {value!r}"
                )


def _match_value(value: object, pattern: str) -> bool:
    """Case-insensitive glob match (defeats 'FORMAT C:' vs 'format *')."""
    return fnmatch.fnmatch(str(value).casefold(), pattern.casefold())


def _rule_matches(rule: dict, action: dict) -> bool:
    for field in ("kind", "target", "risk"):
        pattern = rule.get(field)
        if pattern is None:
            continue  # unspecified field matches anything
        if not _match_value(action[field], pattern):
            return False
    command_pattern = rule.get("command")
    if command_pattern is not None:
        # Matched against the action's real payload, not its label.
        if not _match_value(action.get("command_text", ""), command_pattern):
            return False
    return True


def _validate_action(action: object) -> dict:
    if not isinstance(action, dict):
        raise GateConfigError("action must be a dict")
    missing = [f for f in _REQUIRED_ACTION_FIELDS if f not in action]
    if missing:
        raise GateConfigError(f"action is missing required fields: {missing}")
    if action["risk"] not in _VALID_RISKS:
        raise GateConfigError(f"invalid action risk: {action['risk']!r}")
    for field in _OPTIONAL_ACTION_FIELDS:
        if field in action and not isinstance(action[field], str):
            raise GateConfigError(f"optional action field '{field}' must be a string")
    return action


def check(action: dict, rules: dict | None = None) -> Verdict:
    """Return the verdict for an action: "allow", "ask", or "deny".

    Fail-closed: an action matching no rule returns "ask". The "never" tier
    always wins and returns "deny". A malformed action raises GateConfigError
    (the caller must not treat garbage as allowed).
    """
    action = _validate_action(action)
    rules = rules if rules is not None else load_rules()
    tiers = rules["tiers"]

    for rule in tiers.get("never", []):
        if _rule_matches(rule, action):
            return "deny"
    for rule in tiers.get("auto", []):
        if _rule_matches(rule, action):
            return "allow"
    for rule in tiers.get("ask", []):
        if _rule_matches(rule, action):
            return "ask"
    return "ask"  # FAIL-CLOSED default
