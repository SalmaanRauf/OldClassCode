"""
Tests for deterministic BD trigger construction.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bd_trigger_builder import build_bd_trigger


def test_build_trigger_from_form_params():
    trigger = build_bd_trigger(
        sector="defense",
        user_query="",
        session_params={
            "signals": "CMMC, IV&V",
            "company": "Hanwha",
            "geography": "CONUS",
            "min_value": "1M",
            "time_window": "last 100 days",
        },
    )

    assert trigger.sector == "Defense"
    assert trigger.signals == ["CMMC", "IV&V"]
    assert trigger.company_focus == "Hanwha"
    assert trigger.geography == "CONUS"
    assert trigger.time_window_days == 100
    assert trigger.min_value_usd == 1_000_000


def test_build_trigger_from_query_fallbacks():
    query = (
        "Research Defense sector opportunities for Hanwha focusing on CMMC and RMF signals. "
        "Filter for CONUS geography with minimum contract value of $2.5B within the past 90 days."
    )
    trigger = build_bd_trigger(sector="Defense", user_query=query, session_params={})

    assert trigger.sector == "Defense"
    assert "CMMC" in trigger.signals
    assert "RMF" in trigger.signals
    assert trigger.company_focus == "Hanwha"
    assert trigger.geography == "CONUS"
    assert trigger.time_window_days == 90
    assert trigger.min_value_usd == 2_500_000_000


def test_trigger_defaults_and_clamps():
    trigger = build_bd_trigger(
        sector="general",
        user_query="Look for opportunities",
        session_params={"time_window": "within 900 days", "signals": ""},
    )
    assert trigger.sector == "General"
    assert trigger.time_window_days == 365
    assert trigger.signals == []
    assert trigger.min_value_usd is None

    trigger_malformed = build_bd_trigger(
        sector="general",
        user_query="Look for opportunities",
        session_params={"time_window": "abc"},
    )
    assert trigger_malformed.time_window_days == 30


def test_query_without_money_does_not_set_min_value_from_day_count():
    trigger = build_bd_trigger(
        sector="defense",
        user_query="Research defense opportunities within the last 100 days.",
        session_params={},
    )
    assert trigger.time_window_days == 100
    assert trigger.min_value_usd is None
