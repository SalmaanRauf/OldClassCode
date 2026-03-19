"""
Presentation helpers for the people movement brief workflow.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from models.movement_schemas import (
    MovementAction,
    MovementBrief,
    MovementCredentialsProof,
    MovementLeverageSummary,
    MovementRecord,
)


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


def build_movement_scan_form_props(
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
    """Build stable props for the movement scan intake form."""
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


def build_movement_brief_payload(
    brief: MovementBrief,
    *,
    secondary_controls: Optional[List[Dict[str, Any]]] = None,
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
        "executive_summary": brief.executive_summary,
        "signal_summary": list(brief.signal_summary[:4]),
        "table_columns": MOVEMENT_TABLE_COLUMNS,
        "stats": _build_stats(visible_rows, visible_actions),
        "movement_rows": row_payloads,
        "row_details_by_id": row_details_by_id,
        "where_to_act": [_build_action_payload(action) for action in visible_actions],
        "takeaway": brief.takeaway,
        "secondary_controls": _normalize_secondary_controls(secondary_controls or []),
        "section_order": [
            "executive_summary",
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


def _normalize_secondary_controls(controls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for control in controls[:3]:
        label = str(control.get("label") or "").strip()
        artifact_key = str(control.get("artifact_key") or "").strip()
        artifact_type = str(control.get("artifact_type") or "").strip()
        if not label or not artifact_key or not artifact_type:
            continue
        normalized.append(
            {
                "label": label,
                "artifact_key": artifact_key,
                "artifact_type": artifact_type,
                "description": str(control.get("description") or "").strip(),
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
