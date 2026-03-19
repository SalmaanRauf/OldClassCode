"""
Tests for deterministic people movement brief assembly.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import SignalEvidence  # noqa: E402
from models.movement_schemas import (  # noqa: E402
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)
from models.bd_schemas import BDTrigger  # noqa: E402
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


def test_assemble_brief_caps_rows_and_actions_and_attaches_proof_packets():
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
        trigger=_trigger(),
        deep_research_summary="Capital One is under governance pressure and people movement is active.",
        signal_evidence=signal_evidence,
        ranked_rows=ranked_rows,
        deep_enriched_rows=deep_enriched_rows,
        credential_packets=credential_packets,
    )

    assert "Deep Research Findings" in brief.executive_summary
    assert "Credentials Agent Findings" in brief.executive_summary
    assert len(brief.signal_summary) == 2
    assert len(brief.movement_rows) == 10
    assert len(brief.where_to_act) == 3
    assert brief.where_to_act[0].person_name == "Person 0"
    assert brief.where_to_act[0].action_posture == "Immediate Re-engagement"
    assert "0 projects, 2 wins" in brief.where_to_act[0].likely_play
    assert brief.where_to_act[0].relationship_owner == "Ben L"
    assert "Relationship owner: Ben L." in brief.where_to_act[0].why_now
    assert "Leverage: known relationship, delivery history." in brief.where_to_act[0].why_now
    assert brief.movement_rows[0].leverage is not None
    assert brief.movement_rows[0].credentials_proof is not None
    assert brief.movement_rows[0].credentials_proof.lookup_status == "Matched"
    assert "deep-enriched rows: 10" in brief.executive_summary.lower()


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
