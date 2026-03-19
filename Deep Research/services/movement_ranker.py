"""
Deterministic ranking for enriched movement rows.
"""
from __future__ import annotations

from typing import Any, Dict, List


class MovementRanker:
    """Rank enriched movement rows for the main brief."""

    def rank(self, enriched_rows: List[Dict[str, Any]], max_rows: int = 10) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for item in enriched_rows:
            score = self._score(item)
            ranked.append(
                {
                    **item,
                    "rank_score": round(score, 4),
                    "action_posture": self._action_posture(item, score),
                }
            )

        ranked.sort(key=lambda item: item["rank_score"], reverse=True)
        return ranked[:max_rows]

    def _score(self, item: Dict[str, Any]) -> float:
        movement = item["movement"]
        score = 0.0
        if item.get("known"):
            score += 1.5
        if item.get("worked_with"):
            score += 2.0
        score += min(float(item.get("project_count", 0)), 5.0) * 0.3
        score += min(float(item.get("win_count", 0)), 5.0) * 0.5
        if item.get("relationship_owner"):
            score += 0.5
        if movement.category == "BUYER":
            score += 0.75
        if str(movement.company_context).strip().lower() == "internal":
            score += 0.5
        return score

    def _action_posture(self, item: Dict[str, Any], score: float) -> str:
        if item.get("worked_with") and score >= 4.0:
            return "Immediate Re-engagement"
        if item.get("known") or score >= 2.0:
            return "Expansion Opportunity"
        return "Monitor"
