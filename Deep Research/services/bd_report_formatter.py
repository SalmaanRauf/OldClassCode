"""
Formatting helpers for BD report rendering in Chainlit surfaces.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Any, Optional, List

from models.bd_schemas import (
    MDReport,
    CredentialMatch,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
)


def format_bd_report_as_section(report: MDReport) -> Optional[Dict[str, Any]]:
    """Format an MDReport into a Deep Research section payload."""
    if not report:
        return None

    show_diagnostics = os.getenv("BD_SHOW_PIPELINE_DIAGNOSTICS", "false").lower() in {"1", "true", "yes"}
    if report.layout_version == "fs_evidence_locked_v1" or report.phase2_signal_evidence or report.phase3_opportunities:
        content = _format_phase_layout(report, show_diagnostics=show_diagnostics)
        return {
            "title": "🎯 BD Analysis & Credentials Validation",
            "content": content,
            "citations": [],
        }

    lines: List[str] = []

    if report.executive_summary:
        lines.append("### Executive Summary")
        lines.append(report.executive_summary)
        lines.append("")

    if report.top_opportunities:
        lines.append("### Validated Opportunities")
        lines.append("")
        for index, opp_report in enumerate(report.top_opportunities, 1):
            opp = opp_report.opportunity
            status_emoji = {
                "Validated": "✅",
                "Partial": "🔶",
                "No Internal Data": "❓",
            }.get(opp_report.validation_status, "❓")

            lines.append(f"**{index}. {opp.title}** {status_emoji}")
            if opp.agency:
                lines.append(f"   - Agency: {opp.agency}")
            if opp.estimated_value:
                lines.append(f"   - Value: {opp.estimated_value}")
            if opp.timeline:
                lines.append(f"   - Timeline: {opp.timeline}")
            lines.append(f"   - Validation: {opp_report.validation_status}")
            lines.append(f"   - Credentials Lookup Status: {opp_report.credentials_lookup_status}")

            if opp_report.credentials:
                lines.append("   - **Supporting Credentials:**")
                for cred in opp_report.credentials[:2]:
                    if cred.url:
                        lines.append(f"     - [{cred.title}]({cred.url})")
                    else:
                        lines.append(f"     - {cred.title}")
            lines.append("")

    if show_diagnostics:
        lines.extend(_format_pipeline_diagnostics(report))
        if report.credentials_lookup_mode == "batched_single_call" and report.credentials_batch_diagnostics:
            lines.extend(_format_credentials_batch_io(report))
        lines.extend(_format_credentials_evidence(report))

    if report.signals_detected:
        lines.append("### Key Signals Detected")
        for signal in report.signals_detected[:5]:
            lines.append(f"• {signal}")
        lines.append("")

    if report.recommended_actions:
        lines.append("### Recommended Next Steps")
        for action in report.recommended_actions[:5]:
            lines.append(f"• {action}")
        lines.append("")

    if report.confidence_note:
        lines.append(f"*{report.confidence_note}*")

    return {
        "title": "🎯 BD Analysis & Credentials Validation",
        "content": "\n".join(lines),
        "citations": [],
    }


def _split_three_block_summary(summary: str) -> Optional[Dict[str, str]]:
    text = (summary or "").strip()
    headings = [
        "Deep Research Findings",
        "Credentials Agent Findings",
        "Combined Report & Action Items",
    ]

    positions: List[int] = []
    cursor = 0
    for heading in headings:
        position = text.find(heading, cursor)
        if position < 0:
            return None
        positions.append(position)
        cursor = position + len(heading)

    sections: Dict[str, str] = {}
    for index, heading in enumerate(headings):
        start = positions[index] + len(heading)
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        sections[heading] = text[start:end].strip()
    return sections


def _distinct_sources(sources: Optional[List[str]]) -> List[str]:
    seen = set()
    distinct: List[str] = []
    for source in sources or []:
        normalized = source.strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        distinct.append(normalized)
    return distinct


def _format_scan_first_summary(report: MDReport, distinct_source_count: int) -> List[str]:
    lines: List[str] = ["### EXECUTIVE SUMMARY — Scan-First Brief", ""]
    confirmed_signal_count = len(
        [item for item in (report.phase2_signal_evidence or []) if item.status == "Confirmed"]
    )
    top_opportunity_count = len(report.top_opportunities or [])
    if top_opportunity_count == 0 and report.phase3_opportunities:
        top_opportunity_count = len(report.phase3_opportunities)
    lines.append(
        "**Context Coverage:** "
        f"Confirmed signals: {confirmed_signal_count} | "
        f"Top opportunities: {top_opportunity_count} | "
        f"Distinct sources: {distinct_source_count}"
    )
    lines.append("")

    sections = _split_three_block_summary(report.executive_summary or "")
    if not sections:
        lines.append("**Deep Research Findings**")
        lines.append((report.executive_summary or "No executive summary content was provided.").strip())
        lines.append("")
        return lines

    ordered_headings = [
        "Deep Research Findings",
        "Credentials Agent Findings",
        "Combined Report & Action Items",
    ]
    for index, heading in enumerate(ordered_headings):
        lines.append(f"**{heading}**")
        lines.append(sections.get(heading, "") or "No content provided.")
        lines.append("")
        if index < len(ordered_headings) - 1:
            lines.append("---")
            lines.append("")
    return lines


def _parse_footnote_fields(footnote: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in (footnote or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered.startswith("verbatim quote:"):
            fields["quote"] = raw.split(":", 1)[1].strip()
        elif lowered.startswith("source title:"):
            fields["title"] = raw.split(":", 1)[1].strip()
        elif lowered.startswith("canonical url:"):
            fields["url"] = raw.split(":", 1)[1].strip()
        elif lowered.startswith("evidentiary linkage:"):
            fields["linkage"] = raw.split(":", 1)[1].strip()
    return fields


def _format_structured_footnote_lines(footnote: str) -> List[str]:
    fields = _parse_footnote_fields(footnote)
    if not fields:
        compact = (footnote or "").strip()
        fields = {
            "quote": "(Not provided)",
            "title": "(Not provided)",
            "url": "(Not provided)",
            "linkage": compact or "(Not provided)",
        }
    return [
        f"Verbatim quote: {fields.get('quote') or '(Not provided)'}",
        f"Source title: {fields.get('title') or '(Not provided)'}",
        f"Canonical URL: {fields.get('url') or '(Not provided)'}",
        f"Evidentiary linkage: {fields.get('linkage') or '(Not provided)'}",
    ]


def _extract_signal_code_from_title(text: str) -> Optional[str]:
    match = re.match(r"\s*(FS\.[A-Z0-9_.]+)\s*:", (text or "").strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _build_phase_credentials_index(report: MDReport) -> Dict[str, List[CredentialMatch]]:
    index: Dict[str, List[CredentialMatch]] = {}
    seen_keys: Dict[str, set[str]] = {}
    for opp_report in report.top_opportunities or []:
        if opp_report.credentials_lookup_status != "Matched" or not opp_report.credentials:
            continue
        signal_code = _extract_signal_code_from_title(opp_report.opportunity.title)
        if not signal_code:
            continue
        bucket = index.setdefault(signal_code, [])
        seen = seen_keys.setdefault(signal_code, set())
        for credential in opp_report.credentials:
            dedupe_key = f"{(credential.url or '').strip().lower()}|{(credential.title or '').strip().lower()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            bucket.append(credential)
    return index


def _format_technologies(technologies: List[str]) -> str:
    normalized = [item.strip() for item in (technologies or []) if item and item.strip()]
    return ", ".join(normalized) if normalized else "Not provided"


def _credential_match_reason(opportunity_signal: str, credential: CredentialMatch) -> str:
    base = {
        "FS.CONSUMER.LITIGATION_SETTLEMENT": (
            "Matches remediation-governance needs around calculation controls, execution oversight, and regulator-facing evidence."
        ),
        "FS.REGULATORY.DEADLINE": (
            "Matches deadline-driven governance and documentation needs where traceability, ownership, and defensibility are critical."
        ),
        "FS.EXEC.TRANSITION": (
            "Matches risk-operating-model alignment needs during leadership transitions, including control ownership and oversight cadence."
        ),
        "FS.CECL.IMPLEMENTATION": (
            "Matches accounting and control-governance needs tied to model methodology, evidence quality, and post-change assurance."
        ),
    }.get(
        (opportunity_signal or "").upper(),
        "Matches the confirmed opportunity scope based on similar governance, risk, and control outcomes.",
    )
    if credential.industry:
        return f"{base} Industry alignment: {credential.industry}."
    return base


def _sanitize_phase_credentials_summary(summary: str) -> str:
    normalized = (summary or "").strip()
    if not normalized:
        return "No materially aligned credentials identified."
    lowered = normalized.lower()
    if "lookup failed" in lowered or lowered.startswith("failed"):
        return "No materially aligned credentials identified."
    return normalized


def _format_phase_credential_cards(
    opportunity_signal: str,
    credentials: List[CredentialMatch],
) -> List[str]:
    lines: List[str] = []
    if not credentials:
        lines.append("No materially aligned credentials identified.")
        return lines

    for index, credential in enumerate(credentials[:2], 1):
        lines.append(f"Credential {index}")
        lines.append(f"Matched credential: {credential.title or 'Not provided'}")
        lines.append(f"Client challenge: {credential.client_challenge or 'Not provided'}")
        lines.append(f"What we did: {credential.approach or 'Not provided'}")
        lines.append(f"Value provided: {credential.value_provided or 'Not provided'}")
        lines.append(f"Industry: {credential.industry or 'Not provided'}")
        lines.append(f"Technologies used: {_format_technologies(credential.technologies_used)}")
        lines.append(f"EMD: {credential.emd or 'Not provided'}")
        lines.append(f"Why this matches: {_credential_match_reason(opportunity_signal, credential)}")
        lines.append(f"URL: {credential.url or 'Not provided'}")
        if index < min(2, len(credentials)):
            lines.append("")
    return lines


def _format_phase_layout(report: MDReport, show_diagnostics: bool) -> str:
    lines: List[str] = []
    distinct_sources = _distinct_sources(report.phase_sources)
    phase_credentials = _build_phase_credentials_index(report)

    lines.extend(_format_scan_first_summary(report, distinct_source_count=len(distinct_sources)))

    lines.append("### PHASE 2 — Analytical Synthesis (Evidence-Locked)")
    lines.append("")
    if report.phase2_headline:
        lines.append(f"Governing Headline: {report.phase2_headline}")
        lines.append("")

    if report.phase2_signal_evidence:
        for evidence in report.phase2_signal_evidence:
            lines.append(f"**{evidence.signal_label} ({evidence.signal_code}) — {evidence.status}**")
            if evidence.analysis:
                lines.append(evidence.analysis)
            if evidence.evidence_quote:
                lines.append(f"Verbatim quote: \"{evidence.evidence_quote}\"")
            if evidence.source_url:
                source_title = evidence.source_title or evidence.source_url
                lines.append(f"Source title: {source_title}")
                lines.append(f"Canonical URL: {evidence.source_url}")
            lines.append("")
        lines.append("")
    else:
        lines.append("No phase-2 signal evidence was produced.")
        lines.append("")

    if report.phase2_footnotes:
        lines.append("Footnotes")
        for index, footnote in enumerate(report.phase2_footnotes, 1):
            lines.append(f"{index}.")
            lines.extend(_format_structured_footnote_lines(footnote))
            lines.append("")
        lines.append("")

    lines.append("### PHASE 3 — Opportunity Analysis & Client Enablement")
    lines.append("")
    if report.phase3_opportunities:
        for index, opportunity in enumerate(report.phase3_opportunities, 1):
            lines.append(f"#### Opportunity {index} — {opportunity.derived_from_signal}")
            lines.append("")
            if opportunity.overview:
                lines.append("**Opportunity Overview**")
                lines.append(opportunity.overview)
                lines.append("")
            if opportunity.technical_explanation:
                lines.append("**Detailed Technical Explanation**")
                lines.append(opportunity.technical_explanation)
                lines.append("")
            if opportunity.layman_explanation:
                lines.append("**Layman's Explanation**")
                lines.append(opportunity.layman_explanation)
                lines.append("")
            if opportunity.relevant_service_lines:
                lines.append("**Relevant Service Lines (mapped ONLY to this opportunity's confirmed signals)**")
                for service_line in opportunity.relevant_service_lines:
                    lines.append(f"- {service_line}")
                lines.append("")
            lines.append("**Relevant Protiviti Credentials (if applicable)**")
            resolved_credentials = phase_credentials.get((opportunity.derived_from_signal or "").upper(), [])
            if resolved_credentials:
                lines.extend(
                    _format_phase_credential_cards(
                        opportunity_signal=opportunity.derived_from_signal,
                        credentials=resolved_credentials,
                    )
                )
            else:
                lines.append(_sanitize_phase_credentials_summary(opportunity.credentials_summary))
            lines.append("")
            if opportunity.recommended_actions:
                lines.append("**Recommended Client Enablement Actions**")
                for action in opportunity.recommended_actions:
                    lines.append(f"- {action}")
                lines.append("")
            if opportunity.sources:
                lines.append("**Sources (signal-aligned)**")
                for source in opportunity.sources:
                    lines.append(f"- {source}")
                lines.append("")
            if index < len(report.phase3_opportunities):
                lines.append("---")
                lines.append("")
    else:
        lines.append("No phase-3 opportunities were generated.")
        lines.append("")

    if distinct_sources:
        lines.append(f"Sources ({len(distinct_sources)} distinct unique citations)")
        for source in distinct_sources:
            lines.append(f"- {source}")
        lines.append("")

    if show_diagnostics:
        lines.extend(_format_pipeline_diagnostics(report))
        if report.credentials_lookup_mode == "batched_single_call" and report.credentials_batch_diagnostics:
            lines.extend(_format_credentials_batch_io(report))
        lines.extend(_format_credentials_evidence(report))

    return "\n".join(lines)


def _format_credentials_evidence(report: MDReport) -> List[str]:
    """Render full credentials lookup I/O for auditability."""
    lines: List[str] = ["### Credentials Evidence (Full I/O)", ""]

    evidence_by_title = {
        evidence.opportunity_title: evidence for evidence in report.credentials_evidence
    }

    opportunities_by_title = {
        opp_report.opportunity.title: opp_report for opp_report in report.top_opportunities
    }

    ordered_titles: List[str] = []
    for opp_report in report.top_opportunities:
        title = opp_report.opportunity.title
        if title not in ordered_titles:
            ordered_titles.append(title)
    for title in evidence_by_title:
        if title not in ordered_titles:
            ordered_titles.append(title)

    if not ordered_titles:
        if report.lookups_executed_count == 0 and report.lookups_skipped_reason:
            lines.append(f"No credentials lookups were executed for this run. Reason: {report.lookups_skipped_reason}")
        elif report.lookups_executed_count == 0:
            lines.append("No credentials lookups were executed for this run.")
        else:
            lines.append("No credentials evidence records were available.")
        lines.append("")
        return lines

    for index, title in enumerate(ordered_titles, 1):
        evidence = evidence_by_title.get(title)
        opp_report = opportunities_by_title.get(title)
        credentials = opp_report.credentials if opp_report else []

        if evidence is None:
            evidence = CredentialsLookupDiagnostics(
                opportunity_title=title,
                sector="",
                query_text="",
                raw_response_text="",
                parse_outcome="evidence_missing",
                lookup_status=opp_report.credentials_lookup_status if opp_report else "Lookup Failed",
                duration_ms=0.0,
                match_count=len(credentials),
            )

        lines.append(f"**{index}. {title}**")
        lines.append(f"- Status: {evidence.lookup_status}")
        lines.append(f"- Parse Outcome: {evidence.parse_outcome or 'N/A'}")
        lines.append(f"- Duration (ms): {evidence.duration_ms:.2f}")
        lines.append(f"- Parsed Matches: {evidence.match_count}")
        if evidence.lookup_status == "Lookup Failed":
            lines.append(f"- Failure Reason: {evidence.error_message or 'Unavailable'}")

        if report.credentials_lookup_mode == "batched_single_call" and report.credentials_batch_diagnostics:
            lines.append("- Full Query Text: See **Credentials Batch I/O (Full)** section.")
            lines.append("- Full Raw Response Text: See **Credentials Batch I/O (Full)** section.")
        else:
            lines.append("- Full Query Text:")
            lines.append("```text")
            lines.append(evidence.query_text if evidence.query_text else "(empty)")
            lines.append("```")

            lines.append("- Full Raw Response Text:")
            lines.append("```text")
            lines.append(evidence.raw_response_text if evidence.raw_response_text else "(empty)")
            lines.append("```")

        lines.append("- Parsed Matches Summary:")
        if credentials:
            lines.extend(_format_credential_details(credentials))
        elif evidence.match_count > 0:
            lines.append("  - Matches were parsed but credential details were not carried into top opportunities.")
        else:
            lines.append("  - No credential matches.")
        lines.append("")

    return lines


def _format_credentials_batch_io(report: MDReport) -> List[str]:
    """Render one-time batch credentials request/response evidence."""
    lines: List[str] = ["### Credentials Batch I/O (Full)", ""]
    diagnostics: CredentialsBatchDiagnostics | None = report.credentials_batch_diagnostics
    if not diagnostics:
        lines.append("No batch credentials diagnostics were recorded for this run.")
        lines.append("")
        return lines

    lines.append(f"- Invoked: {diagnostics.invoked}")
    lines.append(f"- Lookup Count Requested: {diagnostics.lookup_count_requested}")
    lines.append(f"- Lookup Count Returned: {diagnostics.lookup_count_returned}")
    lines.append(f"- Parse Outcome: {diagnostics.parse_outcome or 'N/A'}")
    lines.append(f"- Duration (ms): {diagnostics.duration_ms:.2f}")
    if diagnostics.error_message:
        lines.append(f"- Error: {diagnostics.error_message}")

    lines.append("- Full Batch Query Text:")
    lines.append("```text")
    lines.append(diagnostics.query_text if diagnostics.query_text else "(empty)")
    lines.append("```")

    lines.append("- Full Batch Raw Response Text:")
    lines.append("```text")
    lines.append(diagnostics.raw_response_text if diagnostics.raw_response_text else "(empty)")
    lines.append("```")
    lines.append("")
    return lines


def _format_credential_details(credentials: List[CredentialMatch]) -> List[str]:
    lines: List[str] = []
    for credential in credentials:
        lines.append(f"  - Title: {credential.title}")
        lines.append(f"    - Industry: {credential.industry or 'N/A'}")
        lines.append(f"    - Client Challenge: {credential.client_challenge or 'N/A'}")
        lines.append(f"    - Approach: {credential.approach or 'N/A'}")
        lines.append(f"    - Value Provided: {credential.value_provided or 'N/A'}")
        lines.append(f"    - URL: {credential.url or 'N/A'}")
    return lines


def _format_pipeline_diagnostics(report: MDReport) -> List[str]:
    """Render deterministic pipeline diagnostics for operator visibility."""
    lines: List[str] = ["### Pipeline Diagnostics", ""]
    lines.append(f"- Synthesis Status: {report.synthesis_status}")
    if report.synthesis_fallback_reason:
        lines.append(f"- Synthesis Fallback Reason: {report.synthesis_fallback_reason}")
    if report.synthesis_error_message:
        lines.append(f"- Synthesis Error: {report.synthesis_error_message}")
    lines.append(f"- Opportunities Extracted: {report.opportunities_extracted_count}")
    lines.append(f"- Extraction Status: {report.opportunity_extraction_status}")
    if report.opportunity_extraction_reason:
        lines.append(f"- Extraction Reason: {report.opportunity_extraction_reason}")
    lines.append(f"- Lookups Executed: {report.lookups_executed_count}")
    lines.append(f"- Credentials Lookup Mode: {report.credentials_lookup_mode}")
    lines.append(f"- Opportunities Source: {report.opportunities_source}")
    lines.append(
        "- Lookup Status Counts: "
        f"Matched={report.credentials_status_counts.get('Matched', 0)}, "
        f"No Match={report.credentials_status_counts.get('No Match', 0)}"
    )
    if report.lookups_skipped_reason:
        lines.append(f"- Lookups Skipped Reason: {report.lookups_skipped_reason}")
    if report.opportunity_extraction_status == "Extraction Failed":
        lines.append(
            "- Remediation: Ensure the deep research output includes explicit opportunity sections "
            "or improve extractor patterns before rerunning credentials validation."
        )
    lines.append("")
    return lines
