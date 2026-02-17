"""
Tests for deterministic opportunity selection policy.
"""
from datetime import date

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import BDTrigger, Opportunity
from services.opportunity_selector import select_top_opportunities


REFERENCE_DATE = date(2026, 2, 17)


def _opp(
    title: str,
    timeline: str | None = None,
    estimated_value: str | None = None,
    cmmc_level: str | None = None,
    confidence: str = "Medium",
):
    return Opportunity(
        title=title,
        scope=f"{title} scope",
        timeline=timeline,
        estimated_value=estimated_value,
        cmmc_level=cmmc_level,
        confidence=confidence,
    )


def test_rejects_explicit_out_of_window_dates():
    trigger = BDTrigger(sector="Defense", time_window_days=100)
    opportunities = [
        _opp("Old Opportunity", timeline="November 1, 2025"),
        _opp("Recent Opportunity", timeline="January 20, 2026"),
    ]

    selected, diagnostics = select_top_opportunities(opportunities, trigger, REFERENCE_DATE, top_n=3)

    assert [opp.title for opp in selected] == ["Recent Opportunity"]
    assert diagnostics.rejection_counts["out_of_window"] == 1


def test_rejects_below_minimum_value_when_parseable():
    trigger = BDTrigger(sector="Defense", min_value_usd=1_000_000)
    opportunities = [
        _opp("Below Min", estimated_value="$500K"),
        _opp("Above Min", estimated_value="$2M"),
    ]

    selected, diagnostics = select_top_opportunities(opportunities, trigger, REFERENCE_DATE, top_n=3)

    assert [opp.title for opp in selected] == ["Above Min"]
    assert diagnostics.rejection_counts["below_min_value"] == 1


def test_rejects_geography_mismatch_for_conus():
    trigger = BDTrigger(sector="Defense", geography="CONUS")
    opportunities = [
        _opp("OCONUS Support Program", timeline="January 30, 2026"),
        _opp("CONUS Integration Program", timeline="January 31, 2026"),
    ]

    selected, diagnostics = select_top_opportunities(opportunities, trigger, REFERENCE_DATE, top_n=3)

    assert [opp.title for opp in selected] == ["CONUS Integration Program"]
    assert diagnostics.rejection_counts["geography_mismatch"] == 1


def test_unknown_date_fallback_only_when_needed():
    trigger = BDTrigger(sector="Defense")
    opportunities = [
        _opp("Exact Date Opportunity", timeline="January 31, 2026"),
        _opp("Unknown Date One"),
        _opp("Unknown Date Two"),
    ]

    selected, diagnostics = select_top_opportunities(opportunities, trigger, REFERENCE_DATE, top_n=3)
    assert len(selected) == 3
    assert diagnostics.fallback_used is True

    enough_dated = [
        _opp("Dated A", timeline="February 10, 2026"),
        _opp("Dated B", timeline="February 12, 2026"),
        _opp("Dated C", timeline="February 14, 2026"),
        _opp("Unknown D"),
    ]
    selected_no_fallback, diagnostics_no_fallback = select_top_opportunities(
        enough_dated, trigger, REFERENCE_DATE, top_n=3
    )
    assert len(selected_no_fallback) == 3
    assert diagnostics_no_fallback.fallback_used is False
    assert "Unknown D" not in [opp.title for opp in selected_no_fallback]


def test_cmmc_signal_deprioritizes_non_cmmc_opportunities():
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    opportunities = [
        _opp("General Risk Program", timeline="February 10, 2026", confidence="High"),
        _opp("CMMC Compliance Program", timeline="February 11, 2026", cmmc_level="Level 2", confidence="Medium"),
    ]

    selected, diagnostics = select_top_opportunities(opportunities, trigger, REFERENCE_DATE, top_n=2)

    assert diagnostics.cmmc_required is True
    assert selected[0].title == "CMMC Compliance Program"
    assert diagnostics.selected_titles == [opp.title for opp in selected]
