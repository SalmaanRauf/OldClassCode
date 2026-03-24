"""
Presentation helpers for the people movement brief workflow.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from models.movement_schemas import MovementBriefRequest
from models.movement_schemas import (
    MovementAction,
    MovementBrief,
    MovementCredentialsProof,
    MovementLeverageSummary,
    MovementRecord,
)
from models.transition_schemas import TransitionPreflight
from services.movement_form_mapper import build_movement_form_props as _build_form_props
from services.movement_prompt_builder import MovementPromptPackage


MOVEMENT_TABLE_COLUMNS = [
    "Signal",
    "Person",
    "Previous Role",
    "New Role",
    "Movement Type",
    "Known",
    "Worked With",
    "# Projects",
    "# Wins",
    "Relationship Owner",
    "Action",
    "Details",
]

ACTION_RUN_MOVEMENT_RESEARCH = "movement_run_research"
ACTION_EDIT_MOVEMENT_PROMPT = "movement_edit_prompt"
ACTION_ADJUST_MOVEMENT = "movement_adjust_move"
ACTION_VIEW_MOVEMENT_PROMPT = "movement_view_prompt"


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
    """Build stable props for the movement scan intake form."""
    return _build_form_props(
        industry_options=industry_options,
        person_name=person_name,
        from_company=from_company,
        to_company=to_company,
        new_role=new_role,
        lookback_days=lookback_days,
        synthetic_scenario=synthetic_scenario,
        industry_override=industry_override,
        geography=geography,
        additional_context=additional_context,
        show_advanced=show_advanced,
    )


build_movement_scan_form_props = build_movement_form_props


def build_movement_preflight_review(
    request: MovementBriefRequest,
    preflight: TransitionPreflight,
    prompt_package: MovementPromptPackage,
    *,
    run_id: str,
) -> Dict[str, Any]:
    """Build the named-move review surface shown before research starts."""
    indicators = preflight.quick_indicators
    content_lines: List[str] = [
        "**People Movement Brief Review**",
        "",
        "Review the validated move context below, then click `Run Research` to start Deep Research.",
        "",
        f"Person: {request.person_name}",
        f"Move: {request.from_company} -> {request.to_company}",
        f"Target role: {request.new_role}",
        f"Lookback: {request.lookback_days} days",
        f"Scenario type: {'Synthetic' if request.synthetic_scenario else 'Live'}",
        f"Person match: {preflight.person_resolution.match_status.title()}",
        (
            "Source account: "
            f"{'Resolved' if preflight.from_account.resolved else 'Unresolved'}"
            f" ({preflight.from_account.company_name or request.from_company})"
        ),
        (
            "Destination account: "
            f"{'Resolved' if preflight.to_account.resolved else 'Unresolved'}"
            f" ({preflight.to_account.company_name or request.to_company})"
        ),
        f"Warm path available: {'Yes' if indicators.warm_intro_path_available else 'No'}",
        f"Prior work: Source {'Yes' if indicators.source_worked_before else 'No'} | Destination {'Yes' if indicators.destination_worked_before else 'No'}",
        f"Industry context: {_format_industry_label(prompt_package.industry_key)}",
    ]
    if preflight.opportunity_hypotheses:
        content_lines.extend(["", "**Top hypotheses:**"])
        for hypothesis in preflight.opportunity_hypotheses[:3]:
            content_lines.append(f"- {hypothesis.title} ({hypothesis.confidence})")

    return {
        "content": "\n".join(content_lines).strip(),
        "actions": [
            {
                "name": ACTION_RUN_MOVEMENT_RESEARCH,
                "label": "Run Research",
                "payload": {"run_id": run_id, "mode": "movement"},
            },
            {
                "name": ACTION_EDIT_MOVEMENT_PROMPT,
                "label": "Edit Prompt",
                "payload": {"run_id": run_id, "mode": "movement"},
            },
            {
                "name": ACTION_ADJUST_MOVEMENT,
                "label": "Adjust Movement",
                "payload": {"run_id": run_id, "mode": "movement"},
            },
        ],
        "view_prompt_action": {
            "name": ACTION_VIEW_MOVEMENT_PROMPT,
            "label": "View Generated Prompt",
            "payload": {"run_id": run_id, "mode": "movement"},
        },
    }


def build_movement_brief_payload(
    brief: MovementBrief,
    *,
    request: Optional[MovementBriefRequest] = None,
    preflight: Optional[TransitionPreflight] = None,
    person_details_by_name: Optional[Dict[str, Dict[str, Any]]] = None,
    row_action_context_by_row_id: Optional[Dict[str, Dict[str, Any]]] = None,
    row_action_context_by_person_name: Optional[Dict[str, Dict[str, Any]]] = None,
    title: str = "People Movement Brief",
    subtitle: str = "Executive and buyer movement with leverage, proof, and next actions.",
) -> Dict[str, Any]:
    """Build the structured payload for the movement brief custom element."""
    visible_rows = list(brief.movement_rows[:10])
    visible_actions = list(brief.where_to_act[:3])
    row_payloads: List[Dict[str, Any]] = []
    row_details_by_id: Dict[str, Dict[str, Any]] = {}
    person_details_by_name = person_details_by_name or {}
    row_action_context_by_row_id = row_action_context_by_row_id or {}
    row_action_context_by_person_name = row_action_context_by_person_name or {}

    for index, row in enumerate(visible_rows, start=1):
        row_id = f"movement-row-{index}"
        row_payload = _build_row_payload(
            row=row,
            row_id=row_id,
            actions=visible_actions,
            row_action_context_by_row_id=row_action_context_by_row_id,
            row_action_context_by_person_name=row_action_context_by_person_name,
            index=index,
        )
        row_payloads.append(row_payload)
        row_details_by_id[row_id] = _build_row_detail(
            row=row,
            row_id=row_id,
            row_payload=row_payload,
            person_details_by_name=person_details_by_name,
        )

    payload = {
        "title": title,
        "subtitle": subtitle,
        "move_summary": _build_move_summary(request, preflight, brief),
        "signal_summary": list(brief.signal_summary[:4]),
        "table_columns": MOVEMENT_TABLE_COLUMNS,
        "stats": _build_stats(visible_rows, visible_actions),
        "movement_rows": row_payloads,
        "row_details_by_id": row_details_by_id,
        "where_to_act": [_build_action_payload(action) for action in visible_actions],
        "takeaway": brief.takeaway,
        "section_order": [
            "move_summary",
            "signal_summary",
            "movement_table",
            "where_to_act",
            "takeaway",
        ],
    }
    return payload


def _build_row_payload(
    *,
    row: MovementRecord,
    row_id: str,
    actions: List[MovementAction],
    row_action_context_by_row_id: Dict[str, Dict[str, Any]],
    row_action_context_by_person_name: Dict[str, Dict[str, Any]],
    index: int,
) -> Dict[str, Any]:
    leverage = row.leverage or MovementLeverageSummary()
    credential_proof = row.credentials_proof
    action = next((item for item in actions if item.person_name == row.person_name), None)
    action_context = (
        _normalize_action_context(row_action_context_by_row_id.get(row_id))
        or _normalize_action_context(row_action_context_by_person_name.get(row.person_name))
    )
    action_posture = action_context.get("action_posture") or (action.action_posture if action else "Monitor")
    action_summary = action_context.get("action_summary") or (action.likely_play if action else "")
    signal_label = "BUYER" if row.category == "BUYER" else "EXEC"

    return {
        "row_id": row_id,
        "row_index": index,
        "signal": signal_label,
        "person_name": _normalize_text(row.person_name),
        "previous_role": _normalize_text(row.previous_role),
        "new_role": _normalize_text(row.new_role),
        "movement_type": _normalize_text(row.movement_type),
        "known": leverage.known,
        "worked_with": leverage.worked_with,
        "project_count": leverage.project_count,
        "win_count": leverage.win_count,
        "relationship_owner": _normalize_text(leverage.relationship_owner or "") or None,
        "person_match_status": _normalize_text(leverage.person_match_status or "") or None,
        "action_posture": action_posture,
        "action_summary": _normalize_text(action_summary),
        "detail_id": row_id,
        "has_credential_proof": bool(credential_proof and credential_proof.lookup_status != "No Match"),
        "has_person_detail": False,
    }


def _build_row_detail(
    *,
    row: MovementRecord,
    row_id: str,
    row_payload: Dict[str, Any],
    person_details_by_name: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    proof = row.credentials_proof
    person_detail = _clean_dict(person_details_by_name.get(row.person_name))
    matched_credentials = []
    credential_summary = ""
    lookup_status = "No Match"

    if proof:
        lookup_status = proof.lookup_status
        credential_summary = proof.summary
        matched_credentials = [
            {"title": credential.title, "url": credential.url}
            for credential in proof.matched_credentials
        ]

    if person_detail:
        row_payload["has_person_detail"] = True

    return {
        "row_id": row_id,
        "signal": row_payload["signal"],
        "evidence_quote": _normalize_text(row.evidence.evidence_quote),
        "source_url": _normalize_text(row.evidence.source_url),
        "source_title": _normalize_text(row.evidence.source_title or "") or None,
        "source_marker": _normalize_text(row.evidence.source_marker or "") or None,
        "corroborated": row.evidence.corroborated,
        "confidence_label": row.evidence.confidence_label,
        "known": row_payload["known"],
        "worked_with": row_payload["worked_with"],
        "project_count": row_payload["project_count"],
        "win_count": row_payload["win_count"],
        "relationship_owner": row_payload["relationship_owner"],
        "person_match_status": row_payload["person_match_status"],
        "credential_summary": _normalize_text(credential_summary),
        "lookup_status": lookup_status,
        "matched_credentials": matched_credentials,
        "person_detail": person_detail,
        "action_posture": row_payload["action_posture"],
        "action_summary": _normalize_text(row_payload["action_summary"]),
    }


def _build_action_payload(action: MovementAction) -> Dict[str, Any]:
    return {
        "action_posture": action.action_posture,
        "person_name": _normalize_text(action.person_name),
        "likely_play": _normalize_text(action.likely_play),
        "why_now": _normalize_text(action.why_now),
        "relationship_owner": _normalize_text(action.relationship_owner or "") or None,
    }


def _build_stats(rows: List[MovementRecord], actions: List[MovementAction]) -> Dict[str, Any]:
    exec_count = sum(1 for row in rows if row.category == "EXEC")
    buyer_count = sum(1 for row in rows if row.category == "BUYER")
    known_count = sum(1 for row in rows if row.leverage and row.leverage.known)
    worked_with_count = sum(1 for row in rows if row.leverage and row.leverage.worked_with)
    return {
        "visible_rows": len(rows),
        "exec_rows": exec_count,
        "buyer_rows": buyer_count,
        "known_rows": known_count,
        "worked_with_rows": worked_with_count,
        "actions": len(actions),
    }


def _build_move_summary(
    request: Optional[MovementBriefRequest],
    preflight: Optional[TransitionPreflight],
    brief: MovementBrief,
) -> Dict[str, Any]:
    request = request or MovementBriefRequest(
        person_name="Unknown person",
        from_company="Unknown source",
        to_company="Unknown destination",
        new_role="Unknown role",
    )
    from_company = preflight.from_account.company_name if preflight else request.from_company
    to_company = preflight.to_account.company_name if preflight else request.to_company
    indicators = preflight.quick_indicators if preflight else None
    return {
        "summary_text": brief.executive_summary,
        "person_name": _normalize_text(request.person_name),
        "from_company": _normalize_text(from_company),
        "to_company": _normalize_text(to_company),
        "new_role": _normalize_text(request.new_role),
        "lookback_days": request.lookback_days,
        "synthetic_scenario": bool(request.synthetic_scenario),
        "warm_intro_path_available": bool(indicators.warm_intro_path_available) if indicators else False,
        "source_worked_before": bool(indicators.source_worked_before) if indicators else False,
        "destination_worked_before": bool(indicators.destination_worked_before) if indicators else False,
    }


def _normalize_secondary_controls(controls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for control in controls:
        if not isinstance(control, dict):
            continue
        artifact_key = _normalize_text(control.get("artifact_key") or "")
        label = _normalize_text(control.get("label") or "")
        if not artifact_key or not label:
            continue
        normalized.append(
            {
                "label": label,
                "artifact_key": artifact_key,
                "artifact_type": _normalize_text(control.get("artifact_type") or "") or "artifact",
                "description": _normalize_text(control.get("description") or ""),
            }
        )
    return normalized


def _clean_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_action_context(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "action_posture": _normalize_text(value.get("action_posture") or ""),
        "action_summary": _normalize_text(value.get("action_summary") or ""),
    }


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _format_industry_label(industry_key: str) -> str:
    return (industry_key or "financial_services").replace("_", " ").title()
