"""
Contract tests for people movement brief schemas.
"""
import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import (  # noqa: E402
    MovementAction,
    MovementBrief,
    MovementBriefRequest,
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)


def build_evidence() -> MovementEvidence:
    return MovementEvidence(
        evidence_quote="Sarah Chen was promoted to VP, Model Risk in February 2026.",
        source_url="https://example.com/sarah-chen-promotion",
        source_title="Capital One leadership update",
    )


def test_movement_brief_request_defaults_lookback_and_synthetic_mode():
    request = MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
    )

    assert request.lookback_days == 180
    assert request.synthetic_scenario is True


def test_movement_record_accepts_exec_and_buyer_categories():
    exec_record = MovementRecord(
        person_name="Sarah Chen",
        target_company="Capital One",
        previous_role="Director, Model Risk",
        new_role="VP, Model Risk",
        movement_type="Promoted",
        category="BUYER",
        company_context="internal",
        evidence=build_evidence(),
    )
    buyer_record = MovementRecord(
        person_name="John Doe",
        target_company="Capital One",
        previous_role="Chief Risk Officer",
        new_role="Board Member",
        movement_type="Joined",
        category="EXEC",
        company_context="board_integration",
        evidence=build_evidence(),
    )

    assert exec_record.category == "BUYER"
    assert buyer_record.category == "EXEC"


def test_movement_record_rejects_invalid_category():
    with pytest.raises(ValidationError):
        MovementRecord(
            person_name="Sarah Chen",
            target_company="Capital One",
            previous_role="Director, Model Risk",
            new_role="VP, Model Risk",
            movement_type="Promoted",
            category="OTHER",
            company_context="internal",
            evidence=build_evidence(),
        )


def test_movement_evidence_requires_quote_and_url():
    with pytest.raises(ValidationError):
        MovementEvidence(
            evidence_quote="",
            source_url="https://example.com/source",
        )

    with pytest.raises(ValidationError):
        MovementEvidence(
            evidence_quote="Promotion confirmed.",
            source_url="",
        )


def test_movement_action_rejects_invalid_action_posture():
    with pytest.raises(ValidationError):
        MovementAction(
            action_posture="Investigate",
            person_name="Sarah Chen",
            likely_play="Model risk governance",
            why_now="Expanded authority over model risk",
            relationship_owner="Ben L",
        )


def test_movement_brief_caps_visible_rows_and_actions():
    rows = [
        MovementRecord(
            person_name=f"Person {index}",
            target_company="Capital One",
            previous_role="Role A",
            new_role="Role B",
            movement_type="Promoted",
            category="BUYER",
            company_context="internal",
            evidence=build_evidence(),
        )
        for index in range(11)
    ]
    actions = [
        MovementAction(
            action_posture="Immediate Re-engagement",
            person_name=f"Person {index}",
            likely_play="Model risk governance",
            why_now="Expanded scope",
            relationship_owner="Ben L",
        )
        for index in range(4)
    ]

    with pytest.raises(ValidationError):
        MovementBrief(
            executive_summary="Summary",
            signal_summary=["Pressure on controls"],
            movement_rows=rows,
            where_to_act=actions[:3],
            takeaway="Takeaway",
        )

    with pytest.raises(ValidationError):
        MovementBrief(
            executive_summary="Summary",
            signal_summary=["Pressure on controls"],
            movement_rows=rows[:10],
            where_to_act=actions,
            takeaway="Takeaway",
        )


def test_movement_record_can_carry_leverage_and_credentials_proof():
    leverage = MovementLeverageSummary(
        known=True,
        worked_with=True,
        project_count=3,
        win_count=2,
        relationship_owner="Ben L",
        person_match_status="matched",
    )
    proof = MovementCredentialsProof(
        lookup_status="Matched",
        summary="Prior model risk delivery with adjacent teams.",
        matched_credentials=[{"title": "Model Risk Remediation", "url": "https://example.com/cred"}],
    )

    record = MovementRecord(
        person_name="Sarah Chen",
        target_company="Capital One",
        previous_role="Director, Model Risk",
        new_role="VP, Model Risk",
        movement_type="Promoted",
        category="BUYER",
        company_context="internal",
        evidence=build_evidence(),
        leverage=leverage,
        credentials_proof=proof,
    )

    assert record.leverage is not None
    assert record.credentials_proof is not None
    assert record.credentials_proof.lookup_status == "Matched"
