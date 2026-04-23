"""
Tests for account-research direct-input parsing.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.account_research_input import (  # noqa: E402
    AccountResearchInputError,
    parse_account_research_input,
)


def test_parse_account_research_input_accepts_company_only() -> None:
    parsed = parse_account_research_input("BAE Systems")

    assert parsed.account_name == "BAE Systems"
    assert parsed.focus_hint is None
    assert parsed.raw_input == "BAE Systems"


def test_parse_account_research_input_extracts_focus_hint_from_pipe() -> None:
    parsed = parse_account_research_input("Sayari | PE / PortCo context")

    assert parsed.account_name == "Sayari"
    assert parsed.focus_hint == "PE / PortCo context"


def test_parse_account_research_input_extracts_focus_hint_from_focus_on_clause() -> None:
    parsed = parse_account_research_input("BAE Systems - focus on Metro DC")

    assert parsed.account_name == "BAE Systems"
    assert parsed.focus_hint == "Metro DC"


def test_parse_account_research_input_extracts_focus_hint_from_generic_dash_suffix() -> None:
    parsed = parse_account_research_input("BAE Systems - Metro DC target account")

    assert parsed.account_name == "BAE Systems"
    assert parsed.focus_hint == "Metro DC target account"


def test_parse_account_research_input_extracts_focus_hint_from_comma_focus_clause() -> None:
    parsed = parse_account_research_input("CareFirst BlueCross BlueShield, focus on PGP Elite expansion")

    assert parsed.account_name == "CareFirst BlueCross BlueShield"
    assert parsed.focus_hint == "PGP Elite expansion"


@pytest.mark.parametrize(
    ("raw_input", "expected_fragment"),
    [
        ("BAE Systems\nCareFirst", "one account at a time"),
        ("BAE Systems; CareFirst", "one account at a time"),
        ("- BAE Systems\n- CareFirst", "one account at a time"),
    ],
)
def test_parse_account_research_input_rejects_multi_account_input(
    raw_input: str,
    expected_fragment: str,
) -> None:
    with pytest.raises(AccountResearchInputError) as excinfo:
        parse_account_research_input(raw_input)

    assert expected_fragment in str(excinfo.value)
