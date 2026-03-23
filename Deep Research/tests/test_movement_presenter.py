"""
Tests for movement presenter payloads.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import (  # noqa: E402
    MovementAction,
    MovementBriefRequest,
    MovementBrief,
    MovementCredentialReference,
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_presenter import (  # noqa: E402
    ACTION_ADJUST_MOVEMENT,
    ACTION_EDIT_MOVEMENT_PROMPT,
    ACTION_RUN_MOVEMENT_RESEARCH,
    ACTION_VIEW_MOVEMENT_PROMPT,
    MOVEMENT_TABLE_COLUMNS,
    build_movement_brief_payload,
    build_movement_form_props,
    build_movement_preflight_review,
)
from services.movement_prompt_builder import MovementPromptPackage  # noqa: E402


def _movement(index: int, *, with_proof: bool = False) -> MovementRecord:
    leverage = MovementLeverageSummary(
        known=index % 2 == 0,
        worked_with=index % 3 == 0,
        project_count=index,
        win_count=index // 2,
        relationship_owner="Ben L." if index < 4 else None,
        person_match_status="matched" if index < 4 else "unmatched",
    )
    proof = None
    if with_proof:
        proof = MovementCredentialsProof(
            lookup_status="Matched",
            summary="Existing delivery with adjacent control team.",
            matched_credentials=[
                MovementCredentialReference(
                    title="Controls Transformation Program",
                    url="https://example.com/credential",
                )
            ],
        )

    return MovementRecord(
        person_name=f"Person {index + 1}",
        target_company="Capital One",
        previous_role=f"Previous Role {index + 1}",
        new_role=f"New Role {index + 1}",
        movement_type="Promoted" if index % 2 == 0 else "Joined",
        category="BUYER" if index % 2 == 0 else "EXEC",
        company_context="internal" if index % 2 == 0 else "inbound",
        evidence=MovementEvidence(
            evidence_quote=f"Person {index + 1} moved into a new role.",
            source_url=f"https://example.com/{index + 1}",
            source_title=f"Source {index + 1}",
            source_marker=f"S{index + 1}",
            corroborated=index < 2,
            confidence_label="High" if index < 2 else "Medium",
        ),
        leverage=leverage if index < 6 else None,
        credentials_proof=proof,
    )


def _brief(movement_rows, where_to_act, signal_summary=None):
    model_construct = getattr(MovementBrief, "model_construct", None)
    if model_construct is None:
        model_construct = MovementBrief.construct
    return model_construct(
        executive_summary="Executive Summary text.",
        signal_summary=signal_summary or [
            "Account pressure is concentrated in governance and operating model change.",
            "People movement is strongest at the target account.",
            "Buyer movement creates re-engagement scope.",
            "Executive movement creates governance scope.",
            "Trailing context that should be trimmed.",
        ],
        movement_rows=movement_rows,
        where_to_act=where_to_act,
        takeaway="Move first on the strongest movers and validate adjacent scope.",
    )


def _request() -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        lookback_days=180,
        synthetic_scenario=True,
        geography="United States",
        industry_override="financial_services",
        additional_context="POC demo scenario",
    )


def _preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
            industry_override="financial_services",
            additional_context="POC demo scenario",
        ),
        person_resolution=TransitionPersonResolution(
            requested_name="Jennifer Brady",
            match_status="matched",
            matched_name="Jennifer Brady",
            matched_title="Senior Director of Technology Risk",
            match_source="from_key_buyers",
            direct_person_evidence=True,
        ),
        from_account=AccountResolution(
            company_name="Capital One Financial Corporation",
            resolved=True,
            account_id="00130000000BYU2AAO",
        ),
        to_account=AccountResolution(
            company_name="Federal National Mortgage Association (Fannie Mae)",
            resolved=True,
            account_id="00130000000BYUIAA4",
        ),
        quick_indicators=QuickRelationshipIndicators(
            warm_intro_path_available=True,
            source_worked_before=True,
            destination_worked_before=True,
            source_key_buyer_count=24,
            destination_key_buyer_count=14,
            source_connected_colleague_count=5,
            destination_connected_colleague_count=1,
        ),
        opportunity_hypotheses=[
            OpportunityHypothesis(
                title="AI governance program",
                rationale="CIO transition increases pressure around AI oversight.",
                confidence="High",
            )
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate executive and buyer movement at Fannie Mae over the last 180 days.",
    )


def test_build_movement_form_props_trims_and_defaults():
    props = build_movement_form_props(
        industry_options=[{"value": "financial_services", "label": "Financial Services"}],
        person_name="  Jennifer Brady  ",
        from_company="  Capital One  ",
        to_company="  Fannie Mae  ",
        new_role="  Chief Information Officer  ",
        lookback_days=365,
        synthetic_scenario=False,
        industry_override="  general  ",
        geography="  United States  ",
        additional_context="  Focus on buyer movement  ",
        show_advanced=True,
    )

    assert props["title"] == "Build a People Movement Brief"
    assert props["description"].startswith("Validate the move")
    assert props["person_name"] == "Jennifer Brady"
    assert props["from_company"] == "Capital One"
    assert props["to_company"] == "Fannie Mae"
    assert props["new_role"] == "Chief Information Officer"
    assert props["lookback_days"] == 365
    assert props["synthetic_scenario"] is False
    assert props["industry_override"] == "general"
    assert props["geography"] == "United States"
    assert props["additional_context"] == "Focus on buyer movement"
    assert props["show_advanced"] is True
    assert props["industry_options"] == [{"value": "financial_services", "label": "Financial Services"}]
    assert props["primary_cta_label"] == "Generate Research Plan"
    assert props["secondary_cta_label"] == "Cancel"
    assert props["scan_hint"].startswith("Start from the named move")


def test_build_movement_preflight_review_shows_move_context_and_prompt_actions():
    payload = build_movement_preflight_review(
        _request(),
        _preflight(),
        MovementPromptPackage(
            industry_key="financial_services",
            system_prompt="FS prompt",
            user_prompt="Generated move prompt.",
        ),
    )

    assert "People Movement Brief Review" in payload["content"]
    assert "Jennifer Brady" in payload["content"]
    assert "Capital One -> Fannie Mae" in payload["content"]
    assert "180 days" in payload["content"]
    assert "Synthetic" in payload["content"]
    assert "AI governance program" in payload["content"]
    assert payload["actions"] == [
        {"name": ACTION_RUN_MOVEMENT_RESEARCH, "label": "Run Research", "payload": {}},
        {"name": ACTION_EDIT_MOVEMENT_PROMPT, "label": "Edit Prompt", "payload": {}},
        {"name": ACTION_ADJUST_MOVEMENT, "label": "Adjust Movement", "payload": {}},
    ]
    assert payload["view_prompt_action"]["name"] == ACTION_VIEW_MOVEMENT_PROMPT


def test_build_movement_brief_payload_caps_visible_rows_and_actions_and_keeps_detail_content():
    movement_rows = [_movement(index, with_proof=(index == 0)) for index in range(12)]
    where_to_act = [
        MovementAction(
            action_posture="Immediate Re-engagement",
            person_name=f"Person {index + 1}",
            likely_play=f"Likely play {index + 1}",
            why_now=f"Why now {index + 1}",
            relationship_owner="Ben L." if index == 0 else None,
        )
        for index in range(4)
    ]

    payload = build_movement_brief_payload(
        _brief(movement_rows, where_to_act),
        request=_request(),
        preflight=_preflight(),
        secondary_controls=[
            {
                "label": "View Full Deep Research Report",
                "artifact_key": "deep-research-report",
                "artifact_type": "report",
                "description": "Open the full report.",
            },
            {
                "label": "View Additional Signals",
                "artifact_key": "additional-signals",
                "artifact_type": "appendix",
                "description": "Open the signal appendix.",
            },
            {
                "label": "View ProConnect Detail",
                "artifact_key": "proconnect-detail",
                "artifact_type": "dossier",
                "description": "Open the relationship detail.",
            },
            {
                "label": "Discard me",
                "artifact_key": "",
                "artifact_type": "ignored",
                "description": "Should be dropped.",
            },
        ],
        person_details_by_name={
            "Person 1": {
                "name": "Person 1",
                "title": "Chief Risk Officer",
                "location": "New York",
                "linkedin_url": "https://linkedin.com/in/person-1",
            }
        },
        row_action_context_by_row_id={
            "movement-row-4": {
                "action_posture": "Expansion Opportunity",
                "action_summary": "Row-specific expansion play for a non-top-3 mover.",
            }
        },
        row_action_context_by_person_name={
            "Person 6": {
                "action_posture": "Monitor",
                "action_summary": "Person-keyed monitoring note.",
            }
        },
    )

    assert payload["table_columns"] == MOVEMENT_TABLE_COLUMNS
    assert len(payload["movement_rows"]) == 10
    assert len(payload["where_to_act"]) == 3
    assert payload["stats"]["visible_rows"] == 10
    assert payload["stats"]["actions"] == 3
    assert payload["stats"]["exec_rows"] == 5
    assert payload["stats"]["buyer_rows"] == 5
    assert payload["signal_summary"] == [
        "Account pressure is concentrated in governance and operating model change.",
        "People movement is strongest at the target account.",
        "Buyer movement creates re-engagement scope.",
        "Executive movement creates governance scope.",
    ]
    assert payload["move_summary"]["person_name"] == "Jennifer Brady"
    assert payload["move_summary"]["from_company"] == "Capital One Financial Corporation"
    assert payload["move_summary"]["to_company"] == "Federal National Mortgage Association (Fannie Mae)"
    assert payload["move_summary"]["new_role"] == "Chief Information Officer"
    assert payload["move_summary"]["lookback_days"] == 180
    assert payload["move_summary"]["synthetic_scenario"] is True
    assert payload["move_summary"]["warm_intro_path_available"] is True
    assert payload["move_summary"]["source_worked_before"] is True
    assert payload["move_summary"]["destination_worked_before"] is True
    assert len(payload["secondary_controls"]) == 3
    assert payload["secondary_controls"][0]["label"] == "View Full Deep Research Report"
    assert payload["movement_rows"][0]["signal"] == "BUYER"
    assert payload["movement_rows"][0]["has_credential_proof"] is True
    assert payload["movement_rows"][0]["has_person_detail"] is True
    assert payload["movement_rows"][0]["relationship_owner"] == "Ben L."
    assert payload["movement_rows"][0]["action_summary"] == "Likely play 1"
    assert payload["movement_rows"][3]["action_posture"] == "Expansion Opportunity"
    assert payload["movement_rows"][3]["action_summary"] == "Row-specific expansion play for a non-top-3 mover."
    assert payload["movement_rows"][5]["action_posture"] == "Monitor"
    assert payload["movement_rows"][5]["action_summary"] == "Person-keyed monitoring note."
    assert "movement-row-1" in payload["row_details_by_id"]

    detail = payload["row_details_by_id"]["movement-row-1"]
    assert detail["evidence_quote"] == "Person 1 moved into a new role."
    assert detail["source_url"] == "https://example.com/1"
    assert detail["source_title"] == "Source 1"
    assert detail["source_marker"] == "S1"
    assert detail["credential_summary"] == "Existing delivery with adjacent control team."
    assert detail["lookup_status"] == "Matched"
    assert detail["matched_credentials"] == [
        {
            "title": "Controls Transformation Program",
            "url": "https://example.com/credential",
        }
    ]
    assert detail["person_detail"] == {
        "name": "Person 1",
        "title": "Chief Risk Officer",
        "location": "New York",
        "linkedin_url": "https://linkedin.com/in/person-1",
    }
    assert detail["action_posture"] == "Immediate Re-engagement"
    assert detail["action_summary"] == "Likely play 1"
    assert payload["where_to_act"][0]["relationship_owner"] == "Ben L."


def test_build_movement_brief_payload_keeps_only_top_ten_rows_and_three_actions():
    movement_rows = [_movement(index) for index in range(12)]
    where_to_act = [
        MovementAction(
            action_posture="Expansion Opportunity",
            person_name=f"Person {index + 1}",
            likely_play=f"Likely play {index + 1}",
            why_now=f"Why now {index + 1}",
            relationship_owner=None,
        )
        for index in range(5)
    ]

    payload = build_movement_brief_payload(
        _brief(movement_rows, where_to_act),
        request=_request(),
        preflight=_preflight(),
    )

    assert len(payload["movement_rows"]) == 10
    assert len(payload["row_details_by_id"]) == 10
    assert len(payload["where_to_act"]) == 3
    assert payload["movement_rows"][-1]["row_id"] == "movement-row-10"
    assert payload["where_to_act"][-1]["person_name"] == "Person 3"
