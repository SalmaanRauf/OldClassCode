"""
Contract tests for movement-form mapping helpers.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import MovementAction, MovementBrief, MovementEvidence, MovementRecord  # noqa: E402
from services.movement_form_mapper import (  # noqa: E402
    MOVEMENT_EVIDENCE_ARTIFACT_KEY,
    MOVEMENT_REPORT_ARTIFACT_KEY,
    MOVEMENT_SIGNALS_ARTIFACT_KEY,
    build_movement_artifact_actions,
    build_movement_artifacts,
    build_movement_person_details_by_name,
    build_movement_progress_content,
    build_movement_request_from_form_response,
    build_movement_row_action_context_by_person_name,
    build_movement_trigger,
)
from services.signal_registry_service import get_signal_registry_service  # noqa: E402


def _movement_brief() -> MovementBrief:
    evidence = MovementEvidence(
        evidence_quote="Sarah Chen moved into a VP role.",
        source_url="https://example.com/move",
        source_title="Leadership update",
    )
    movement = MovementRecord(
        person_name="Sarah Chen",
        target_company="Capital One",
        previous_role="Director, Model Risk",
        new_role="VP, Model Risk",
        movement_type="Promoted",
        category="BUYER",
        company_context="internal",
        evidence=evidence,
    )
    action = MovementAction(
        action_posture="Immediate Re-engagement",
        person_name="Sarah Chen",
        likely_play="Model risk governance",
        why_now="Expanded authority over model risk.",
        relationship_owner="Ben L.",
    )
    return MovementBrief(
        executive_summary="Movement summary.",
        signal_summary=["Buyer and executive movement are both present."],
        movement_rows=[movement],
        where_to_act=[action],
        takeaway="Lead with the strongest mover.",
    )


def test_build_movement_request_normalizes_form_response_and_defaults_industry():
    request = build_movement_request_from_form_response(
        {
            "company_name": "  Capital One  ",
            "account_id": "  ACCT-123  ",
            "person_name": "  Sarah Chen  ",
            "industry_override": "",
            "geography": "  United States  ",
            "notes": "  buyer movement and executive movement  ",
            "show_advanced": True,
        }
    )

    assert request["company_name"] == "Capital One"
    assert request["account_id"] == "ACCT-123"
    assert request["person_name"] == "Sarah Chen"
    assert request["industry_key"] == "financial_services"
    assert request["geography"] == "United States"
    assert request["show_advanced"] is True
    assert "Capital One" in request["user_query"]
    assert "buyer movement" in request["user_query"].lower()


def test_build_movement_trigger_reuses_financial_services_signal_mapping():
    request = build_movement_request_from_form_response(
        {
            "company_name": "Capital One",
            "account_id": "",
            "person_name": "",
            "industry_override": "financial_services",
            "geography": "",
            "notes": "",
            "show_advanced": False,
        }
    )

    trigger = build_movement_trigger(request)

    assert trigger.sector == "Financial Services"
    assert trigger.company_focus == "Capital One"
    assert trigger.signals == get_signal_registry_service().get_fs_signal_codes()
    assert "people movement" in (trigger.user_prompt_context or "").lower()


def test_build_movement_artifacts_exposes_full_report_signals_and_evidence():
    result = SimpleNamespace(
        deep_research_markdown="### Deep Research\n- Found leadership change.",
        signal_evidence=[
            SimpleNamespace(
                signal_label="Executive Movement",
                status="Confirmed",
                evidence_quote="Leadership is shifting.",
                source_title="Issuer newsroom",
                source_url="https://example.com/exec",
                analysis="Executive movement supports governance reset.",
            )
        ],
        signal_diagnostics={"status": "Succeeded", "signals_returned": 1, "parse_outcome": "json_parsed"},
        movement_brief=_movement_brief(),
        deep_enriched_rows=[
            {"person_detail": {"name": "Sarah Chen", "title": "VP, Model Risk", "linkedin_url": "https://linkedin.com/in/sarah"}}
        ],
    )

    artifacts = build_movement_artifacts(result)
    actions = build_movement_artifact_actions()

    assert artifacts[MOVEMENT_REPORT_ARTIFACT_KEY].startswith("### Deep Research")
    assert "Executive Movement" in artifacts[MOVEMENT_SIGNALS_ARTIFACT_KEY]
    assert "Signals returned: 1" in artifacts[MOVEMENT_SIGNALS_ARTIFACT_KEY]
    assert "Sarah Chen" in artifacts[MOVEMENT_EVIDENCE_ARTIFACT_KEY]
    assert "ProConnect detail" in artifacts[MOVEMENT_EVIDENCE_ARTIFACT_KEY]
    assert len(actions) == 3
    assert actions[0]["payload"]["artifact_key"] == MOVEMENT_REPORT_ARTIFACT_KEY


def test_build_movement_person_details_and_row_action_context_capture_non_top_rows():
    result = SimpleNamespace(
        movement_brief=MovementBrief(
            executive_summary="Movement summary.",
            signal_summary=["Signals present."],
            movement_rows=[
                MovementRecord(
                    person_name="Sarah Chen",
                    target_company="Capital One",
                    previous_role="Director, Model Risk",
                    new_role="VP, Model Risk",
                    movement_type="Promoted",
                    category="BUYER",
                    company_context="internal",
                    evidence=MovementEvidence(
                        evidence_quote="Sarah Chen moved into a VP role.",
                        source_url="https://example.com/move",
                    ),
                ),
                MovementRecord(
                    person_name="Jane Doe",
                    target_company="Capital One",
                    previous_role="SVP, Audit",
                    new_role="Chief Audit Executive",
                    movement_type="Joined",
                    category="EXEC",
                    company_context="inbound",
                    evidence=MovementEvidence(
                        evidence_quote="Jane Doe joined as CAE.",
                        source_url="https://example.com/jane",
                    ),
                ),
            ],
            where_to_act=[
                MovementAction(
                    action_posture="Immediate Re-engagement",
                    person_name="Sarah Chen",
                    likely_play="Model risk governance",
                    why_now="Expanded authority over model risk.",
                    relationship_owner="Ben L.",
                )
            ],
            takeaway="Lead with the strongest mover.",
        ),
        deep_enriched_rows=[
            {
                "movement": MovementRecord(
                    person_name="Sarah Chen",
                    target_company="Capital One",
                    previous_role="Director, Model Risk",
                    new_role="VP, Model Risk",
                    movement_type="Promoted",
                    category="BUYER",
                    company_context="internal",
                    evidence=MovementEvidence(
                        evidence_quote="Sarah Chen moved into a VP role.",
                        source_url="https://example.com/move",
                    ),
                ),
                "person_detail": {
                    "name": "Sarah Chen",
                    "title": "VP, Model Risk",
                    "location": "McLean, VA",
                    "linkedin_url": "https://linkedin.com/in/sarah",
                },
            }
        ],
        ranked_rows=[
            {
                "movement": MovementRecord(
                    person_name="Sarah Chen",
                    target_company="Capital One",
                    previous_role="Director, Model Risk",
                    new_role="VP, Model Risk",
                    movement_type="Promoted",
                    category="BUYER",
                    company_context="internal",
                    evidence=MovementEvidence(
                        evidence_quote="Sarah Chen moved into a VP role.",
                        source_url="https://example.com/move",
                    ),
                ),
                "action_posture": "Immediate Re-engagement",
            },
            {
                "movement": MovementRecord(
                    person_name="Jane Doe",
                    target_company="Capital One",
                    previous_role="SVP, Audit",
                    new_role="Chief Audit Executive",
                    movement_type="Joined",
                    category="EXEC",
                    company_context="inbound",
                    evidence=MovementEvidence(
                        evidence_quote="Jane Doe joined as CAE.",
                        source_url="https://example.com/jane",
                    ),
                ),
                "action_posture": "Expansion Opportunity",
            },
        ],
    )

    details = build_movement_person_details_by_name(result)
    row_context = build_movement_row_action_context_by_person_name(result)

    assert details["Sarah Chen"]["title"] == "VP, Model Risk"
    assert "Sarah Chen" not in row_context
    assert row_context["Jane Doe"]["action_posture"] == "Expansion Opportunity"
    assert "executive support" in row_context["Jane Doe"]["action_summary"].lower()


def test_build_movement_progress_content_tracks_pipeline_and_deep_research_polling():
    content = build_movement_progress_content(
        {
            "company_name": "Capital One",
            "industry_key": "financial_services",
        },
        [
            {
                "stage": "running_deep_research",
                "message": "Polling Deep Research.",
                "status": "in_progress",
                "citation_count": 3,
                "poll_count": 2,
                "activity_log": [
                    "Searching issuer newsroom",
                    "Checking LinkedIn disclosures",
                ],
                "latest_text": "Found a new executive move.",
            },
            {
                "stage": "account_signals",
                "message": "Normalizing financial-services signal evidence...",
                "status": "complete",
            },
            {
                "stage": "movement_rows",
                "message": "Extracting movement rows...",
                "status": "in_progress",
            },
            {
                "stage": "proconnect",
                "message": "Matching movement leverage in ProConnect...",
                "status": "in_progress",
            },
        ],
    )

    assert "People Movement Brief In Progress" in content
    assert "Account: Capital One" in content
    assert "Account signals: complete" in content
    assert "Executive movement: complete" in content
    assert "Buyer movement: complete" in content
    assert "ProConnect matching/enrichment: in progress" in content
    assert "Deep Research polling" in content
    assert "Poll: #2" in content
