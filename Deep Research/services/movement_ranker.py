"""
Deterministic ranking for enriched movement rows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class MovementRanker:
    """Rank enriched movement rows for the main brief."""

    _DEPARTURE_MARKERS = (
        "departure",
        "departed",
        "resigned",
        "resignation",
        "retired",
        "retirement",
        "stepped down",
        "termination",
        "terminated",
        "left company",
        "left role",
        "stepped away",
    )
    _EXTERNAL_HIRE_MARKERS = (
        "external hire",
        "joined",
        "hired",
        "appointed from",
    )
    _APPOINTMENT_MARKERS = (
        "appointed",
        "appointment",
        "named",
        "elected",
    )
    _PROMOTION_MARKERS = (
        "promoted",
        "promotion",
        "role expansion",
        "scope expansion",
        "expanded role",
        "expanded responsibilities",
    )
    _ACTING_MARKERS = (
        "acting",
        "interim",
    )

    def rank(
        self,
        enriched_rows: List[Dict[str, Any]],
        max_rows: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
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
        if max_rows is None:
            return ranked
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
            score += 1.0
        if str(movement.company_context).strip().lower() == "internal":
            score += 0.5
        score += self._movement_priority(movement)
        return score

    def _action_posture(self, item: Dict[str, Any], score: float) -> str:
        if item.get("worked_with") and score >= 4.0:
            return "Immediate Re-engagement"
        if item.get("known") or score >= 2.0:
            return "Expansion Opportunity"
        return "Monitor"

    @classmethod
    def _movement_priority(cls, movement: Any) -> float:
        text = cls._movement_text(movement)
        if any(marker in text for marker in cls._DEPARTURE_MARKERS):
            return -1.5
        if any(marker in text for marker in cls._EXTERNAL_HIRE_MARKERS):
            return 1.4
        if any(marker in text for marker in cls._APPOINTMENT_MARKERS):
            return 1.1
        if any(marker in text for marker in cls._PROMOTION_MARKERS):
            return 0.9
        if any(marker in text for marker in cls._ACTING_MARKERS):
            return 0.6
        return 0.0

    @staticmethod
    def _movement_text(movement: Any) -> str:
        return " ".join(
            str(part or "").strip().lower()
            for part in (
                getattr(movement, "movement_type", ""),
                getattr(movement, "previous_role", ""),
                getattr(movement, "new_role", ""),
            )
            if str(part or "").strip()
        )
