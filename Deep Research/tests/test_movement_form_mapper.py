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
    build_movement_form_props,
    build_movement_person_details_by_name,
    build_movement_progress_content,
    build_movement_request_from_form_response,
    build_movement_row_action_context_by_person_name,
    build_movement_trigger,
    build_movement_user_query,
    build_transition_request_for_movement,
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


def test_build_movement_form_props_defaults_to_named_move_intake():
    props = build_movement_form_props(
        industry_options=[{"value": "financial_services", "label": "Financial Services"}],
        person_name=" Jennifer Brady ",
        from_company=" Capital One ",
        to_company=" Fannie Mae ",
        new_role=" Chief Information Officer ",
        lookback_days=365,
        industry_override=" general ",
        geography=" United States ",
        additional_context=" Focus on buyer movement. ",
        show_advanced=True,
    )

    assert props["title"] == "Build a People Movement Brief"
    assert props["person_name"] == "Jennifer Brady"
    assert props["from_company"] == "Capital One"
    assert props["to_company"] == "Fannie Mae"
    assert props["new_role"] == "Chief Information Officer"
    assert props["lookback_days"] == 365
    assert props["industry_override"] == "general"
    assert props["geography"] == "United States"
    assert props["additional_context"] == "Focus on buyer movement."
    assert props["show_advanced"] is True
    assert props["primary_cta_label"] == "Generate Research Plan"


def test_build_movement_request_normalizes_named_move_form_response_and_defaults_industry():
    request = build_movement_request_from_form_response(
        {
            "person_name": "  Jennifer Brady  ",
            "from_company": "  Capital One  ",
            "to_company": "  Fannie Mae  ",
            "new_role": "  Chief Information Officer  ",
            "lookback_days": "",
            "synthetic_scenario": True,
            "industry_override": "",
            "geography": "  United States  ",
            "additional_context": "  Focus on executive and buyer movement.  ",
            "show_advanced": True,
        }
    )

    assert request.person_name == "Jennifer Brady"
    assert request.from_company == "Capital One"
    assert request.to_company == "Fannie Mae"
    assert request.new_role == "Chief Information Officer"
    assert request.lookback_days == 180
    assert request.synthetic_scenario is True
    assert request.industry_override is None
    assert request.geography == "United States"
    assert request.additional_context == "Focus on executive and buyer movement."


def test_build_movement_user_query_keeps_recall_first_guidance() -> None:
    query = build_movement_user_query(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "industry_override": "financial_services",
        }
    ).lower()

    assert "roughly 15-18 total movers" in query
    assert "prefer recall over conservative pruning" in query
    assert "downstream workflow ranks movers later" in query
    assert "do not compress movers into narrative-only prose" in query
    assert "chief operating officer" in query
    assert "coo" in query
    assert "co-coo" in query
    assert "chief control office" in query


def test_build_movement_request_accepts_nested_output_payload() -> None:
    request = build_movement_request_from_form_response(
        {
            "submitted": True,
            "output": {
                "person_name": "Jennifer Brady",
                "from_company": "Capital One",
                "to_company": "Fannie Mae",
                "new_role": "Chief Information Officer",
                "lookback_days": 180,
                "synthetic_scenario": True,
            },
        }
    )

    assert request.person_name == "Jennifer Brady"
    assert request.from_company == "Capital One"
    assert request.to_company == "Fannie Mae"
    assert request.new_role == "Chief Information Officer"


def test_build_movement_request_parses_string_false_synthetic_scenario() -> None:
    request = build_movement_request_from_form_response(
        {
            "submitted": True,
            "output": {
                "person_name": "Jennifer Brady",
                "from_company": "Capital One",
                "to_company": "Fannie Mae",
                "new_role": "Chief Information Officer",
                "lookback_days": 180,
                "synthetic_scenario": "false",
            },
        }
    )

    assert request.synthetic_scenario is False


def test_build_movement_request_rejects_blank_required_fields() -> None:
    try:
        build_movement_request_from_form_response(
            {
                "submitted": True,
                "output": {
                    "person_name": "",
                    "from_company": "",
                    "to_company": "",
                    "new_role": "",
                },
            }
        )
    except Exception as exc:
        message = str(exc)
        assert "person_name" in message or "must not be blank" in message
    else:
        raise AssertionError("Expected blank required fields to fail validation")


def test_build_movement_trigger_reuses_financial_services_signal_mapping_and_lookback():
    request = build_movement_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "synthetic_scenario": True,
            "industry_override": "financial_services",
            "geography": "United States",
            "additional_context": "",
            "show_advanced": False,
        }
    )

    trigger = build_movement_trigger(request)

    assert trigger.sector == "Financial Services"
    assert trigger.company_focus == "Fannie Mae"
    assert trigger.time_window_days == 180
    assert trigger.signals == get_signal_registry_service().get_fs_signal_codes()
    assert "Jennifer Brady" not in (trigger.user_prompt_context or "")
    assert "Capital One" not in (trigger.user_prompt_context or "")
    assert "Fannie Mae" in (trigger.user_prompt_context or "")
    assert "executive movement" in (trigger.user_prompt_context or "").lower()
    assert "buyer movement" in (trigger.user_prompt_context or "").lower()
    assert "why the account matters now" in (trigger.user_prompt_context or "").lower()


