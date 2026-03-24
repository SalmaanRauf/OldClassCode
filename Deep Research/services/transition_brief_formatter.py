"""
Compact formatting helpers for the Transition Playbook workflow.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, List

from models.bd_schemas import MDReportOpportunity
from models.transition_schemas import (
    HiddenArtifactRef,
    RecommendedAction,
    TransitionBrief,
    TransitionOpportunityCard,
    TransitionProofCard,
)
from services.deep_research_formatter import format_deep_research_response_as_markdown
if TYPE_CHECKING:
    from services.transition_playbook_orchestrator import TransitionPlaybookRunResult


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def build_transition_brief(result: "TransitionPlaybookRunResult") -> TransitionBrief:
    """Convert the full transition workflow result into a compact brief."""
    preflight = result.preflight
    report = result.bd_report
    actioning_context = result.actioning_context or {}

    proof_cards: List[TransitionProofCard] = []
    opportunity_cards: List[TransitionOpportunityCard] = []
    sponsors = _extract_internal_sponsors(actioning_context)
    warm_path_summary = _build_warm_path_summary(actioning_context, preflight)

    for opp_report in report.top_opportunities[:3]:
        opportunity_cards.append(
            TransitionOpportunityCard(
                title=opp_report.opportunity.title,
                why_now=_build_why_now(opp_report),
                role_fit=_build_role_fit(preflight.request.new_role, opp_report),
                confidence=_normalize_confidence(opp_report.opportunity.confidence),
            )
        )
        proof_cards.append(
            TransitionProofCard(
                opportunity_title=opp_report.opportunity.title,
                credential_summary=_build_credential_summary(opp_report),
                warm_path_summary=warm_path_summary,
                internal_sponsors=sponsors[:4],
            )
        )

    owner_hint = sponsors[0] if sponsors else None
    recommended_actions = [
        RecommendedAction(
            title=_truncate_sentence(action),
            owner_hint=owner_hint,
            rationale=action,
        )
        for action in (report.recommended_actions or [])[:5]
    ]

    hidden_artifacts = [
        HiddenArtifactRef(
            artifact_type="deep_research_report",
            label="View Full Research Report",
            artifact_key="deep_research_report",
        ),
        HiddenArtifactRef(
            artifact_type="proconnect_dossier",
            label="View ProConnect Dossier",
            artifact_key="proconnect_dossier",
        ),
    ]
    if _collect_source_urls(result.deep_research_response):
        hidden_artifacts.append(
            HiddenArtifactRef(
                artifact_type="evidence_sources",
                label="View Source Evidence",
                artifact_key="evidence_sources",
            )
        )

    return TransitionBrief(
        transition_summary=_build_transition_summary(result),
        top_opportunities=opportunity_cards,
        proof_and_warm_paths=proof_cards,
        recommended_actions=recommended_actions,
        hidden_artifacts=hidden_artifacts,
    )

def build_transition_artifacts(result: "TransitionPlaybookRunResult") -> Dict[str, str]:
    """Build the secondary artifact payloads shown behind buttons."""
    artifacts = {
        "deep_research_report": format_deep_research_response_as_markdown(result.deep_research_response),
        "proconnect_dossier": _format_proconnect_dossier(result),
    }
    evidence = _format_evidence_sources(result.deep_research_response)
    if evidence:
        artifacts["evidence_sources"] = evidence
    return artifacts


def _build_transition_summary(result: "TransitionPlaybookRunResult") -> str:
    request = result.preflight.request
    resolved_from_company = result.preflight.from_account.company_name or request.from_company
    resolved_to_company = result.preflight.to_account.company_name or request.to_company
    indicators = result.preflight.quick_indicators
    scenario_type = "Synthetic" if request.synthetic_scenario else "Live"
    return (
        f"{request.person_name} is modeled as a {scenario_type} transition from "
        f"{resolved_from_company} to {resolved_to_company} into the {request.new_role} role. "
        f"Person match status is {result.preflight.person_resolution.match_status}. "
        f"Warm path available: {'yes' if indicators.warm_intro_path_available else 'no'}. "
        f"Prior work exists at the source account: {'yes' if indicators.source_worked_before else 'no'}; "
        f"destination account: {'yes' if indicators.destination_worked_before else 'no'}."
    )


def _build_why_now(opp_report: MDReportOpportunity) -> str:
    scope = (opp_report.opportunity.scope or "").strip()
    if scope:
        return _truncate_text(scope, limit=140)
    if opp_report.validation_status == "Validated":
        return "This is supported by internal credentials and current destination-account context."
    return "This aligns with the current transition-driven agenda at the destination account."


def _build_role_fit(new_role: str, opp_report: MDReportOpportunity) -> str:
    role = (new_role or "target executive role").strip()
    scope = (opp_report.opportunity.scope or "").strip().lower()
    if "risk" in scope or "control" in scope:
        return f"Fits the {role} remit because it shapes enterprise technology governance and control posture."
    if "ai" in scope or "data" in scope:
        return f"Fits the {role} remit because it affects technology strategy, governance, and execution priorities."
    return f"Fits the {role} remit because it is a plausible early executive priority tied to technology leadership."


def _build_credential_summary(opp_report: MDReportOpportunity) -> str:
    if opp_report.credentials:
        titles = [match.title for match in opp_report.credentials[:2] if match.title]
        if titles:
            return "Matched credentials: " + "; ".join(titles) + "."
    if opp_report.credentials_lookup_status == "Lookup Failed":
        return "Credential lookup failed in this run."
    if opp_report.credentials_lookup_status == "No Match":
        return "No materially aligned credential found in this run."
    return "Credential validation is partial in this run."


def _build_warm_path_summary(actioning_context: Dict[str, Any], preflight) -> str:
    from_context = _as_dict(actioning_context.get("from_company_context"))
    to_context = _as_dict(actioning_context.get("to_company_context"))
    from_relationship = _as_dict(from_context.get("relationship_network"))
    to_relationship = _as_dict(to_context.get("relationship_network"))

    source_connected = _as_list(_as_dict(from_relationship.get("connected_colleagues")).get("items"))
    destination_connected = _as_list(_as_dict(to_relationship.get("connected_colleagues")).get("items"))
    destination_alumni = _as_list(_as_dict(to_relationship.get("protiviti_alumni")).get("items"))

    return (
        f"Warm intro available: {'yes' if preflight.quick_indicators.warm_intro_path_available else 'no'}. "
        f"Source connected colleagues: {len(source_connected)}. "
        f"Destination connected colleagues: {len(destination_connected)}. "
        f"Destination alumni: {len(destination_alumni)}."
    )


def _extract_internal_sponsors(actioning_context: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    seen = set()

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        key = text.lower()
        if not text or key in seen:
            return
        seen.add(key)
        names.append(text)

    for context_key in ("from_company_context", "to_company_context"):
        context = _as_dict(actioning_context.get(context_key))
        account_team = _as_dict(context.get("account_team"))
        for team_key in ("account_mdd", "account_executive", "account_pmo"):
            _add(_as_dict(account_team.get(team_key)).get("name"))

        relationship = _as_dict(context.get("relationship_network"))
        for list_key in ("connected_colleagues", "protiviti_alumni"):
            for item in _as_list(_as_dict(relationship.get(list_key)).get("items")):
                if isinstance(item, dict):
                    _add(item.get("name"))

    return names


def _format_proconnect_dossier(result: "TransitionPlaybookRunResult") -> str:
    preflight = result.preflight
    actioning = result.actioning_context or {}
    resolved_from_company = preflight.from_account.company_name or preflight.request.from_company
    resolved_to_company = preflight.to_account.company_name or preflight.request.to_company
    lines = [
        "# ProConnect Dossier",
        "",
        "## Transition Validation",
        f"- Person: {preflight.request.person_name}",
        f"- Move: {resolved_from_company} -> {resolved_to_company}",
        f"- Target role: {preflight.request.new_role}",
        f"- Person match status: {preflight.person_resolution.match_status}",
        f"- Warm path available: {'Yes' if preflight.quick_indicators.warm_intro_path_available else 'No'}",
        "",
    ]

    person_profile = _as_dict(actioning.get("person_profile"))
    if person_profile:
        matched_person = _as_dict(person_profile.get("matched_person"))
        lines.extend(
            [
                "## Person Profile",
                f"- Matched name: {matched_person.get('name') or preflight.request.person_name}",
                f"- Salesforce title: {person_profile.get('title_salesforce') or matched_person.get('title') or ''}",
                f"- External title: {person_profile.get('title_external') or ''}",
                "",
            ]
        )

    for label, key in (("Source Account", "from_company_context"), ("Destination Account", "to_company_context")):
        context = _as_dict(actioning.get(key))
        if not context:
            continue
        lines.append(f"## {label}")
        account_team = _as_dict(context.get("account_team"))
        for team_key, team_label in (
            ("account_mdd", "Account MDD"),
            ("account_executive", "Account Executive"),
            ("account_pmo", "Account PMO"),
        ):
            name = _as_dict(account_team.get(team_key)).get("name")
            if name:
                lines.append(f"- {team_label}: {name}")
        relationship = _as_dict(context.get("relationship_network"))
        for list_key, item_label in (
            ("connected_colleagues", "Connected colleagues"),
            ("protiviti_alumni", "Protiviti alumni"),
        ):
            names = _extract_names(_as_dict(relationship.get(list_key)).get("items"))
            if names:
                lines.append(f"- {item_label}: {', '.join(names)}")
        lines.append("")

    ranked = _as_list(actioning.get("ranked_opportunities_top10"))
    if ranked:
        lines.extend(["## Ranked Destination Opportunities", ""])
        for item in ranked[:5]:
            if not isinstance(item, dict):
                continue
            title = item.get("opportunity") or "Opportunity"
            stage = item.get("stage") or "Unknown stage"
            buyer = item.get("primary_key_buyer") or "Unknown buyer"
            lines.append(f"- {title} | {stage} | PKB: {buyer}")
        lines.append("")

    warnings = [str(item).strip() for item in _as_list(actioning.get("warnings")) if str(item).strip()]
    if warnings:
        lines.extend(["## Run Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    return "\n".join(lines).strip()


def _format_evidence_sources(response: Dict[str, Any]) -> str:
    urls = _collect_source_urls(response)
    if not urls:
        return ""
    lines = ["# Source Evidence", ""]
    lines.extend(f"- {url}" for url in urls)
    return "\n".join(lines)


def _collect_source_urls(response: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen = set()

    def _add(url: Any) -> None:
        text = str(url or "").strip()
        key = text.lower()
        if not text.startswith(("http://", "https://")) or key in seen:
            return
        seen.add(key)
        urls.append(text)

    for citation in _as_list(response.get("citations")):
        if isinstance(citation, dict):
            _add(citation.get("url"))

    for section in _as_list(response.get("sections")):
        if not isinstance(section, dict):
            continue
        for citation in _as_list(section.get("citations")):
            if isinstance(citation, dict):
                _add(citation.get("url"))

    return urls


def _extract_names(items: Iterable[Any]) -> List[str]:
    names: List[str] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _normalize_confidence(value: str | None) -> str:
    normalized = str(value or "Medium").strip().title()
    return normalized if normalized in {"High", "Medium", "Low"} else "Medium"


def _truncate_text(text: str, *, limit: int) -> str:
    stripped = " ".join((text or "").split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + "..."


def _truncate_sentence(text: str) -> str:
    stripped = str(text or "").strip()
    if len(stripped) <= 90:
        return stripped
    return stripped[:87].rstrip() + "..."
