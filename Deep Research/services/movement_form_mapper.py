"""
Helpers for mapping Chainlit movement-form submissions into workflow state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger
from services.bd_trigger_context import build_trigger_for_bd_enrichment


DEFAULT_MOVEMENT_INDUSTRY = "financial_services"
MOVEMENT_REQUEST_SESSION_KEY = "movement_request"
MOVEMENT_PROGRESS_SESSION_KEY = "movement_progress"
MOVEMENT_BRIEF_SESSION_KEY = "movement_brief"
MOVEMENT_ARTIFACTS_SESSION_KEY = "movement_artifacts"

MOVEMENT_REPORT_ARTIFACT_KEY = "deep_research_report"
MOVEMENT_SIGNALS_ARTIFACT_KEY = "additional_signals"
MOVEMENT_EVIDENCE_ARTIFACT_KEY = "movement_evidence"


def build_movement_form_props(
    industry_options: Optional[List[Dict[str, str]]] = None,
    *,
    company_name: str = "",
    account_id: str = "",
    person_name: str = "",
    industry_override: str = "",
    geography: str = "",
    notes: str = "",
    show_advanced: bool = False,
) -> Dict[str, Any]:
    """Build stable props for the movement intake form."""
    return {
        "title": "Build a People Movement Brief",
        "description": "Scan an account for executive and buyer movement, then enrich leverage.",
        "company_name": _normalize_text(company_name),
        "account_id": _normalize_text(account_id),
        "person_name": _normalize_text(person_name),
        "industry_override": _normalize_text(industry_override),
        "geography": _normalize_text(geography),
        "notes": _normalize_text(notes),
        "show_advanced": show_advanced,
        "industry_options": industry_options or [],
        "primary_cta_label": "Run Movement Scan",
        "secondary_cta_label": "Cancel",
        "scan_hint": "Use the company or account as the primary search anchor.",
    }


def build_movement_request_from_form_response(
    response: Dict[str, Any],
    *,
    default_industry: str = DEFAULT_MOVEMENT_INDUSTRY,
) -> Dict[str, Any]:
    """Map CustomElement response fields into a normalized movement request."""
    company_name = _normalize_text(response.get("company_name"))
    account_id = _normalize_text(response.get("account_id"))
    person_name = _normalize_text(response.get("person_name"))
    industry_override = _normalize_text(response.get("industry_override"))
    geography = _normalize_text(response.get("geography"))
    notes = _normalize_text(response.get("notes"))
    show_advanced = bool(response.get("show_advanced"))

    request = {
        "company_name": company_name,
        "account_id": account_id,
        "person_name": person_name,
        "industry_override": industry_override,
        "industry_key": industry_override or default_industry,
        "geography": geography,
        "notes": notes,
        "show_advanced": show_advanced,
    }
    request["user_query"] = build_movement_user_query(request)
    return request


def persist_movement_request_session(session: Any, request: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the movement request in a Chainlit-like session store."""
    payload = dict(request)
    session.set(MOVEMENT_REQUEST_SESSION_KEY, payload)
    return payload


def load_movement_request_session(session: Any) -> Optional[Dict[str, Any]]:
    """Load a persisted movement request from a Chainlit-like session store."""
    payload = session.get(MOVEMENT_REQUEST_SESSION_KEY)
    if not payload:
        return None
    return dict(payload)


