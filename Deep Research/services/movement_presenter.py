"""
Presentation helpers for the people movement brief workflow.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from models.movement_schemas import MovementBriefRequest
from models.movement_schemas import (
    MovementAction,
    MovementBrief,
    MovementCredentialsProof,
    MovementLeverageSummary,
    MovementEvidence,
    MovementRecord,
)
from models.transition_schemas import TransitionPreflight
from services.movement_form_mapper import build_movement_form_props as _build_form_props
from services.movement_prompt_builder import MovementPromptPackage

logger = logging.getLogger(__name__)

MOVEMENT_TABLE_COLUMNS = [
    "Signal",
    "Person",
    "Previous Role",
    "New Role",
    "Movement Type",
    "Known",
    "Worked With",
    "# Current Projects",
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
    if preflight.person_resolution.match_diagnostics:
        content_lines.extend(["", "**Match diagnostics:**"])
        content_lines.extend(f"- {item}" for item in preflight.person_resolution.match_diagnostics[:4])
    if preflight.person_resolution.candidate_suggestions:
        content_lines.extend(["", "**Candidate suggestions:**"])
        content_lines.extend(f"- {item}" for item in preflight.person_resolution.candidate_suggestions[:3])
    if preflight.review_diagnostics:
        content_lines.extend(["", "**Review diagnostics:**"])
        content_lines.extend(f"- {item}" for item in preflight.review_diagnostics[:4])
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
    named_mover_context: Optional[Dict[str, Any]] = None,
    person_details_by_name: Optional[Dict[str, Dict[str, Any]]] = None,
    row_action_context_by_row_id: Optional[Dict[str, Dict[str, Any]]] = None,
    row_action_context_by_person_name: Optional[Dict[str, Dict[str, Any]]] = None,
    footer_actions: Optional[List[Dict[str, Any]]] = None,
    title: str = "People Movement Brief",
    subtitle: str = "Executive and buyer movement with leverage, proof, and next actions.",
) -> Dict[str, Any]:
    """Build the structured payload for the movement brief custom element."""
    visible_rows = list(brief.movement_rows or [])
    scenario_row = _build_named_mover_board_row(
        request=request,
        preflight=preflight,
        named_mover_context=named_mover_context or {},
        movement_rows=visible_rows,
    )
    if scenario_row is not None:
        visible_rows = [scenario_row, *visible_rows]
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
        if row.company_context == "scenario":
            row_details_by_id[row_id] = _build_named_mover_detail(
                row=row,
                row_id=row_id,
                row_payload=row_payload,
                preflight=preflight,
                named_mover_context=named_mover_context or {},
            )
        else:
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
        "destination_account_opportunity_context": _build_destination_account_opportunity_context(preflight),
        "table_columns": MOVEMENT_TABLE_COLUMNS,
        "stats": _build_stats(visible_rows, visible_actions),
        "movement_rows": row_payloads,
        "row_details_by_id": row_details_by_id,
        "where_to_act": [_build_action_payload(action) for action in visible_actions],
        "footer_actions": list(footer_actions or []),
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
    if row.company_context == "scenario" and not action_context and not action:
        action_posture = "Expansion Opportunity" if leverage.known or leverage.worked_with else "Monitor"
        action_summary = f"Named move scenario around {_normalize_text(row.new_role).lower()}."
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
        "is_focus_move": row.company_context == "scenario",
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
        matched_credentials = _serialize_matched_credentials(proof)

    if person_detail:
        row_payload["has_person_detail"] = True

    internal_connections = _normalize_name_list(person_detail.get("internal_connections"))
    if internal_connections:
        person_detail = {key: value for key, value in person_detail.items() if key != "internal_connections"}

    return {
        "row_id": row_id,
        "signal": row_payload["signal"],
        "evidence_quote": _normalize_text(row.evidence.evidence_quote),
        "source_url": _public_source_url(row.evidence.source_url),
        "source_title": _normalize_text(row.evidence.source_title or "") or None,
        "corroborated": row.evidence.corroborated,
        "confidence_label": row.evidence.confidence_label,
        "known": row_payload["known"],
        "worked_with": row_payload["worked_with"],
        "project_count": row_payload["project_count"],
        "win_count": row_payload["win_count"],
        "relationship_owner": row_payload["relationship_owner"],
        "person_match_status": row_payload["person_match_status"],
        "internal_connections": internal_connections,
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


def _build_destination_account_opportunity_context(
    preflight: Optional[TransitionPreflight],
) -> List[Dict[str, str]]:
    if not preflight or not getattr(preflight, "opportunity_hypotheses", None):
        return []
    context: List[Dict[str, str]] = []
    for hypothesis in list(preflight.opportunity_hypotheses)[:3]:
        title = _normalize_text(getattr(hypothesis, "title", "") or "")
        confidence = _normalize_text(getattr(hypothesis, "confidence", "") or "")
        rationale = _normalize_text(getattr(hypothesis, "rationale", "") or "")
        if not title:
            continue
        context.append(
            {
                "title": title,
                "confidence": confidence or "Medium",
                "rationale": rationale,
            }
        )
    return context


def _build_named_mover_board_row(
    *,
    request: Optional[MovementBriefRequest],
    preflight: Optional[TransitionPreflight],
    named_mover_context: Dict[str, Any],
    movement_rows: List[MovementRecord],
) -> Optional[MovementRecord]:
    if request is None or preflight is None or not request.synthetic_scenario or not named_mover_context:
        return None
    if _normalize_text(preflight.person_resolution.match_status).lower() != "matched":
        return None

    named_people = {
        _normalize_person_name(request.person_name),
        _normalize_person_name(preflight.person_resolution.matched_name or ""),
    }
    named_people.discard("")
    if any(_normalize_person_name(row.person_name) in named_people for row in movement_rows):
        return None

    person_profile = _clean_dict(named_mover_context.get("person_profile"))
    matched_person = _clean_dict(person_profile.get("matched_person"))
    from_context = _clean_dict(named_mover_context.get("from_company_context"))
    to_context = _clean_dict(named_mover_context.get("to_company_context"))
    match_scope = _normalize_text(preflight.person_resolution.match_scope or matched_person.get("company_scope")).lower()
    scope_context = from_context if match_scope == "from" else to_context if match_scope == "to" else {}
    account_team = _clean_dict(scope_context.get("account_team"))
    relationship_network = _clean_dict(scope_context.get("relationship_network"))
    connected_colleagues = _clean_list(_clean_dict(relationship_network.get("connected_colleagues")).get("items"))
    alumni = _clean_list(_clean_dict(relationship_network.get("protiviti_alumni")).get("items"))
    scope_key_buyer_match = _find_named_mover_scope_record(
        person_name=preflight.person_resolution.matched_name or request.person_name,
        scope_context=scope_context,
    )

    project_count = _max_positive_int(
        person_profile.get("project_count"),
        matched_person.get("project_count"),
        matched_person.get("projectCount"),
        len(_clean_list(person_profile.get("projects"))),
        len(_clean_list(matched_person.get("projects"))),
        _max_positive_int(
            scope_key_buyer_match.get("project_count"),
            scope_key_buyer_match.get("projectCount"),
            scope_key_buyer_match.get("numberOfProjects"),
        ),
    )
    win_count = _max_positive_int(
        person_profile.get("win_count"),
        matched_person.get("win_count"),
        matched_person.get("winCount"),
        len(_clean_list(person_profile.get("closeWonOpps"))),
        len(_clean_list(person_profile.get("closeWonOpportunities"))),
        len(_clean_list(matched_person.get("closeWonOpps"))),
        len(_clean_list(matched_person.get("closeWonOpportunities"))),
        _max_positive_int(
            scope_key_buyer_match.get("win_count"),
            scope_key_buyer_match.get("winCount"),
            scope_key_buyer_match.get("wins_5y"),
            scope_key_buyer_match.get("numberOfWins"),
        ),
        len(_clean_list(scope_key_buyer_match.get("close_won_opportunities"))),
        len(_clean_list(scope_key_buyer_match.get("closeWonOpps"))),
    )
    relationship_owner = _first_non_empty_text(
        person_profile.get("relationship_owner"),
        matched_person.get("relationship_owner"),
        matched_person.get("relationshipOwner"),
        scope_key_buyer_match.get("relationship_owner"),
        scope_key_buyer_match.get("relationshipOwner"),
        _clean_dict(account_team.get("account_executive")).get("name"),
        _clean_dict(account_team.get("account_mdd")).get("name"),
        _clean_dict(account_team.get("account_pmo")).get("name"),
    )

    scope_worked_before = (
        preflight.quick_indicators.source_worked_before
        if match_scope == "from"
        else preflight.quick_indicators.destination_worked_before
        if match_scope == "to"
        else (
            preflight.quick_indicators.source_worked_before
            or preflight.quick_indicators.destination_worked_before
        )
    )
    known = bool(
        person_profile.get("direct_person_evidence")
        or preflight.quick_indicators.warm_intro_path_available
        or project_count > 0
        or win_count > 0
        or relationship_owner
        or connected_colleagues
        or alumni
    )
    worked_with = bool(project_count > 0 or win_count > 0 or scope_worked_before)
    leverage = MovementLeverageSummary(
        known=known,
        worked_with=worked_with,
        project_count=project_count,
        win_count=win_count,
        relationship_owner=relationship_owner or None,
        person_match_status=_normalize_text(preflight.person_resolution.match_status) or None,
    )
    proof_payload = _clean_dict(named_mover_context.get("named_mover_credentials_proof"))
    proof = MovementCredentialsProof(**proof_payload) if proof_payload else None

    matched_name = _normalize_text(preflight.person_resolution.matched_name or request.person_name)
    matched_title = _normalize_text(preflight.person_resolution.matched_title or "")
    target_company = _normalize_text(preflight.to_account.company_name or request.to_company)
    logger.info(
        "Movement presenter named mover row person=%s scope=%s projects=%s wins=%s owner=%s profile_project_names=%s profile_win_names=%s scope_key_buyer=%s",
        matched_name,
        match_scope or None,
        project_count,
        win_count,
        relationship_owner or None,
        [item.get("name") for item in _clean_list(matched_person.get("projects"))[:5] if isinstance(item, dict)],
        [item.get("name") for item in _clean_list(matched_person.get("closeWonOpps"))[:5] if isinstance(item, dict)],
        _clean_dict(scope_key_buyer_match).get("name") or None,
    )
    return MovementRecord(
        person_name=matched_name,
        target_company=target_company,
        previous_role=matched_title or f"Current role at {request.from_company}",
        new_role=_normalize_text(request.new_role),
        movement_type="Named move scenario",
        category=_infer_named_mover_category(request.new_role),
        company_context="scenario",
        evidence=MovementEvidence(
            evidence_quote=(
                f"Scenario input validated against ProConnect: {matched_name} is modeled as moving "
                f"from {request.from_company} to {target_company} as {request.new_role}."
            ),
            source_url="internal://named-move-scenario",
            source_title="Scenario input + ProConnect preflight",
            source_marker="Scenario",
            corroborated=False,
            confidence_label=None,
        ),
        leverage=leverage,
        credentials_proof=proof,
    )


def _build_named_mover_detail(
    *,
    row: MovementRecord,
    row_id: str,
    row_payload: Dict[str, Any],
    preflight: Optional[TransitionPreflight],
    named_mover_context: Dict[str, Any],
) -> Dict[str, Any]:
    person_profile = _clean_dict(named_mover_context.get("person_profile"))
    matched_person = _clean_dict(person_profile.get("matched_person"))
    proof = row.credentials_proof
    person_detail = {
        "name": _normalize_text(preflight.person_resolution.matched_name if preflight else row.person_name) or row.person_name,
        "title": _first_non_empty_text(preflight.person_resolution.matched_title if preflight else "", matched_person.get("title")),
        "match_scope": _first_non_empty_text(
            preflight.person_resolution.match_scope if preflight else "",
            matched_person.get("company_scope"),
        ),
        "match_source": _normalize_text(preflight.person_resolution.match_source if preflight else ""),
        "claim_policy_note": _normalize_text(person_profile.get("claim_policy_note")),
    }
    person_detail = {key: value for key, value in person_detail.items() if value}
    scope_context = _clean_dict(named_mover_context.get("from_company_context"))
    match_scope = _normalize_text(preflight.person_resolution.match_scope if preflight else "").lower()
    if match_scope == "to":
        scope_context = _clean_dict(named_mover_context.get("to_company_context"))
    relationship_network = _clean_dict(scope_context.get("relationship_network"))
    internal_connections = _normalize_name_list(
        [
            item.get("name")
            for item in _clean_list(_clean_dict(relationship_network.get("connected_colleagues")).get("items"))
            if isinstance(item, dict)
        ]
    )

    return {
        "row_id": row_id,
        "signal": row_payload["signal"],
        "evidence_quote": _normalize_text(row.evidence.evidence_quote),
        "source_url": None,
        "source_title": _normalize_text(row.evidence.source_title or "") or None,
        "corroborated": False,
        "confidence_label": row.evidence.confidence_label,
        "known": row_payload["known"],
        "worked_with": row_payload["worked_with"],
        "project_count": row_payload["project_count"],
        "win_count": row_payload["win_count"],
        "relationship_owner": row_payload["relationship_owner"],
        "person_match_status": row_payload["person_match_status"],
        "internal_connections": internal_connections,
        "credential_summary": _normalize_text(proof.summary if proof else ""),
        "lookup_status": proof.lookup_status if proof else "",
        "matched_credentials": _serialize_matched_credentials(proof) if proof else [],
        "person_detail": person_detail,
        "action_posture": row_payload["action_posture"],
        "action_summary": _normalize_text(row_payload["action_summary"]),
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


def _serialize_matched_credentials(proof: MovementCredentialsProof) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for credential in list(proof.matched_credentials or [])[:2]:
        item = {
            "title": credential.title,
            "url": credential.url,
        }
        why_relevant = _normalize_text(getattr(credential, "why_relevant", "") or "")
        if why_relevant:
            item["why_relevant"] = why_relevant
        results.append(item)
    return results


def _find_named_mover_scope_record(*, person_name: str, scope_context: Dict[str, Any]) -> Dict[str, Any]:
    normalized_person = _normalize_person_name(person_name)
    candidate_lists = [
        _clean_list(scope_context.get("top_key_buyers")),
        _clean_list(_clean_dict(scope_context.get("key_buyers")).get("items")),
    ]
    for candidates in candidate_lists:
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if _normalize_person_name(candidate.get("name") or "") == normalized_person:
                return candidate
    return {}


def _clean_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _normalize_name_list(value: Any, *, limit: int = 3) -> List[str]:
    items = value if isinstance(value, list) else []
    normalized: List[str] = []
    for item in items:
        text = _normalize_text(item)
        if text and text not in normalized:
            normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_action_context(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "action_posture": _normalize_text(value.get("action_posture") or ""),
        "action_summary": _normalize_text(value.get("action_summary") or ""),
    }


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _public_source_url(value: str) -> Optional[str]:
    text = _normalize_text(value)
    if not text or text.startswith("internal://"):
        return None
    return text


def _normalize_person_name(value: str) -> str:
    return _normalize_text(value).lower()


def _first_non_empty_text(*values: Any) -> str:
    for value in values:
        normalized = _normalize_text(value)
        if normalized:
            return normalized
    return ""


def _first_positive_int(*values: Any) -> int:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            if value > 0:
                return value
            continue
        text = _normalize_text(value)
        if not text:
            continue
        try:
            parsed = int(float(text))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _max_positive_int(*values: Any) -> int:
    best = 0
    for value in values:
        best = max(best, _first_positive_int(value))
    return best


def _infer_named_mover_category(new_role: str) -> str:
    normalized = _normalize_text(new_role).lower()
    exec_markers = (
        "chief",
        "ceo",
        "cio",
        "cto",
        "cfo",
        "coo",
        "president",
        "general counsel",
        "board",
        "head of",
    )
    return "EXEC" if any(marker in normalized for marker in exec_markers) else "BUYER"


def _format_industry_label(industry_key: str) -> str:
    return (industry_key or "financial_services").replace("_", " ").title()
