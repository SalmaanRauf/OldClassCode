"""
Tests for replay summary console formatting.
"""
from datetime import datetime
from io import StringIO
from contextlib import redirect_stdout
import os

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import MDReport
from scripts.replay_bd_from_deep_research import _print_report_summary


def test_replay_summary_shows_failed_lookup_count_in_production_output():
    report = MDReport(
        trigger_summary="FS trigger",
        executive_summary="Summary",
        top_opportunities=[],
        signals_detected=[],
        recommended_actions=[],
        generated_at=datetime.now(),
        confidence_note="High confidence.",
        opportunity_extraction_status="Parsed",
        opportunities_extracted_count=3,
        lookups_executed_count=3,
        credentials_status_counts={"Matched": 2, "No Match": 1, "Lookup Failed": 4},
        synthesis_status="synthesized",
    )

    stream = StringIO()
    with redirect_stdout(stream):
        _print_report_summary(report)
    output = stream.getvalue()

    assert "credentials_status_counts: matched=2, no_match=1, failed=4" in output


def test_replay_summary_demo_profile_omits_failed_lookup_count():
    os.environ["BD_RUNTIME_PROFILE"] = "demo"
    os.environ["BD_FAILURE_VISIBILITY"] = "suppressed"
    report = MDReport(
        trigger_summary="FS trigger",
        executive_summary="Summary",
        top_opportunities=[],
        signals_detected=[],
        recommended_actions=[],
        generated_at=datetime.now(),
        confidence_note="High confidence.",
        opportunity_extraction_status="Parsed",
        opportunities_extracted_count=3,
        lookups_executed_count=3,
        credentials_status_counts={"Matched": 2, "No Match": 1, "Lookup Failed": 4},
        synthesis_status="synthesized",
    )

    stream = StringIO()
    try:
        with redirect_stdout(stream):
            _print_report_summary(report)
    finally:
        os.environ.pop("BD_RUNTIME_PROFILE", None)
        os.environ.pop("BD_FAILURE_VISIBILITY", None)
    output = stream.getvalue()

    assert "credentials_status_counts: matched=2, no_match=1" in output
    assert "failed=" not in output
