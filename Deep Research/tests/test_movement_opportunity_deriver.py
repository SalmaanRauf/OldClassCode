"""
Tests for deterministic movement opportunity derivation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import SignalEvidence  # noqa: E402
from models.movement_schemas import MovementBriefRequest, MovementEvidence, MovementRecord  # noqa: E402
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_opportunity_deriver import MovementOpportunityDeriver  # noqa: E402


def _request() -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        lookback_days=180,
        synthetic_scenario=True,
    )


def _preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
        ),
        person_resolution=TransitionPersonResolution(
            requested_name="Jennifer Brady",
            match_status="matched",
            matched_name="Jennifer Brady",
            matched_title="Senior Director of Technology Risk",
            match_source="from_key_buyers",
            direct_person_evidence=True,
        ),
        from_account=AccountResolution(company_name="Capital One", resolved=True, account_id="001"),
        to_account=AccountResolution(company_name="Fannie Mae", resolved=True, account_id="002"),
        quick_indicators=QuickRelationshipIndicators(
            warm_intro_path_available=True,
            source_worked_before=True,
            destination_worked_before=True,
            source_key_buyer_count=12,
            destination_key_buyer_count=8,
            source_connected_colleague_count=4,
            destination_connected_colleague_count=2,
        ),
        opportunity_hypotheses=[
            OpportunityHypothesis(
                title="AI governance program",
                rationale="CIO transition increases pressure around AI oversight.",
                confidence="High",
            )
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate movement and account pressure.",
    )


def _ranked_row(index: int) -> dict:
    movement = MovementRecord(
        person_name=f"Person {index}",
        target_company="Fannie Mae",
        previous_role=f"Role {index}",
        new_role=f"New Role {index}",
        movement_type="Promoted",
        category="BUYER" if index % 2 == 0 else "EXEC",
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"Person {index} moved into a new role.",
            source_url=f"https://example.com/{index}",
        ),
    )
    return {
        "movement": movement,
        "action_posture": "Immediate Re-engagement" if index == 0 else "Expansion Opportunity",
    }


def test_deriver_creates_top_three_credentials_inputs_from_ranked_rows():
    deriver = MovementOpportunityDeriver()

    opportunities = deriver.derive(
        request=_request(),
        preflight=_preflight(),
        signal_evidence=[
            SignalEvidence(
                signal_code="FS.EXEC.TRANSITION",
                signal_label="Executive Movement",
                status="Confirmed",
                evidence_quote="Leadership is shifting.",
                source_url="https://example.com/exec",
                source_title="Exec Source",
                analysis="Executive movement supports governance reset.",
            )
        ],
        ranked_rows=[_ranked_row(index) for index in range(5)],
        max_opportunities=3,
    )

    assert len(opportunities) == 3
    assert opportunities[0].person_name == "Person 0"
    assert opportunities[0].opportunity.title.startswith("Person 0")
    assert opportunities[0].opportunity.agency == "Fannie Mae"
    assert "Warm path available: yes" in (opportunities[0].opportunity.incumbent or "")
    assert opportunities[0].source_signal_codes == ["FS.EXEC.TRANSITION"]
