"""
Tests for BD report formatter phase rendering and diagnostics toggles.
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
    PhaseOpportunity,
    SignalEvidence,
)


def _build_phase_report() -> MDReport:
    return MDReport(
        trigger_summary="Financial services trigger",
        executive_summary=(
            "Deep Research Findings\n"
            "Verified public signals detected.\n\n"
            "Credentials Agent Findings\n"
            "- Matched opportunities: 1\n"
            "- No-match opportunities: 0\n"
            "- Lookup failures: 0\n\n"
            "Combined Report & Action Items\n"
            "- Prioritize phase-aligned opportunities."
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
        opportunity_extraction_reason="Parsed 1 opportunities using fs_signal_derivation.",
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="batched_single_call",
        opportunities_source="fs_signal_derivation",
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
                sector="Financial Services",
                query_text="FULL QUERY TEXT",
                raw_response_text='{"matches":[{"title":"Defense CMMC Credential"}]}',
                parse_outcome="json_parsed_with_matches",
                lookup_status="Matched",
                duration_ms=12.34,
                match_count=1,
            )
        ],
        phase2_headline="Capital One is balancing remediation execution with regulatory deliverable cadence.",
        phase2_signal_evidence=[
            SignalEvidence(
                signal_code="FS.EXEC.TRANSITION",
                signal_label="Executive Transition",
                status="Confirmed",
                evidence_quote="Capital One appointed ... Business Chief Risk Officer ...",
                source_url="https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro",
                source_title="FinTech Magazine",
                analysis="Named risk leadership aligns to payments expansion governance.",
            )
        ],
        phase2_footnotes=[
            "\"Capital One appointed ...\" — FinTech Magazine; https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"
        ],
        phase3_opportunities=[
            PhaseOpportunity(
                derived_from_signal="FS.EXEC.TRANSITION",
                overview="Risk leadership transition creates governance alignment opportunity.",
                technical_explanation="Define operating model, control ownership, and escalation paths.",
                layman_explanation="Set clear guardrails early so growth does not require rework later.",
                relevant_service_lines=[
                    "Risk governance and operating model advisory",
                    "Control framework design for new initiatives",
                ],
                credentials_summary="No materially aligned credentials identified.",
                recommended_actions=[
                    "Facilitate a mandate translation workshop within the next 30-90 days."
                ],
                sources=[
                    "https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"
                ],
            )
        ],
        phase_sources=[
            "https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"
        ],
        layout_version="fs_evidence_locked_v1",
    )


def test_formatter_renders_phase_layout_by_default():
    report = _build_phase_report()
    section = format_bd_report_as_section(report)

    assert section is not None
    content = section["content"]
    assert "PHASE 2 — Analytical Synthesis (Evidence-Locked)" in content
    assert "PHASE 3 — Opportunity Analysis & Client Enablement" in content
    assert "Executive Transition (FS.EXEC.TRANSITION)" in content
    assert "— Confirmed" in content
    assert "Opportunity 1 (Derived from FS.EXEC.TRANSITION)" in content


def test_formatter_hides_diagnostics_by_default():
    report = _build_phase_report()
    os.environ.pop("BD_SHOW_PIPELINE_DIAGNOSTICS", None)
    section = format_bd_report_as_section(report)

    content = section["content"]
    assert "### Pipeline Diagnostics" not in content
    assert "### Credentials Evidence (Full I/O)" not in content
    assert "### Credentials Batch I/O (Full)" not in content


def test_formatter_can_show_diagnostics_with_toggle():
    report = _build_phase_report()
    os.environ["BD_SHOW_PIPELINE_DIAGNOSTICS"] = "true"
    try:
        section = format_bd_report_as_section(report)
    finally:
        os.environ.pop("BD_SHOW_PIPELINE_DIAGNOSTICS", None)

    content = section["content"]
    assert "### Pipeline Diagnostics" in content
    assert "### Credentials Evidence (Full I/O)" in content
    assert "### Credentials Batch I/O (Full)" in content
