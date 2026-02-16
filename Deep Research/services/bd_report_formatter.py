"""
Formatting helpers for BD report rendering in Chainlit surfaces.
"""
from __future__ import annotations

from typing import Dict, Any, Optional, List

from models.bd_schemas import MDReport, CredentialMatch, MDReportOpportunity, CredentialsLookupDiagnostics


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
        lines.append("No credentials lookups were executed for this run.")
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
