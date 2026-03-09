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
                    title="FS.EXEC.TRANSITION: Program A",
                    agency="DoD",
                    scope="Compliance services",
                    estimated_value="$10M",
                    timeline="FY2026",
                    confidence="High",
                ),
                credentials=[
                    CredentialMatch(
                        title="Technology Risk Management & Governance",
                        client_challenge="Needed CMMC alignment",
                        approach="Control mapping and remediation",
                        value_provided="Passed readiness assessment",
                        industry="Financial Services",
                        technologies_used=["NIST 800-171"],
                        emd=None,
                        url="https://ishare.protiviti.com/cred/123",
                    ),
                    CredentialMatch(
                        title="Operational Risk Management Governance and Framework Support",
                        client_challenge="Needed first-line/second-line oversight alignment",
                        approach="RCSA assessments and governance workflow support",
                        value_provided="Improved governance visibility and audit readiness",
                        industry="Financial Services",
                        technologies_used=[],
                        emd="Jane Leader",
                        url="https://ishare.protiviti.com/cred/456",
                    ),
                    CredentialMatch(
                        title="Should Not Render Because Top 2 Cap",
                        client_challenge="Challenge",
                        approach="Approach",
                        value_provided="Value",
                        industry="Financial Services",
                        technologies_used=[],
                        emd=None,
                        url="https://ishare.protiviti.com/cred/789",
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
                analysis=(
                    "Named risk leadership aligns to payments expansion governance. "
                    "Movement sources: "
                    "https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro; "
                    "https://www.linkedin.com/posts/example_exec_post."
                ),
            ),
            SignalEvidence(
                signal_code="FS.MODEL_RISK.FINDINGS",
                signal_label="Model Risk Findings",
                status="Insufficient",
                evidence_quote="No public model findings were explicitly identified.",
                source_url="https://example.com/model-risk",
                source_title="Example",
                analysis="Insufficient evidence for confirmation.",
            ),
        ],
        phase2_footnotes=[
            "Verbatim quote: \"Capital One appointed ...\"\n"
            "Source title: FinTech Magazine\n"
            "Canonical URL: https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro\n"
            "Evidentiary linkage: Supports documented executive transition.",
            "Verbatim quote: \"No public model findings were explicitly identified.\"\n"
            "Source title: Example\n"
            "Canonical URL: https://example.com/model-risk\n"
            "Evidentiary linkage: This should not render in confirmed-only mode."
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
    assert "### EXECUTIVE SUMMARY — Scan-First Brief" in content
    assert "**Context Coverage:** Confirmed signals: 1 | Top opportunities: 1 | Distinct sources: 1" in content
    assert "**Deep Research Findings**" in content
    assert "**Credentials Agent Findings**" in content
    assert "**Combined Report & Action Items**" in content
    assert "PHASE 2 — Analytical Synthesis (Evidence-Locked)" in content
    assert "PHASE 3 — Opportunity Analysis & Client Enablement" in content
    assert "Governing Headline:" in content
    assert "Executive Transition (FS.EXEC.TRANSITION)" in content
    assert "— Confirmed" in content
    assert "Model Risk Findings (FS.MODEL_RISK.FINDINGS)" in content
    assert "— Insufficient" in content
    assert "Verbatim quote:" in content
    assert "Canonical URL:" in content
    assert "Additional discovered movement sources (candidate set):" in content
    assert "- https://www.linkedin.com/posts/example_exec_post" in content
    assert "1. Verbatim quote:" in content
    assert "   Source title:" in content
    assert "   Canonical URL:" in content
    assert "   Evidentiary linkage:" in content
    assert "2. Verbatim quote:" in content
    assert "Evidentiary linkage:" in content
    assert "#### Opportunity 1 — FS.EXEC.TRANSITION" in content
    assert "**Opportunity Overview**" in content
    assert "**Detailed Technical Explanation**" in content
    assert "**Layman's Explanation**" in content
    assert "**Relevant Service Lines (mapped ONLY to this opportunity's confirmed signals)**" in content
    assert "**Relevant Protiviti Credentials (if applicable)**" in content
    assert "Credential 1" in content
    assert "Matched credential: Technology Risk Management & Governance" in content
    assert "Client challenge: Needed CMMC alignment" in content
    assert "What we did: Control mapping and remediation" in content
    assert "Value provided: Passed readiness assessment" in content
    assert "Industry: Financial Services" in content
    assert "Technologies used: NIST 800-171" in content
    assert "EMD: Not provided" in content
    assert "Why this matches:" in content
    assert "URL: https://ishare.protiviti.com/cred/123" in content
    assert "Credential 2" in content
    assert "Matched credential: Operational Risk Management Governance and Framework Support" in content
    assert "EMD: Jane Leader" in content
    assert "Should Not Render Because Top 2 Cap" not in content
    assert "**Sources (signal-aligned)**" in content
    assert content.count("---") >= 2
    assert "Sources (1 distinct unique citations)" in content


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
    assert "Lookup Failed=0" in content


def test_formatter_demo_profile_shows_confirmed_only_and_hides_lookup_failed_count():
    report = _build_phase_report()
    os.environ["BD_RUNTIME_PROFILE"] = "demo"
    os.environ["BD_FAILURE_VISIBILITY"] = "suppressed"
    os.environ["BD_SHOW_PIPELINE_DIAGNOSTICS"] = "true"
    try:
        section = format_bd_report_as_section(report)
    finally:
        os.environ.pop("BD_RUNTIME_PROFILE", None)
        os.environ.pop("BD_FAILURE_VISIBILITY", None)
        os.environ.pop("BD_SHOW_PIPELINE_DIAGNOSTICS", None)

    content = section["content"]
    assert "Model Risk Findings (FS.MODEL_RISK.FINDINGS)" not in content
    assert "Lookup Failed=0" not in content


def test_formatter_uses_position_fallback_for_credentials_cards_when_signal_code_unavailable():
    report = _build_phase_report()
    report.top_opportunities[0].opportunity.title = "Program A rewritten by synthesis"
    section = format_bd_report_as_section(report)

    content = section["content"]
    assert "Matched credential: Technology Risk Management & Governance" in content
    assert "Matched credential: Operational Risk Management Governance and Framework Support" in content


def test_non_phase_layout_remains_legacy():
    report = MDReport(
        trigger_summary="Legacy trigger",
        executive_summary="Legacy executive summary",
        top_opportunities=[],
        signals_detected=[],
        recommended_actions=[],
        generated_at=datetime.now(),
        confidence_note="Legacy confidence",
    )

    section = format_bd_report_as_section(report)
    assert section is not None
    content = section["content"]
    assert "### Executive Summary" in content
    assert "### EXECUTIVE SUMMARY — Scan-First Brief" not in content
    assert "PHASE 2 — Analytical Synthesis (Evidence-Locked)" not in content
