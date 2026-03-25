"""
Presentation helpers for transition validation/review surfaces.
"""
from __future__ import annotations

from typing import Any, Dict, List

from models.transition_schemas import TransitionBrief, TransitionPreflight
from services.transition_prompt_builder import TransitionPromptPackage


ACTION_RUN_RESEARCH = "transition_run_research"
ACTION_EDIT_PROMPT = "transition_edit_prompt"
ACTION_ADJUST_TRANSITION = "transition_adjust_transition"
ACTION_VIEW_PROMPT = "transition_view_prompt"
ACTION_VIEW_ARTIFACT = "transition_view_artifact"


def build_transition_preflight_review(
    preflight: TransitionPreflight,
    prompt_package: TransitionPromptPackage,
    *,
    run_id: str,
) -> Dict[str, Any]:
    """Build a compact review payload for the transition validation screen."""
    indicators = preflight.quick_indicators
    request = preflight.request

    content_lines: List[str] = [
        "**Transition Validation**",
        "",
        f"Person: {request.person_name}",
        f"Move: {request.from_company} -> {request.to_company}",
        f"Target role: {request.new_role}",
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

    actions = [
        {"name": ACTION_RUN_RESEARCH, "label": "Run Research", "payload": {"run_id": run_id, "mode": "transition"}},
        {"name": ACTION_EDIT_PROMPT, "label": "Edit Prompt", "payload": {"run_id": run_id, "mode": "transition"}},
        {"name": ACTION_ADJUST_TRANSITION, "label": "Adjust Transition", "payload": {"run_id": run_id, "mode": "transition"}},
    ]

    return {
        "content": "\n".join(content_lines).strip(),
        "actions": actions,
        "view_prompt_action": {
            "name": ACTION_VIEW_PROMPT,
            "label": "View Generated Prompt",
            "payload": {"run_id": run_id, "mode": "transition"},
        },
    }


def build_transition_brief_payload(brief: TransitionBrief, *, run_id: str) -> Dict[str, Any]:
    """Build message content and actions for the compact transition brief."""
    content_lines: List[str] = ["**Transition Playbook**", "", brief.transition_summary, ""]

    if brief.top_opportunities:
        content_lines.extend(["**Top opportunities:**"])
        for card in brief.top_opportunities[:3]:
            content_lines.append(f"- {card.title} ({card.confidence})")
            content_lines.append(f"  Why now: {card.why_now}")
            content_lines.append(f"  Role fit: {card.role_fit}")
        content_lines.append("")

    if brief.proof_and_warm_paths:
        content_lines.extend(["**Proof + warm paths:**"])
        for proof in brief.proof_and_warm_paths[:3]:
            sponsors = ""
            if proof.internal_sponsors:
                sponsors = f" Sponsors: {', '.join(proof.internal_sponsors[:3])}."
            content_lines.append(
                f"- {proof.opportunity_title}: {proof.credential_summary} "
                f"{proof.warm_path_summary}{sponsors}".strip()
            )
        content_lines.append("")

    if brief.recommended_actions:
        content_lines.extend(["**Recommended next actions:**"])
        for action in brief.recommended_actions[:5]:
            suffix = f" ({action.owner_hint})" if action.owner_hint else ""
            content_lines.append(f"- {action.title}{suffix}")

    actions = [
        {
            "name": ACTION_VIEW_ARTIFACT,
            "label": artifact.label,
            "payload": {
                "artifact_key": artifact.artifact_key,
                "artifact_type": artifact.artifact_type,
                "run_id": run_id,
                "mode": "transition",
            },
        }
        for artifact in brief.hidden_artifacts
    ]

    return {"content": "\n".join(content_lines).strip(), "actions": actions}


def build_transition_progress_content(
    request: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> str:
    """Render a factual transition progress card from stage events."""
    person = request.get("person_name") or "Unknown person"
    from_company = request.get("from_company") or "Unknown source"
    to_company = request.get("to_company") or "Unknown destination"
    new_role = request.get("new_role") or "Unknown role"

    latest = events[-1] if events else {}
    stage = _format_stage_label(str(latest.get("stage") or "transition"))
    status = str(latest.get("status") or "in_progress").replace("_", " ").title()

    lines = [
        "**Transition Playbook In Progress**",
        "",
        f"Person: {person}",
        f"Move: {from_company} -> {to_company}",
        f"Target role: {new_role}",
        f"Stage: {stage}",
        f"Status: {status}",
        "",
    ]

    relationship_complete = next(
        (
            event
            for event in reversed(events)
            if event.get("stage") == "building_relationship_context" and event.get("status") == "complete"
        ),
        None,
    )
    if relationship_complete:
        lines.extend(
            [
                "**Relationship signals:**",
                (
                    f"- Match: {relationship_complete.get('person_match_status', 'unknown')} | "
                    f"Warm path: {'Yes' if relationship_complete.get('warm_intro_path_available') else 'No'} | "
                    f"Source KBs: {relationship_complete.get('source_key_buyer_count', 0)} | "
                    f"Destination KBs: {relationship_complete.get('destination_key_buyer_count', 0)}"
                ),
                "",
            ]
        )

    if latest.get("stage") == "running_deep_research":
        lines.extend(
            [
                "**Research activity:**",
                (
                    f"- Sources found: {latest.get('citation_count', 0)} | "
                    f"Poll: #{latest.get('poll_count', 0)}"
                ),
            ]
        )
        for item in (latest.get("activity_log") or [])[-5:]:
            lines.append(f"- {item}")
        if latest.get("message"):
            lines.extend(["", f"Latest update: {latest['message']}"])
    else:
        recent_messages = [
            str(event.get("message") or "").strip()
            for event in events[-5:]
            if str(event.get("message") or "").strip()
        ]
        if recent_messages:
            lines.extend(["**Recent updates:**"])
            lines.extend(f"- {message}" for message in recent_messages)

    return "\n".join(lines).strip()


def _format_industry_label(industry_key: str) -> str:
    return (industry_key or "general").replace("_", " ").title()


def _format_stage_label(stage: str) -> str:
    return (stage or "transition").replace("_", " ").title()
