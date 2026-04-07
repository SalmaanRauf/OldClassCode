"""
Tests for deterministic people movement brief assembly.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import SignalEvidence  # noqa: E402
from models.movement_schemas import (  # noqa: E402
    MovementBriefRequest,
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)
from models.bd_schemas import BDTrigger  # noqa: E402
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_brief_assembler import MovementBriefAssembler  # noqa: E402


def _trigger() -> BDTrigger:
    return BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"],
        company_focus="Capital One",
        user_prompt_context="Find people movement at Capital One.",
    )


def _movement(index: int) -> MovementRecord:
    return MovementRecord(
        person_name=f"Person {index}",
        target_company="Capital One",
        previous_role=f"Role {index}",
        new_role=f"New Role {index}",
        movement_type="Promoted",
        category="BUYER" if index % 2 == 0 else "EXEC",
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"Person {index} moved into a new role.",
            source_url=f"https://example.com/{index}",
            source_title=f"Source {index}",
        ),
    )


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
        opportunity_hypotheses=[],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate movement.",
    )


def test_assemble_brief_keeps_all_ranked_rows_and_attaches_proof_packets():
    assembler = MovementBriefAssembler()
    signal_evidence = [
        SignalEvidence(
            signal_code="FS.EXEC.TRANSITION",
            signal_label="Executive Movement",
            status="Confirmed",
            evidence_quote="Leadership is shifting.",
            source_url="https://example.com/exec",
            source_title="Exec Source",
            analysis="Executive movement supports governance reset.",
        ),
        SignalEvidence(
            signal_code="FS.BUYER.MOVEMENT",
            signal_label="Buyer Movement",
            status="Confirmed",
            evidence_quote="Buyer authority expanded.",
            source_url="https://example.com/buyer",
            source_title="Buyer Source",
            analysis="Buyer movement creates re-engagement scope.",
        ),
    ]
    ranked_rows = [
        {
            "movement": _movement(index),
            "known": index < 5,
            "worked_with": index < 3,
            "project_count": index,
            "win_count": 2 if index == 0 else 0,
            "relationship_owner": "Ben L" if index < 4 else None,
            "person_match_status": "matched" if index < 5 else "no_match",
            "rank_score": 10 - index,
            "action_posture": "Immediate Re-engagement" if index == 0 else "Expansion Opportunity",
        }
        for index in range(12)
    ]
    deep_enriched_rows = ranked_rows[:10]
    credential_packets = {
        "Person 0": MovementCredentialsProof(
            lookup_status="Matched",
            summary="Existing delivery with adjacent team.",
            matched_credentials=[],
        ),
        "Person 1": MovementCredentialsProof(
            lookup_status="No Match",
            summary="No internal proof found.",
            matched_credentials=[],
        ),
    }

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary="Capital One is under governance pressure and people movement is active.",
        signal_evidence=signal_evidence,
        ranked_rows=ranked_rows,
        deep_enriched_rows=deep_enriched_rows,
        credential_packets=credential_packets,
        derived_opportunities=[object(), object()],
    )

    assert "planning scenario" in brief.executive_summary.lower()
    assert "Jennifer Brady is moving from Capital One to Fannie Mae as Chief Information Officer" in brief.executive_summary
    assert len(brief.signal_summary) == 2
    assert len(brief.movement_rows) == 12
    assert len(brief.where_to_act) == 3
    assert brief.where_to_act[0].person_name == "Person 0"
    assert brief.where_to_act[0].action_posture == "Immediate Re-engagement"
    assert "0 current projects, 2 wins" in brief.where_to_act[0].likely_play
    assert brief.where_to_act[0].relationship_owner == "Ben L"
    assert "Relationship owner: Ben L." in brief.where_to_act[0].why_now
    assert "Leverage: known in ProConnect, delivery history." in brief.where_to_act[0].why_now
    assert "Credential proof: Existing delivery with adjacent team." in brief.where_to_act[0].why_now
    assert brief.movement_rows[0].leverage is not None
    assert brief.movement_rows[0].credentials_proof is not None
    assert brief.movement_rows[0].credentials_proof.lookup_status == "Matched"
    assert "matched credentials for 1 of 2 prioritized plays" in brief.executive_summary.lower()


def test_assemble_brief_uses_fallback_actions_when_rows_are_sparse():
    assembler = MovementBriefAssembler()

    brief = assembler.assemble(
        trigger=_trigger(),
        deep_research_summary="Capital One is under governance pressure.",
        signal_evidence=[],
        ranked_rows=[],
        deep_enriched_rows=[],
        credential_packets={},
    )

    assert len(brief.where_to_act) == 3
    assert all(action.person_name == "Capital One" for action in brief.where_to_act)
    assert "No confirmed signals" in brief.signal_summary[0]
    assert "degraded" in brief.executive_summary.lower()


def test_assemble_brief_uses_credential_proof_to_raise_action_priority():
    assembler = MovementBriefAssembler()

    ranked_rows = [
        {
            "movement": _movement(0),
            "known": False,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
            "person_match_status": "matched",
            "rank_score": 20,
            "action_posture": "Expansion Opportunity",
            "opportunity_id": "opp_without_proof",
        },
        {
            "movement": _movement(1),
            "known": False,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
            "person_match_status": "matched",
            "rank_score": 10,
            "action_posture": "Immediate Re-engagement",
            "opportunity_id": "opp_with_proof",
        },
    ]

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary="Capital One is under governance pressure.",
        signal_evidence=[],
        ranked_rows=ranked_rows,
        deep_enriched_rows=[],
        credential_packets={
            "opp_with_proof": MovementCredentialsProof(
                lookup_status="Matched",
                summary="Matched credentials: AI Governance Transformation.",
                matched_credentials=[],
            )
        },
    )

    assert brief.where_to_act[0].person_name == "Person 1"
    assert "Credential proof: Matched credentials: AI Governance Transformation." in brief.where_to_act[0].why_now


def test_assemble_brief_describes_known_person_without_implying_relationship_history():
    assembler = MovementBriefAssembler()

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary="Capital One is under governance pressure.",
        signal_evidence=[],
        ranked_rows=[
            {
                "movement": _movement(0),
                "known": True,
                "worked_with": False,
                "project_count": 0,
                "win_count": 0,
                "relationship_owner": None,
                "person_match_status": "matched",
                "rank_score": 10,
                "action_posture": "Expansion Opportunity",
            }
        ],
        deep_enriched_rows=[],
        credential_packets={},
        derived_opportunities=[],
    )

    assert "known in proconnect" in brief.where_to_act[0].why_now.lower()
    assert "known relationship" not in brief.where_to_act[0].why_now.lower()


def test_assemble_brief_keeps_cover_summary_compact_when_deep_research_summary_is_verbose_report():
    assembler = MovementBriefAssembler()

    verbose_report = (
        "Final Report: # Federal National Mortgage Association (Fannie Mae) - Recent Risk & Regulatory Signals "
        "Fannie Mae has undergone significant leadership changes and faces an evolving regulatory landscape over the past several months. "
        "## 1. Executive Transitions "
        "Detailed discussion follows with multiple sections, citations, and source blocks. "
        "Sources: 1. Example Source 2. Another Source"
    )

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary=verbose_report,
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
        ranked_rows=[
            {
                "movement": _movement(0),
                "known": False,
                "worked_with": False,
                "project_count": 0,
                "win_count": 0,
                "relationship_owner": None,
                "person_match_status": "matched",
                "rank_score": 10,
                "action_posture": "Expansion Opportunity",
            }
        ],
        deep_enriched_rows=[],
        credential_packets={},
        derived_opportunities=[],
    )

    assert "Final Report:" not in brief.executive_summary
    assert "## 1. Executive Transitions" not in brief.executive_summary
    assert all("Final Report:" not in item for item in brief.signal_summary)
    assert all("Sources:" not in item for item in brief.signal_summary)
    assert brief.signal_summary[0] == "Confirmed signals: Executive Movement."


def test_assemble_brief_dedupes_same_person_across_visible_rows_and_actions():
    assembler = MovementBriefAssembler()

    ranked_rows = [
        {
            "movement": _movement(0).model_copy(
                update={
                    "person_name": "Danielle M. McCoy",
                    "previous_role": "SVP & General Counsel",
                    "new_role": "Departed",
                    "movement_type": "Departure",
                    "target_company": "Fannie Mae",
                }
            ),
            "known": True,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
            "person_match_status": "matched",
            "rank_score": 90,
            "action_posture": "Expansion Opportunity",
        },
        {
            "movement": _movement(1).model_copy(
                update={
                    "person_name": "Danielle M. McCoy",
                    "previous_role": "Senior Vice President & General Counsel",
                    "new_role": "N/A (Departed)",
                    "movement_type": "Departure",
                    "target_company": "Federal National Mortgage Association",
                }
            ),
            "known": True,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
            "person_match_status": "matched",
            "rank_score": 80,
            "action_posture": "Expansion Opportunity",
        },
        {
            "movement": _movement(2).model_copy(
                update={
                    "person_name": "Jason Dandridge",
                    "previous_role": "SVP",
                    "new_role": "Chief Control Officer & Head of Enterprise Operations",
                    "movement_type": "Promotion & Role Expansion",
                    "target_company": "Fannie Mae",
                }
            ),
            "known": True,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
            "person_match_status": "matched",
            "rank_score": 70,
            "action_posture": "Expansion Opportunity",
        },
    ]

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary="Movement is active.",
        signal_evidence=[],
        ranked_rows=ranked_rows,
        deep_enriched_rows=[],
        credential_packets={},
    )

    assert [row.person_name for row in brief.movement_rows] == [
        "Danielle M. McCoy",
        "Jason Dandridge",
    ]
    assert [action.person_name for action in brief.where_to_act[:2]] == [
        "Danielle M. McCoy",
        "Jason Dandridge",
    ]


def test_assemble_brief_uses_transition_language_for_departure_actions():
    assembler = MovementBriefAssembler()
    departure_row = MovementRecord(
        person_name="Danielle M. McCoy",
        target_company="Fannie Mae",
        previous_role="SVP & General Counsel, Fannie Mae",
        new_role="Departed",
        movement_type="Departure",
        category="BUYER",
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote="Danielle M. McCoy departed after 19 years.",
            source_url="https://example.com/departure",
            source_title="Departure Source",
        ),
    )

    brief = assembler.assemble(
        request=_request(),
        preflight=_preflight(),
        trigger=_trigger(),
        deep_research_summary="Fannie Mae is under active leadership transition.",
        signal_evidence=[],
        ranked_rows=[
            {
                "movement": departure_row,
                "known": False,
                "worked_with": False,
                "project_count": 0,
                "win_count": 0,
                "relationship_owner": None,
                "person_match_status": "matched",
                "rank_score": 10,
                "action_posture": "Monitor",
            }
        ],
        deep_enriched_rows=[],
        credential_packets={},
        derived_opportunities=[],
    )

    assert "around departed" not in brief.where_to_act[0].likely_play.lower()
    assert "transition" in brief.where_to_act[0].likely_play.lower()
