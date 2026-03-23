"""
Helpers for mapping Chainlit movement-form submissions into workflow state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger
from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionRequest
from services.bd_trigger_context import build_trigger_for_bd_enrichment
from services.element_response_utils import extract_element_response_payload


DEFAULT_MOVEMENT_INDUSTRY = "financial_services"
MOVEMENT_REQUEST_SESSION_KEY = "movement_request"
MOVEMENT_PREFLIGHT_SESSION_KEY = "movement_preflight"
MOVEMENT_PROMPT_SESSION_KEY = "movement_prompt"
MOVEMENT_PROMPT_OVERRIDE_SESSION_KEY = "movement_prompt_override"
MOVEMENT_EDIT_PENDING_SESSION_KEY = "movement_edit_pending"
MOVEMENT_PROGRESS_SESSION_KEY = "movement_progress"
MOVEMENT_BRIEF_SESSION_KEY = "movement_brief"
MOVEMENT_ARTIFACTS_SESSION_KEY = "movement_artifacts"

MOVEMENT_REPORT_ARTIFACT_KEY = "deep_research_report"
MOVEMENT_SIGNALS_ARTIFACT_KEY = "additional_signals"
MOVEMENT_EVIDENCE_ARTIFACT_KEY = "movement_evidence"


def build_movement_form_props(
    industry_options: Optional[List[Dict[str, str]]] = None,
    *,
    person_name: str = "",
    from_company: str = "",
    to_company: str = "",
    new_role: str = "",
    lookback_days: int = 180,
    synthetic_scenario: bool = True,
    industry_override: str = "",
    geography: str = "",
    additional_context: str = "",
    show_advanced: bool = False,
) -> Dict[str, Any]:
    """Build stable props for the movement intake form."""
    return {
        "title": "Build a People Movement Brief",
        "description": "Validate the move, generate a research plan, and surface broader people movement.",
        "person_name": _normalize_text(person_name),
        "from_company": _normalize_text(from_company),
        "to_company": _normalize_text(to_company),
        "new_role": _normalize_text(new_role),
        "lookback_days": max(int(lookback_days or 180), 30),
        "synthetic_scenario": bool(synthetic_scenario),
        "industry_override": _normalize_text(industry_override),
        "geography": _normalize_text(geography),
        "additional_context": _normalize_text(additional_context),
        "show_advanced": show_advanced,
        "industry_options": industry_options or [],
        "primary_cta_label": "Generate Research Plan",
        "secondary_cta_label": "Cancel",
        "scan_hint": "Start from the named move, then expand into broader executive and buyer movement.",
    }


def build_movement_request_from_form_response(
    response: Dict[str, Any],
    *,
    default_industry: str = DEFAULT_MOVEMENT_INDUSTRY,
) -> MovementBriefRequest:
    """Map CustomElement response fields into a normalized movement request."""
    payload = extract_element_response_payload(
        response,
        expected_keys=(
            "person_name",
            "from_company",
            "to_company",
            "new_role",
            "lookback_days",
            "synthetic_scenario",
            "industry_override",
            "geography",
            "additional_context",
        ),
    )
    industry_override = _normalize_text(payload.get("industry_override"))
    lookback_raw = payload.get("lookback_days")
    try:
        lookback_days = int(lookback_raw or 180)
    except (TypeError, ValueError):
        lookback_days = 180

    return MovementBriefRequest(
        person_name=_normalize_text(payload.get("person_name")),
        from_company=_normalize_text(payload.get("from_company")),
        to_company=_normalize_text(payload.get("to_company")),
        new_role=_normalize_text(payload.get("new_role")),
        lookback_days=max(30, min(365, lookback_days)),
        synthetic_scenario=bool(payload.get("synthetic_scenario", True)),
        geography=_optional_text(payload.get("geography")),
        industry_override=_optional_text(industry_override),
        additional_context=_optional_text(payload.get("additional_context")),
    )


def persist_movement_request_session(session: Any, request: MovementBriefRequest | Dict[str, Any]) -> Dict[str, Any]:
    """Persist the movement request in a Chainlit-like session store."""
    payload = _dump_request(request)
    session.set(MOVEMENT_REQUEST_SESSION_KEY, payload)
    return payload


def load_movement_request_session(session: Any) -> Optional[MovementBriefRequest]:
    """Load a persisted movement request from a Chainlit-like session store."""
    payload = session.get(MOVEMENT_REQUEST_SESSION_KEY)
    if not payload:
        return None
    if isinstance(payload, MovementBriefRequest):
        return payload
    if hasattr(MovementBriefRequest, "model_validate"):
        return MovementBriefRequest.model_validate(payload)
    return MovementBriefRequest.parse_obj(payload)


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


def build_transition_request_for_movement(request: MovementBriefRequest | Dict[str, Any]) -> TransitionRequest:
    """Convert a movement request into the transition-style request used for ProConnect preflight."""
    movement_request = _coerce_request(request)
    return TransitionRequest(
        person_name=movement_request.person_name,
        from_company=movement_request.from_company,
        to_company=movement_request.to_company,
        new_role=movement_request.new_role,
        synthetic_scenario=movement_request.synthetic_scenario,
        geography=movement_request.geography,
        industry_override=movement_request.industry_override,
        additional_context=movement_request.additional_context,
    )


def build_movement_trigger(request: MovementBriefRequest | Dict[str, Any]) -> BDTrigger:
    """Build the BD trigger used by the movement workflow."""
    movement_request = _coerce_request(request)
    sector = _normalize_text(movement_request.industry_override) or DEFAULT_MOVEMENT_INDUSTRY
    user_query = build_movement_user_query(movement_request)
    session_params = {
        "company": movement_request.to_company,
        "geography": _normalize_text(movement_request.geography),
        "signals": ["All relevant signals"],
        "time_window_days": movement_request.lookback_days,
    }
    trigger = build_trigger_for_bd_enrichment(
        sector=sector,
        user_query=user_query,
        session_params=session_params,
    )
    trigger.time_window_days = movement_request.lookback_days
    return trigger


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


def build_movement_user_query(request: MovementBriefRequest | Dict[str, Any]) -> str:
    """Compose a concise user-query context for the movement workflow."""
    movement_request = _coerce_request(request)
    parts = [
        (
            f"{movement_request.person_name} has moved from {movement_request.from_company} "
            f"to {movement_request.to_company}, with a new role as {movement_request.new_role}."
        ),
        (
            f"Source all relevant information and find executive and buyer movement within the last "
            f"{movement_request.lookback_days} days."
        ),
        "Keep the research broad across financial-services signals, but bias the analysis toward executive movement, buyer movement, and why the move matters now.",
    ]
    if movement_request.synthetic_scenario:
        parts.append("Treat this as a hypothetical planning scenario for demo purposes.")
    if movement_request.geography:
        parts.append(f"Geography: {movement_request.geography}.")
    if movement_request.additional_context:
        parts.append(f"Additional context: {movement_request.additional_context}.")
    if movement_request.industry_override and movement_request.industry_override != DEFAULT_MOVEMENT_INDUSTRY:
        parts.append(f"Industry override: {movement_request.industry_override}.")
    return " ".join(parts).strip()


def build_movement_progress_content(request: MovementBriefRequest | Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    """Render a factual movement progress card from stage events."""
    movement_request = _coerce_request(request)
    industry = _format_industry_label(_normalize_text(movement_request.industry_override) or DEFAULT_MOVEMENT_INDUSTRY)

    state = _derive_progress_state(events)
    lines = [
        "**People Movement Brief In Progress**",
        "",
        f"Person: {movement_request.person_name}",
        f"Move: {movement_request.from_company} -> {movement_request.to_company}",
        f"Target role: {movement_request.new_role}",
        f"Lookback: {movement_request.lookback_days} days",
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
        ["Move validation", "pending"],
        ["Relationship context", "pending"],
        ["Research plan", "pending"],
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
            pipeline[4][1] = movement_status
            pipeline[5][1] = movement_status
        elif stage_key == "proconnect":
            pipeline[4][1] = "complete"
            pipeline[5][1] = "complete"
            pipeline[6][1] = "complete" if latest_status == "complete" else "in progress"
        elif stage_key == "credentials":
            pipeline[4][1] = "complete"
            pipeline[5][1] = "complete"
            pipeline[6][1] = "complete"
            pipeline[7][1] = "complete" if latest_status == "complete" else "in progress"
        elif stage_key == "brief_assembly":
            pipeline[4][1] = "complete"
            pipeline[5][1] = "complete"
            pipeline[6][1] = "complete"
            pipeline[7][1] = "complete"
            pipeline[8][1] = "complete" if latest_status == "complete" else "in progress"

    if last_index >= 0:
        for idx, item in enumerate(pipeline):
            if idx < last_index:
                item[1] = "complete"

    if latest_stage == "resolving_named_move":
        current_stage_label = "Move validation"
    elif latest_stage == "building_relationship_context":
        current_stage_label = "Relationship context"
    elif latest_stage == "generating_research_plan":
        current_stage_label = "Research plan"
    elif latest_stage == "movement_rows":
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
    if "named move" in message:
        return "resolving_named_move"
    if "relationship context" in message:
        return "building_relationship_context"
    if "research plan" in message:
        return "generating_research_plan"
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
        "resolving_named_move": 0,
        "building_relationship_context": 1,
        "generating_research_plan": 2,
        "account_signals": 3,
        "movement_rows": 4,
        "proconnect": 6,
        "credentials": 7,
        "brief_assembly": 8,
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


def _optional_text(value: Any) -> Optional[str]:
    text = _normalize_text(value)
    return text or None


def _coerce_request(request: MovementBriefRequest | Dict[str, Any]) -> MovementBriefRequest:
    if isinstance(request, MovementBriefRequest):
        return request
    if isinstance(request, dict):
        if any(key in request for key in ("company_name", "account_id", "person_name")) and not all(
            key in request for key in ("from_company", "to_company", "new_role")
        ):
            company_name = _normalize_text(request.get("company_name")) or _normalize_text(request.get("account_id"))
            return MovementBriefRequest(
                person_name=_normalize_text(request.get("person_name")) or "Unknown person",
                from_company=company_name or "Unknown source",
                to_company=company_name or "Unknown destination",
                new_role=_normalize_text(request.get("new_role")) or "Unknown role",
                lookback_days=int(request.get("lookback_days") or 180),
                synthetic_scenario=bool(request.get("synthetic_scenario", True)),
                geography=_optional_text(request.get("geography")),
                industry_override=_optional_text(request.get("industry_override") or request.get("industry_key")),
                additional_context=_optional_text(request.get("additional_context") or request.get("notes")),
            )
    if hasattr(MovementBriefRequest, "model_validate"):
        return MovementBriefRequest.model_validate(request)
    return MovementBriefRequest.parse_obj(request)


def _dump_request(request: MovementBriefRequest | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(request, MovementBriefRequest):
        if hasattr(request, "model_dump"):
            return request.model_dump()
        return request.dict()
    return dict(request)
