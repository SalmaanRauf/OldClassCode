"""
Tests for movement presenter payloads.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import (  # noqa: E402
    MovementAction,
    MovementBrief,
    MovementCredentialReference,
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)
from services.movement_presenter import (  # noqa: E402
    MOVEMENT_TABLE_COLUMNS,
    build_movement_brief_payload,
    build_movement_scan_form_props,
)


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


def test_build_movement_scan_form_props_trims_and_defaults():
    props = build_movement_scan_form_props(
        industry_options=[{"value": "financial_services", "label": "Financial Services"}],
        company_name="  Capital One  ",
        account_id="  ACCT-123  ",
        person_name="  Jennifer Brady  ",
        industry_override="  general  ",
        geography="  United States  ",
        notes="  Focus on buyer movement  ",
        show_advanced=True,
    )

    assert props["title"] == "Build a People Movement Brief"
    assert props["description"].startswith("Scan an account")
    assert props["company_name"] == "Capital One"
    assert props["account_id"] == "ACCT-123"
    assert props["person_name"] == "Jennifer Brady"
    assert props["industry_override"] == "general"
    assert props["geography"] == "United States"
    assert props["notes"] == "Focus on buyer movement"
    assert props["show_advanced"] is True
    assert props["industry_options"] == [{"value": "financial_services", "label": "Financial Services"}]
    assert props["primary_cta_label"] == "Run Movement Scan"
    assert props["secondary_cta_label"] == "Cancel"
    assert props["scan_hint"].startswith("Use the company or account")


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

    payload = build_movement_brief_payload(_brief(movement_rows, where_to_act))

    assert len(payload["movement_rows"]) == 10
    assert len(payload["row_details_by_id"]) == 10
    assert len(payload["where_to_act"]) == 3
    assert payload["movement_rows"][-1]["row_id"] == "movement-row-10"
    assert payload["where_to_act"][-1]["person_name"] == "Person 3"
