"""
Formatting helpers for BD report rendering in Chainlit surfaces.
"""
from __future__ import annotations

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

    lines.extend(_format_pipeline_diagnostics(report))
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
        f"No Match={report.credentials_status_counts.get('No Match', 0)}, "
        f"Lookup Failed={report.credentials_status_counts.get('Lookup Failed', 0)}"
    )
    if report.lookups_skipped_reason:
        lines.append(f"- Lookups Skipped Reason: {report.lookups_skipped_reason}")
    if report.opportunity_selection_diagnostics:
        diagnostics = report.opportunity_selection_diagnostics
        lines.append("- Opportunity Selection Diagnostics:")
        lines.append(
            f"  - Policy: {diagnostics.selection_policy}; "
            f"Input={diagnostics.opportunities_input_count}; "
            f"After Filters={diagnostics.opportunities_after_hard_filters}; "
            f"Selected={diagnostics.opportunities_selected_count}"
        )
        lines.append(
            f"  - CMMC Required={diagnostics.cmmc_required}; "
            f"Window={diagnostics.time_window_days} days; "
            f"Min Value={diagnostics.min_value_usd if diagnostics.min_value_usd is not None else 'N/A'}; "
            f"Geography={diagnostics.geography or 'N/A'}"
        )
        lines.append(
            "  - Rejections: "
            + ", ".join(
                f"{reason}={count}" for reason, count in diagnostics.rejection_counts.items()
            )
        )
        lines.append(f"  - Fallback Used: {diagnostics.fallback_used}")
        if diagnostics.selected_titles:
            lines.append(f"  - Selected Titles: {', '.join(diagnostics.selected_titles)}")
    if report.opportunity_extraction_status == "Extraction Failed":
        lines.append(
            "- Remediation: Ensure the deep research output includes explicit opportunity sections "
            "or improve extractor patterns before rerunning credentials validation."
        )
    lines.append("")
    return lines
