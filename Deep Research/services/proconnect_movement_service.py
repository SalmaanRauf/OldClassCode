"""
Lightweight two-pass ProConnect enrichment for movement-led workflows.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from models.movement_schemas import MovementRecord


PersonLoader = Callable[[str, str], Optional[Dict[str, Any]]]


class ProConnectMovementService:
    """Summarize relationship leverage for movement rows using per-person ProConnect payloads."""

    def __init__(self, person_loader: Optional[PersonLoader] = None) -> None:
        self.person_loader = person_loader or (lambda _name, _company: None)

    def light_enrich_movements(self, movement_rows: List[MovementRecord]) -> List[Dict[str, Any]]:
        """Return compact leverage facts for all movement rows."""
        return [self._build_enrichment(row, include_person_detail=False) for row in movement_rows]

    def deep_enrich_movements(
        self,
        movement_rows: List[MovementRecord],
        *,
        max_rows: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return richer person detail for the highest-priority movement rows."""
        selected = movement_rows[:max_rows]
        return [self._build_enrichment(row, include_person_detail=True) for row in selected]

    def _build_enrichment(self, row: MovementRecord, *, include_person_detail: bool) -> Dict[str, Any]:
        payload = self.person_loader(row.person_name, row.target_company) or {}
        matched = bool(payload)
        project_count = self._project_count(payload)
        win_count = self._win_count(payload)
        known = matched and self._has_relationship_evidence(payload, project_count=project_count, win_count=win_count)
        worked_with = project_count > 0 or win_count > 0
        enrichment = {
            "movement": row,
            "known": known,
            "worked_with": worked_with,
            "project_count": project_count,
            "win_count": win_count,
            "relationship_owner": self._relationship_owner(payload),
            "person_match_status": "matched" if matched else "no_match",
            "person_detail": self._person_detail(payload) if include_person_detail and matched else {},
        }
        return enrichment

    @staticmethod
    def _project_count(payload: Dict[str, Any]) -> int:
        explicit = payload.get("projectCount")
        if isinstance(explicit, int):
            return max(explicit, 0)
        projects = payload.get("projects")
        if isinstance(projects, list):
            return len(projects)
        return 0

    @staticmethod
    def _win_count(payload: Dict[str, Any]) -> int:
        explicit = payload.get("winCount")
        if isinstance(explicit, int):
            return max(explicit, 0)
        wins = 0
        for item in payload.get("primaryKeyBuyerOf") or []:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("opportunityStage") or "").strip().lower()
            if stage == "closed - won":
                wins += 1
        return wins

    @staticmethod
    def _has_relationship_evidence(payload: Dict[str, Any], *, project_count: int, win_count: int) -> bool:
        if project_count > 0 or win_count > 0:
            return True
        connections = payload.get("connections")
        if isinstance(connections, list) and connections:
            return True
        relationship_owner = payload.get("relationshipOwner")
        return bool(str(relationship_owner or "").strip())

    @staticmethod
    def _relationship_owner(payload: Dict[str, Any]) -> Optional[str]:
        direct = str(payload.get("relationshipOwner") or "").strip()
        if direct:
            return direct
        connections = payload.get("connections")
        if isinstance(connections, list):
            for item in connections:
                if not isinstance(item, dict):
                    continue
                employee = item.get("employee")
                if isinstance(employee, dict):
                    name = str(employee.get("name") or "").strip()
                    if name:
                        return name
        return None

    @staticmethod
    def _person_detail(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": str(payload.get("name") or "").strip(),
            "title": str(payload.get("title") or "").strip(),
            "location": str(payload.get("location") or "").strip(),
            "linkedin_url": str(payload.get("linkedinUrl") or "").strip(),
        }
