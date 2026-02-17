"""
Tests for BD report formatter credentials evidence rendering.
"""
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bd_report_formatter import format_bd_report_as_section
from models.bd_schemas import (
    MDReport,
    MDReportOpportunity,
    Opportunity,
    CredentialMatch,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
)


def _build_report() -> MDReport:
    return MDReport(
        trigger_summary="Defense trigger",
        executive_summary=(
            "Deep Research Findings\n"
            "Market signal detected.\n\n"
            "Credentials Agent Findings\n"
            "- Matched opportunities: 1\n"
            "- No-match opportunities: 0\n"
            "- Lookup failures: 0\n\n"
            "Combined Report & Action Items\n"
            "- Prioritize validated opportunities."
        ),
        top_opportunities=[
            MDReportOpportunity(
                opportunity=Opportunity(
                    title="Program A",
                    agency="DoD",
                    scope="Compliance services",
                    estimated_value="$10M",
                    timeline="FY2026",
                    confidence="High",
                ),
                credentials=[
                    CredentialMatch(
                        title="Defense CMMC Credential",
                        client_challenge="Needed CMMC alignment",
                        approach="Control mapping and remediation",
                        value_provided="Passed readiness assessment",
                        industry="Defense",
                        technologies_used=["NIST 800-171"],
                        url="https://ishare.protiviti.com/cred/123",
                    )
                ],
                validation_status="Validated",
                credentials_lookup_status="Matched",
            )
        ],
        signals_detected=["Signal 1"],
        recommended_actions=["Action 1"],
        generated_at=datetime.now(),
        confidence_note="High confidence.",
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason="Parsed 1 opportunities using narrative_fallback.",
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="batched_single_call",
        opportunities_source="atlas_digest",
        credentials_batch_diagnostics=CredentialsBatchDiagnostics(
            invoked=True,
            lookup_count_requested=3,
            lookup_count_returned=3,
            duration_ms=42.5,
            query_text="BATCH QUERY FULL TEXT line1\nline2",
            raw_response_text='{"results":[{"opportunity_id":"opp_1"}]}',
            parse_outcome="batch_json_parsed",
        ),
        credentials_evidence=[
            CredentialsLookupDiagnostics(
                opportunity_title="Program A",
                sector="Defense",
                query_text="FULL QUERY TEXT :: include everything line1\nline2\nline3",
                raw_response_text='FULL RAW RESPONSE :: {"matches":[{"title":"Defense CMMC Credential"}]}',
                parse_outcome="json_parsed_with_matches",
                lookup_status="Matched",
                duration_ms=12.34,
                match_count=1,
            )
        ],
    )


def test_formatter_includes_fixed_three_block_summary():
    report = _build_report()
    section = format_bd_report_as_section(report)

    assert section is not None
    content = section["content"]
    assert "Deep Research Findings" in content
    assert "Credentials Agent Findings" in content
    assert "Combined Report & Action Items" in content


def test_formatter_renders_full_credentials_evidence_without_truncation():
    report = _build_report()
    section = format_bd_report_as_section(report)

    content = section["content"]
    assert "### Credentials Evidence (Full I/O)" in content
    assert "Status: Matched" in content
    assert "Parse Outcome: json_parsed_with_matches" in content
    assert "Full Query Text: See **Credentials Batch I/O (Full)** section." in content
    assert "Full Raw Response Text: See **Credentials Batch I/O (Full)** section." in content
    assert "Title: Defense CMMC Credential" in content
    assert "Industry: Defense" in content
    assert "Client Challenge: Needed CMMC alignment" in content
    assert "Approach: Control mapping and remediation" in content
    assert "Value Provided: Passed readiness assessment" in content


def test_formatter_renders_full_batch_io_once():
    report = _build_report()
    section = format_bd_report_as_section(report)

    content = section["content"]
    assert "### Credentials Batch I/O (Full)" in content
    assert "BATCH QUERY FULL TEXT line1\nline2" in content
    assert '{"results":[{"opportunity_id":"opp_1"}]}' in content
    assert "Lookup Count Requested: 3" in content


def test_formatter_includes_pipeline_diagnostics():
    report = _build_report()
    section = format_bd_report_as_section(report)

    content = section["content"]
    assert "### Pipeline Diagnostics" in content
    assert "Opportunities Extracted: 1" in content
    assert "Extraction Status: Parsed" in content
    assert "Lookups Executed: 1" in content
    assert "Credentials Lookup Mode: batched_single_call" in content
    assert "Opportunities Source: atlas_digest" in content
    assert "Lookup Status Counts: Matched=1, No Match=0, Lookup Failed=0" in content