def test_build_movement_progress_content_marks_review_ready_after_preflight():
    request = build_movement_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "synthetic_scenario": True,
        }
    )

    content = build_movement_progress_content(
        request,
        [
            {
                "stage": "resolving_named_move",
                "message": "Resolving named move context.",
                "status": "complete",
            },
            {
                "stage": "building_relationship_context",
                "message": "Relationship context built from ProConnect.",
                "status": "complete",
            },
            {
                "stage": "generating_research_plan",
                "message": "Generated research plan from validated move context.",
                "status": "complete",
            },
        ],
    )

    assert "**People Movement Brief Ready for Review**" in content
    assert "Stage: Review ready" in content
    assert "Status: Awaiting Run Research" in content
    assert "- Account signals: not started" in content
    assert "- Brief assembly: not started" in content


def test_build_movement_progress_content_switches_to_live_run_once_research_starts():
    request = build_movement_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "synthetic_scenario": True,
        }
    )

    content = build_movement_progress_content(
        request,
        [
            {
                "stage": "generating_research_plan",
                "message": "Generated research plan from validated move context.",
                "status": "complete",
            },
            {
                "stage": "account_signals",
                "message": "Normalizing financial-services signal evidence.",
                "status": "in_progress",
            },
        ],
    )

    assert "**People Movement Brief In Progress**" in content
    assert "Stage: Account signals" in content
    assert "Status: Normalizing financial-services signal evidence." in content
    assert "- Account signals: in progress" in content


def test_build_transition_request_for_movement_reuses_named_move_transition_shape():
    request = build_movement_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "synthetic_scenario": True,
            "industry_override": "financial_services",
            "geography": "United States",
            "additional_context": "POC demo",
            "show_advanced": True,
        }
    )

    transition_request = build_transition_request_for_movement(request)

    assert transition_request.person_name == "Jennifer Brady"
    assert transition_request.from_company == "Capital One"
    assert transition_request.to_company == "Fannie Mae"
    assert transition_request.new_role == "Chief Information Officer"
    assert transition_request.synthetic_scenario is True
    assert transition_request.geography == "United States"
    assert transition_request.industry_override == "financial_services"
    assert transition_request.additional_context == "POC demo"


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
    actions = build_movement_artifact_actions(run_id="run-123")

    assert artifacts[MOVEMENT_REPORT_ARTIFACT_KEY].startswith("### Deep Research")
    assert "Executive Movement" in artifacts[MOVEMENT_SIGNALS_ARTIFACT_KEY]
    assert "Signals returned: 1" in artifacts[MOVEMENT_SIGNALS_ARTIFACT_KEY]
    assert "Sarah Chen" in artifacts[MOVEMENT_EVIDENCE_ARTIFACT_KEY]
    assert "ProConnect detail" in artifacts[MOVEMENT_EVIDENCE_ARTIFACT_KEY]
    assert len(actions) == 3


def test_build_movement_artifact_actions_include_run_scope():
    actions = build_movement_artifact_actions(run_id="run-123")

    assert {action["payload"]["run_id"] for action in actions} == {"run-123"}
    assert {action["payload"]["mode"] for action in actions} == {"movement"}
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


def test_build_movement_progress_content_tracks_pipeline_after_deep_research_handoff():
    content = build_movement_progress_content(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "industry_override": "financial_services",
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
    assert "Person: Jennifer Brady" in content
    assert "Move: Capital One -> Fannie Mae" in content
    assert "Lookback: 180 days" in content
    assert "Account signals: complete" in content
    assert "Executive movement: complete" in content
    assert "Buyer movement: complete" in content
    assert "ProConnect matching/enrichment: in progress" in content
    assert "Deep Research polling" not in content
    assert "Poll: #2" not in content


def test_build_movement_progress_content_omits_verbose_final_report_text_from_polling():
    verbose_report = (
        "Final Report: # Federal National Mortgage Association (Fannie Mae) - Recent Risk & Regulatory Signals "
        "## 1. Executive Transitions Detailed report body with many sections and citations."
    )

    content = build_movement_progress_content(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "industry_override": "financial_services",
        },
        [
            {
                "stage": "running_deep_research",
                "message": "Polling Deep Research.",
                "status": "in_progress",
                "citation_count": 33,
                "poll_count": 31,
                "activity_log": [
                    "Searching issuer newsroom",
                    "Checking leadership update sources",
                ],
                "latest_text": verbose_report,
            }
        ],
    )

    assert "Deep Research polling" in content
    assert "Poll: #31 | Sources found: 33" in content
    assert "Searching issuer newsroom" in content
    assert "Checking leadership update sources" in content
    assert "Latest update:" not in content
    assert "Final Report:" not in content
    assert "## 1. Executive Transitions" not in content


def test_build_movement_progress_content_hides_deep_research_polling_once_downstream_stages_start():
    content = build_movement_progress_content(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "lookback_days": 180,
            "industry_override": "financial_services",
        },
        [
            {
                "stage": "running_deep_research",
                "message": "Polling Deep Research.",
                "status": "in_progress",
                "citation_count": 48,
                "poll_count": 336,
                "activity_log": ["Scanning filings", "Checking leadership pages"],
            },
            {
                "stage": "account_signals",
                "message": "Normalizing financial-services signal evidence.",
                "status": "in_progress",
            },
            {
                "stage": "executive_movement",
                "message": "Executive movement extracted.",
                "status": "complete",
            },
            {
                "stage": "assembling_brief",
                "message": "Movement brief assembled.",
                "status": "complete",
            },
        ],
    )

    assert "Stage: Brief assembly" in content
    assert "Status: Complete" in content
    assert "Deep Research polling" not in content
    assert "Poll: #336" not in content
