"""
Tests for movement ranking and action posture classification.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import MovementActionPosture, MovementEvidence, MovementRecord  # noqa: E402
from services.movement_ranker import MovementRanker  # noqa: E402


def _row(name: str, category: str = "BUYER") -> MovementRecord:
    return MovementRecord(
        person_name=name,
        target_company="Capital One",
        previous_role="Director",
        new_role="Vice President",
        movement_type="Promoted",
        category=category,
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"{name} was promoted.",
            source_url=f"https://example.com/{name.lower().replace(' ', '-')}",
        ),
    )


def test_ranker_orders_rows_by_combined_leverage_and_role_priority():
    ranker = MovementRanker()
    enriched_rows = [
        {
            "movement": _row("Low Leverage"),
            "known": False,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
        },
        {
            "movement": _row("High Leverage"),
            "known": True,
            "worked_with": True,
            "project_count": 3,
            "win_count": 2,
            "relationship_owner": "Ben L",
        },
    ]

    ranked = ranker.rank(enriched_rows)

    assert ranked[0]["movement"].person_name == "High Leverage"
    assert ranked[0]["rank_score"] > ranked[1]["rank_score"]


def test_ranker_keeps_all_rows_by_default():
    ranker = MovementRanker()
    enriched_rows = [
        {
            "movement": _row(f"Person {idx}"),
            "known": True,
            "worked_with": idx % 2 == 0,
            "project_count": idx,
            "win_count": 0,
            "relationship_owner": "Owner",
        }
        for idx in range(12)
    ]

    ranked = ranker.rank(enriched_rows)

    assert len(ranked) == 12


def test_ranker_honors_explicit_row_cap_when_requested():
    ranker = MovementRanker()
    enriched_rows = [
        {
            "movement": _row(f"Person {idx}"),
            "known": True,
            "worked_with": idx % 2 == 0,
            "project_count": idx,
            "win_count": 0,
            "relationship_owner": "Owner",
        }
        for idx in range(12)
    ]

    ranked = ranker.rank(enriched_rows, max_rows=10)

    assert len(ranked) == 10


def test_ranker_assigns_action_posture_from_rank_signal():
    ranker = MovementRanker()

    ranked = ranker.rank([
        {
            "movement": _row("Immediate"),
            "known": True,
            "worked_with": True,
            "project_count": 4,
            "win_count": 2,
            "relationship_owner": "Ben L",
        },
        {
            "movement": _row("Expansion"),
            "known": True,
            "worked_with": False,
            "project_count": 1,
            "win_count": 0,
            "relationship_owner": "Naomi K",
        },
        {
            "movement": _row("Monitor", category="EXEC"),
            "known": False,
            "worked_with": False,
            "project_count": 0,
            "win_count": 0,
            "relationship_owner": None,
        },
    ])

    postures = [item["action_posture"] for item in ranked]
    assert postures[0] == "Immediate Re-engagement"
    assert "Expansion Opportunity" in postures
    assert "Monitor" in postures
