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
    assert "FULL QUERY TEXT :: include everything line1\nline2\nline3" in content
    assert 'FULL RAW RESPONSE :: {"matches":[{"title":"Defense CMMC Credential"}]}' in content
    assert "Title: Defense CMMC Credential" in content
