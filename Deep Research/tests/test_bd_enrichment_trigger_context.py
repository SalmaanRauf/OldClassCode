"""
Tests for BD trigger enrichment context building.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bd_trigger_context import build_trigger_for_bd_enrichment


def test_build_trigger_uses_structured_session_params_and_prompt_context():
    trigger = build_trigger_for_bd_enrichment(
        sector="defense",
        user_query=(
            "Research Defense opportunities for Hanwha with CMMC signals. "
            "Filter for CONUS, minimum contract value of $1M, within the last 100 days."
        ),
        session_params={
            "signals": ["CMMC", "IV&V"],
            "company": "Hanwha",
            "geography": "CONUS",
            "time_window": "100 days",
            "min_value": "$1M",
        },
    )

    assert trigger.sector == "Defense"
    assert trigger.signals == ["CMMC", "IV&V"]
    assert trigger.company_focus == "Hanwha"
    assert trigger.geography == "CONUS"
    assert trigger.time_window_days == 100
    assert trigger.min_value_usd == 1_000_000
    assert trigger.user_prompt_context is not None
    assert "Hanwha" in trigger.user_prompt_context
    assert len(trigger.user_prompt_context) <= 600


def test_build_trigger_without_session_params_still_builds():
    trigger = build_trigger_for_bd_enrichment(
        sector="defense",
        user_query=(
            "Research Defense sector opportunities for Hanwha focusing on CMMC signals. "
            "Filter for CONUS geography with minimum contract value of $1M within the last 100 days."
        ),
        session_params={},
    )

    assert trigger.sector == "Defense"
    assert trigger.company_focus == "Hanwha"
    assert trigger.geography == "CONUS"
    assert trigger.time_window_days == 100
    assert trigger.min_value_usd == 1_000_000
    assert "CMMC" in trigger.signals
