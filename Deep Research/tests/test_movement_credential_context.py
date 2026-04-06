"""
Tests for movement credential candidate selection and context building.
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
from services.movement_credential_context import (  # noqa: E402
    MovementCredentialCandidateSelector,
    MovementCredentialContextBuilder,
)


def _request(new_role: str = "Chief Information Officer") -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role=new_role,
        lookback_days=180,
        synthetic_scenario=True,
        industry_override="financial_services",
    )


def _preflight(new_role: str = "Chief Information Officer") -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role=new_role,
            synthetic_scenario=True,
            industry_override="financial_services",
        ),
        person_resolution=TransitionPersonResolution(
            requested_name="Jennifer Brady",
            match_status="matched",
            matched_name="Jennifer Brady",
            matched_title="Senior Director of Technology Risk",
            match_source="from_key_buyers",
            match_scope="from",
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


def _ranked_row(
    person_name: str,
    *,
    new_role: str,
    match_status: str,
    rank_score: float,
    target_company: str = "Fannie Mae",
    category: str = "EXEC",
) -> dict:
    movement = MovementRecord(
        person_name=person_name,
        target_company=target_company,
        previous_role=f"Previous {person_name}",
        new_role=new_role,
        movement_type="Promoted",
        category=category,
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"{person_name} moved into a new role.",
            source_url=f"https://example.com/{person_name.lower().replace(' ', '-')}",
        ),
    )
    return {
        "movement": movement,
        "person_match_status": match_status,
        "rank_score": rank_score,
        "action_posture": "Immediate Re-engagement" if match_status == "matched" else "Monitor",
        "known": match_status == "matched",
        "worked_with": False,
        "project_count": 0,
        "win_count": 0,
        "relationship_owner": None,
    }


def test_selector_prefers_exact_matches_then_falls_back_and_dedupes():
    selector = MovementCredentialCandidateSelector()
    ranked_rows = [
        _ranked_row("Matched One", new_role="Chief Information Officer", match_status="matched", rank_score=9.0),
        _ranked_row("Matched One", new_role="Chief Information Officer", match_status="matched", rank_score=8.5),
        _ranked_row("Matched Two", new_role="General Counsel", match_status="matched", rank_score=8.0),
        _ranked_row("Fallback Three", new_role="Chief Compliance Officer", match_status="no_match", rank_score=7.0),
    ]

    selected = selector.select(
        request=_request(),
        preflight=_preflight(),
        ranked_rows=ranked_rows,
        actioning_context={},
        max_candidates=3,
    )

    assert [candidate.person_name for candidate in selected] == [
        "Matched One",
        "Matched Two",
        "Fallback Three",
    ]


def test_selector_reserves_named_mover_when_visible_and_matched():
    selector = MovementCredentialCandidateSelector()
    ranked_rows = [
        _ranked_row("Matched One", new_role="Chief Information Officer", match_status="matched", rank_score=9.0),
        _ranked_row("Fallback Two", new_role="General Counsel", match_status="no_match", rank_score=8.0),
    ]

    selected = selector.select(
        request=_request(),
        preflight=_preflight(),
        ranked_rows=ranked_rows,
        actioning_context={
            "person_profile": {
                "direct_person_evidence": True,
                "project_count": 1,
                "win_count": 1,
            }
        },
        max_candidates=3,
    )

    assert selected[0].source_type == "named_mover"
    assert selected[0].person_name == "Jennifer Brady"
    assert len(selected) == 3


def test_context_builder_generates_financial_services_cio_overlay():
    selector = MovementCredentialCandidateSelector()
    builder = MovementCredentialContextBuilder()
    candidate = selector.select(
        request=_request(),
        preflight=_preflight(),
        ranked_rows=[
            _ranked_row("Matched One", new_role="Chief Information Officer", match_status="matched", rank_score=9.0),
        ],
        actioning_context={},
        max_candidates=1,
    )[0]

    context = builder.build(
        candidate=candidate,
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
        actioning_context={
            "to_company_context": {
                "account_context": {
                    "industry": "Financial Services & Real Estate",
                    "subIndustry": "Mortgage and Consumer Lending",
                }
            }
        },
    )

    assert context.industry == "Financial Services"
    assert context.subindustry == "Mortgage and Consumer Lending"
    assert context.role_family == "technology_leadership"
    assert "technology modernization" in context.buyer_priorities
    assert any("AI governance" in item for item in context.buyer_priorities)


def test_context_builder_generates_legal_overlay_for_financial_services():
    builder = MovementCredentialContextBuilder()
    candidate = MovementCredentialCandidateSelector().select(
        request=_request("Deputy General Counsel & Deputy Corporate Secretary"),
        preflight=_preflight("Deputy General Counsel & Deputy Corporate Secretary"),
        ranked_rows=[
            _ranked_row(
                "Danielle Mccoy",
                new_role="Deputy General Counsel & Deputy Corporate Secretary",
                match_status="matched",
                rank_score=9.0,
                category="EXEC",
            )
        ],
        actioning_context={},
        max_candidates=1,
    )[0]

    context = builder.build(
        candidate=candidate,
        request=_request("Deputy General Counsel & Deputy Corporate Secretary"),
        preflight=_preflight("Deputy General Counsel & Deputy Corporate Secretary"),
        signal_evidence=[],
        actioning_context={},
    )

    assert context.role_family == "legal_corporate_secretary"
    assert "legal operations" in context.buyer_priorities
    assert any("governance" in item.lower() for item in context.likely_client_needs)