def persist_movement_progress_session(session: Any, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Persist the latest movement progress events."""
    payload = [dict(event) for event in events]
    session.set(MOVEMENT_PROGRESS_SESSION_KEY, payload)
    return payload


def load_movement_progress_session(session: Any) -> List[Dict[str, Any]]:
    """Load persisted movement progress events."""
    payload = session.get(MOVEMENT_PROGRESS_SESSION_KEY) or []
    return [dict(event) for event in payload if isinstance(event, dict)]


def persist_movement_artifacts_session(session: Any, artifacts: Dict[str, str]) -> Dict[str, str]:
    """Persist the movement artifacts in a Chainlit-like session store."""
    payload = {str(key): str(value) for key, value in artifacts.items()}
    session.set(MOVEMENT_ARTIFACTS_SESSION_KEY, payload)
    return payload


def load_movement_artifacts_session(session: Any) -> Dict[str, str]:
    """Load persisted movement artifacts."""
    payload = session.get(MOVEMENT_ARTIFACTS_SESSION_KEY) or {}
    return {str(key): str(value) for key, value in payload.items()}


def build_movement_trigger(request: Dict[str, Any]) -> BDTrigger:
    """Build the BD trigger used by the movement workflow."""
    sector = _normalize_text(request.get("industry_key")) or DEFAULT_MOVEMENT_INDUSTRY
    user_query = build_movement_user_query(request)
    session_params = {
        "company": _primary_company_focus(request),
        "geography": _normalize_text(request.get("geography")),
        "signals": ["All relevant signals"],
    }
    return build_trigger_for_bd_enrichment(
        sector=sector,
        user_query=user_query,
        session_params=session_params,
    )


def build_movement_artifacts(result: Any) -> Dict[str, str]:
    """Format the movement run result into compact artifact payloads."""
    return {
        MOVEMENT_REPORT_ARTIFACT_KEY: _format_deep_research_report(
            getattr(result, "deep_research_markdown", "") or "",
        ),
        MOVEMENT_SIGNALS_ARTIFACT_KEY: _format_additional_signals(result),
        MOVEMENT_EVIDENCE_ARTIFACT_KEY: _format_movement_evidence(result),
    }


def build_movement_artifact_actions() -> List[Dict[str, Any]]:
    """Build the message actions used to open movement artifacts."""
    return [
        {
            "name": "transition_view_artifact",
            "label": "View Full Deep Research Report",
            "payload": {
                "artifact_key": MOVEMENT_REPORT_ARTIFACT_KEY,
                "artifact_type": "report",
            },
        },
        {
            "name": "transition_view_artifact",
            "label": "View Additional Signals",
            "payload": {
                "artifact_key": MOVEMENT_SIGNALS_ARTIFACT_KEY,
                "artifact_type": "signals",
            },
        },
        {
            "name": "transition_view_artifact",
            "label": "View Movement Evidence",
            "payload": {
                "artifact_key": MOVEMENT_EVIDENCE_ARTIFACT_KEY,
                "artifact_type": "evidence",
            },
        },
    ]


def build_movement_person_details_by_name(result: Any) -> Dict[str, Dict[str, Any]]:
    """Map deep-enriched person detail to the movement brief rows by name."""
    details: Dict[str, Dict[str, Any]] = {}
    for entry in list(getattr(result, "deep_enriched_rows", []) or []):
        if not isinstance(entry, dict):
            continue
        movement = entry.get("movement")
        person_name = _normalize_text(getattr(movement, "person_name", "") or "")
        if not person_name:
            person_name = _normalize_text(entry.get("person_name") or "")
        detail = entry.get("person_detail")
        if not person_name or not isinstance(detail, dict):
            continue
        cleaned = {str(key): value for key, value in detail.items() if _normalize_text(value)}
        if cleaned:
            details[person_name] = cleaned
    return details


def build_movement_row_action_context_by_person_name(result: Any) -> Dict[str, Dict[str, Any]]:
    """Build row-level action posture/summary for non-top movers shown in the table."""
    brief = getattr(result, "movement_brief", None)
    top_people = {
        _normalize_text(getattr(action, "person_name", "") or "")
        for action in list(getattr(brief, "where_to_act", []) or [])
        if _normalize_text(getattr(action, "person_name", "") or "")
    }

    contexts: Dict[str, Dict[str, Any]] = {}
    for entry in list(getattr(result, "ranked_rows", []) or []):
        if not isinstance(entry, dict):
            continue
        movement = entry.get("movement")
        person_name = _normalize_text(getattr(movement, "person_name", "") or "")
        if not person_name or person_name in top_people:
            continue
        action_posture = _normalize_text(entry.get("action_posture") or "") or "Monitor"
        contexts[person_name] = {
            "action_posture": action_posture,
            "action_summary": _default_row_action_summary(movement, action_posture),
        }
    return contexts


def build_movement_user_query(request: Dict[str, Any]) -> str:
    """Compose a concise user-query context for the movement workflow."""
    company_name = _normalize_text(request.get("company_name")) or "the target account"
    account_id = _normalize_text(request.get("account_id"))
    person_name = _normalize_text(request.get("person_name"))
    geography = _normalize_text(request.get("geography"))
    notes = _normalize_text(request.get("notes"))
    industry_override = _normalize_text(request.get("industry_override"))

    parts = [
        f"Run a people movement brief for {company_name}.",
        "Find all relevant financial-services signals, but bias the analysis toward executive movement and buyer movement and why they matter now.",
    ]
    if account_id:
        parts.append(f"Account ID: {account_id}.")
    if person_name:
        parts.append(f"Named person to prioritize: {person_name}.")
    if geography:
        parts.append(f"Geography: {geography}.")
    if notes:
        parts.append(f"Notes: {notes}.")
    if industry_override and industry_override != DEFAULT_MOVEMENT_INDUSTRY:
        parts.append(f"Industry override: {industry_override}.")
    return " ".join(parts).strip()


def build_movement_progress_content(request: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    """Render a factual movement progress card from stage events."""
    company_name = _normalize_text(request.get("company_name")) or _normalize_text(request.get("account_id"))
    if not company_name:
        company_name = _normalize_text(request.get("person_name")) or "Unknown account"
    industry = _format_industry_label(_normalize_text(request.get("industry_key")) or DEFAULT_MOVEMENT_INDUSTRY)

    state = _derive_progress_state(events)
    lines = [
        "**People Movement Brief In Progress**",
        "",
        f"Account: {company_name}",
        f"Industry: {industry}",
        f"Stage: {state['current_stage_label']}",
        f"Status: {state['current_status']}",
        "",
        "**Pipeline:**",
    ]

    for label, status in state["pipeline"]:
        lines.append(f"- {label}: {status}")

    research = state.get("deep_research")
    if research:
        lines.extend(
            [
                "",
                "**Deep Research polling:**",
                f"- Status: {research.get('status', 'in progress')}",
                f"- Poll: #{research.get('poll_count', 0)} | Sources found: {research.get('citation_count', 0)}",
            ]
        )
        latest_text = _normalize_text(research.get("latest_text") or research.get("message") or "")
        if latest_text:
            lines.append(f"- Latest update: {latest_text}")
        activity_log = research.get("activity_log") or []
        for item in activity_log[-5:]:
            text = _normalize_text(item)
            if text:
                lines.append(f"- {text}")

    return "\n".join(lines).strip()


def _derive_progress_state(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    pipeline = [
        ["Account signals", "pending"],
        ["Executive movement", "pending"],
        ["Buyer movement", "pending"],
        ["ProConnect matching/enrichment", "pending"],
        ["Credentials", "pending"],
        ["Brief assembly", "pending"],
    ]

    latest_stage = ""
    latest_message = ""
    deep_research_event: Optional[Dict[str, Any]] = None
    last_index = -1
    latest_status = "in_progress"

    for event in events:
        stage_key = _event_stage_key(event)
        if stage_key == "deep_research_poll":
            deep_research_event = dict(event)
            continue

        index = _stage_index(stage_key)
        if index < 0:
            continue
        last_index = max(last_index, index)
        latest_stage = stage_key
        latest_message = _normalize_text(event.get("message") or "")
        latest_status = _normalize_text(event.get("status") or "in_progress").lower() or "in_progress"

        for idx, item in enumerate(pipeline):
            if idx < index:
                item[1] = "complete"
            elif idx == index:
                item[1] = "complete" if latest_status == "complete" else "in progress"

        if stage_key == "movement_rows":
            movement_status = "complete" if latest_status == "complete" else "in progress"
            pipeline[1][1] = movement_status
            pipeline[2][1] = movement_status
        elif stage_key == "proconnect":
            pipeline[1][1] = "complete"
            pipeline[2][1] = "complete"
            pipeline[3][1] = "complete" if latest_status == "complete" else "in progress"
        elif stage_key == "credentials":
            pipeline[1][1] = "complete"
            pipeline[2][1] = "complete"
            pipeline[3][1] = "complete"
            pipeline[4][1] = "complete" if latest_status == "complete" else "in progress"
        elif stage_key == "brief_assembly":
            pipeline[1][1] = "complete"
            pipeline[2][1] = "complete"
            pipeline[3][1] = "complete"
            pipeline[4][1] = "complete"
            pipeline[5][1] = "complete" if latest_status == "complete" else "in progress"

    if last_index >= 0:
        for idx, item in enumerate(pipeline):
            if idx < last_index:
                item[1] = "complete"

    if latest_stage == "movement_rows":
        current_stage_label = "Executive movement / buyer movement"
    elif latest_stage == "proconnect":
        current_stage_label = "ProConnect matching/enrichment"
    elif latest_stage == "credentials":
        current_stage_label = "Credentials"
    elif latest_stage == "brief_assembly":
        current_stage_label = "Brief assembly"
    elif latest_stage == "account_signals":
        current_stage_label = "Account signals"
    elif deep_research_event:
        current_stage_label = "Deep Research polling"
    else:
        current_stage_label = "Initializing"

    current_status = "In progress"
    if latest_status == "complete":
        current_status = "Complete"
    elif latest_message:
        current_status = latest_message

    return {
        "pipeline": pipeline,
        "current_stage_label": current_stage_label,
        "current_status": current_status,
        "deep_research": deep_research_event,
    }


def _event_stage_key(event: Dict[str, Any]) -> str:
    stage = _normalize_text(event.get("stage") or "").lower()
    message = _normalize_text(event.get("message") or "").lower()
    if stage == "running_deep_research":
        return "deep_research_poll"
    if "signal evidence" in message or "account signals" in message:
        return "account_signals"
    if "extracting movement rows" in message:
        return "movement_rows"
    if "matching movement leverage" in message or "deep-enriching top movement rows" in message:
        return "proconnect"
    if "validating credentials" in message:
        return "credentials"
    if "assembling movement brief" in message:
        return "brief_assembly"
    if "movement rows" in stage:
        return "movement_rows"
    return stage or ""


def _stage_index(stage_key: str) -> int:
    order = {
        "account_signals": 0,
        "movement_rows": 1,
        "proconnect": 3,
        "credentials": 4,
        "brief_assembly": 5,
    }
    return order.get(stage_key, -1)


def _format_additional_signals(result: Any) -> str:
    signal_evidence = list(getattr(result, "signal_evidence", []) or [])
    diagnostics = getattr(result, "signal_diagnostics", {}) or {}

    lines = ["# Additional Signals", ""]
    if signal_evidence:
        for evidence in signal_evidence[:8]:
            label = _normalize_text(getattr(evidence, "signal_label", "") or "Signal")
            status = _normalize_text(getattr(evidence, "status", "") or "Unknown")
            quote = _normalize_text(getattr(evidence, "evidence_quote", "") or "")
            source_title = _normalize_text(getattr(evidence, "source_title", "") or "")
            source_url = _normalize_text(getattr(evidence, "source_url", "") or "")
            analysis = _normalize_text(getattr(evidence, "analysis", "") or "")

            lines.append(f"## {label}")
            lines.append(f"- Status: {status}")
            if quote:
                lines.append(f"- Evidence: {quote}")
            if source_title or source_url:
                if source_title and source_url:
                    lines.append(f"- Source: [{source_title}]({source_url})")
                else:
                    lines.append(f"- Source: {source_title or source_url}")
            if analysis:
                lines.append(f"- Analysis: {analysis}")
            lines.append("")
    else:
        lines.append("No signal evidence was retained for this run.")

    if diagnostics:
        status = _normalize_text(diagnostics.get("status") or "")
        count = diagnostics.get("signals_returned")
        parse_outcome = _normalize_text(diagnostics.get("parse_outcome") or "")
        summary_bits = []
        if status:
            summary_bits.append(f"Status: {status}")
        if count is not None:
            summary_bits.append(f"Signals returned: {count}")
        if parse_outcome:
            summary_bits.append(f"Parse outcome: {parse_outcome}")
        if summary_bits:
            lines.extend(["", "## Diagnostics", f"- {' | '.join(summary_bits)}"])

    return "\n".join(lines).strip()


def _format_movement_evidence(result: Any) -> str:
    brief = getattr(result, "movement_brief", None)
    movement_rows = list(getattr(brief, "movement_rows", []) or [])
    deep_enriched_rows = list(getattr(result, "deep_enriched_rows", []) or [])

    lines = ["# Movement Evidence", ""]
    if not movement_rows:
        lines.append("No movement rows were retained for this run.")
        return "\n".join(lines).strip()

    for index, row in enumerate(movement_rows[:6], start=1):
        source_title = _normalize_text(getattr(getattr(row, "evidence", None), "source_title", "") or "")
        source_url = _normalize_text(getattr(getattr(row, "evidence", None), "source_url", "") or "")
        quote = _normalize_text(getattr(getattr(row, "evidence", None), "evidence_quote", "") or "")
        leverage = getattr(row, "leverage", None)
        proof = getattr(row, "credentials_proof", None)
        deep_detail: Dict[str, Any] = {}
        if index - 1 < len(deep_enriched_rows):
            candidate = deep_enriched_rows[index - 1]
            if isinstance(candidate, dict):
                detail = candidate.get("person_detail")
                if isinstance(detail, dict):
                    deep_detail = detail

        lines.append(f"## {index}. {_normalize_text(getattr(row, 'person_name', '') or 'Unknown person')}")
        lines.append(f"- Account: {_normalize_text(getattr(row, 'target_company', '') or '')}")
        lines.append(f"- Role change: {_normalize_text(getattr(row, 'previous_role', '') or '')} -> {_normalize_text(getattr(row, 'new_role', '') or '')}")
        lines.append(f"- Movement type: {_normalize_text(getattr(row, 'movement_type', '') or '')} | Category: {_normalize_text(getattr(row, 'category', '') or '')}")
        if quote:
            lines.append(f"- Evidence: {quote}")
        if source_title or source_url:
            if source_title and source_url:
                lines.append(f"- Source: [{source_title}]({source_url})")
            else:
                lines.append(f"- Source: {source_title or source_url}")
        if leverage:
            leverage_bits = []
            if getattr(leverage, "known", False):
                leverage_bits.append("known relationship")
            if getattr(leverage, "worked_with", False):
                leverage_bits.append(
                    f"worked with ({getattr(leverage, 'project_count', 0)} projects, {getattr(leverage, 'win_count', 0)} wins)"
                )
            owner = _normalize_text(getattr(leverage, "relationship_owner", "") or "")
            if owner:
                leverage_bits.append(f"relationship owner {owner}")
            if leverage_bits:
                lines.append(f"- ProConnect: {'; '.join(leverage_bits)}")
        if proof:
            summary = _normalize_text(getattr(proof, "summary", "") or "")
            status = _normalize_text(getattr(proof, "lookup_status", "") or "")
            if summary or status:
                lines.append(f"- Credentials: {status or 'Unknown'}{f' - {summary}' if summary else ''}")
        if isinstance(deep_detail, dict) and deep_detail:
            detail_bits = []
            for key in ("name", "title", "location", "linkedin_url"):
                value = _normalize_text(deep_detail.get(key) or "")
                if value:
                    detail_bits.append(f"{key.replace('_', ' ').title()}: {value}")
            if detail_bits:
                lines.append(f"- ProConnect detail: {' | '.join(detail_bits)}")
        lines.append("")

    return "\n".join(lines).strip()


def _format_deep_research_report(markdown: str) -> str:
    text = (markdown or "").strip()
    return text or "No Deep Research report was captured for this run."


def _primary_company_focus(request: Dict[str, Any]) -> str:
    for key in ("company_name", "account_id", "person_name"):
        value = _normalize_text(request.get(key))
        if value:
            return value
    return ""


def _format_industry_label(industry_key: str) -> str:
    return (industry_key or DEFAULT_MOVEMENT_INDUSTRY).replace("_", " ").title()


def _default_row_action_summary(movement: Any, action_posture: str) -> str:
    new_role = _normalize_text(getattr(movement, "new_role", "") or "the new role").lower()
    category = _normalize_text(getattr(movement, "category", "") or "EXEC").upper()
    if category == "BUYER":
        return f"{action_posture}: buyer-led expansion around {new_role}."
    return f"{action_posture}: executive support around {new_role}."


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
