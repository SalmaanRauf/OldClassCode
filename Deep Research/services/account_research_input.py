"""
Helpers for parsing direct-input account research requests.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional


class AccountResearchInputError(ValueError):
    """Raised when the direct-input account research request is invalid."""


@dataclass(frozen=True)
class AccountResearchInput:
    account_name: str
    raw_input: str
    focus_hint: Optional[str] = None


def parse_account_research_input(raw_input: str) -> AccountResearchInput:
    cleaned = " ".join(str(raw_input or "").split())
    if not cleaned:
        raise AccountResearchInputError("Please type one target account name.")

    multiline = [line.strip() for line in str(raw_input or "").splitlines() if line.strip()]
    if len(multiline) > 1:
        raise AccountResearchInputError(
            "This mode supports one account at a time. Please send one account name."
        )
    if ";" in cleaned:
        raise AccountResearchInputError(
            "This mode supports one account at a time. Please send one account name."
        )

    if cleaned.startswith("- "):
        raise AccountResearchInputError(
            "This mode supports one account at a time. Please send one account name."
        )

    without_prefix = re.sub(r"^\s*account\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    account_name = without_prefix
    focus_hint: Optional[str] = None

    pipe_parts = [part.strip() for part in without_prefix.split("|", 1)]
    if len(pipe_parts) == 2 and pipe_parts[0] and pipe_parts[1]:
        account_name, focus_hint = pipe_parts[0], pipe_parts[1]
    else:
        focus_match = re.match(
            r"^(?P<account>.+?)\s*-\s*focus on\s+(?P<focus>.+)$",
            without_prefix,
            flags=re.IGNORECASE,
        )
        if focus_match:
            account_name = focus_match.group("account").strip()
            focus_hint = focus_match.group("focus").strip()
        else:
            comma_focus_match = re.match(
                r"^(?P<account>.+?)\s*,\s*focus on\s+(?P<focus>.+)$",
                without_prefix,
                flags=re.IGNORECASE,
            )
            if comma_focus_match:
                account_name = comma_focus_match.group("account").strip()
                focus_hint = comma_focus_match.group("focus").strip()
            elif " - " in without_prefix:
                account_candidate, focus_candidate = [part.strip() for part in without_prefix.split(" - ", 1)]
                if account_candidate and focus_candidate:
                    account_name = account_candidate
                    focus_hint = focus_candidate

    if not account_name:
        raise AccountResearchInputError("Please type one target account name.")

    return AccountResearchInput(
        account_name=account_name,
        raw_input=cleaned,
        focus_hint=focus_hint or None,
    )
