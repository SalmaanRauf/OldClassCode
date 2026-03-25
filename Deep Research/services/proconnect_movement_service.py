"""
Lightweight two-pass ProConnect enrichment for movement-led workflows.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from models.movement_schemas import MovementRecord
from scripts.proconnect_client import ProConnectClient
from scripts.proconnect_lookup_logic import (
    exact_name_equals,
    full_person_name,
    resolve_company_and_account,
)
from scripts.proconnect_stakeholder_payload import (
    extract_person_detail_candidate,
    extract_person_search_candidates,
    merge_person_candidates,
)


PersonLoader = Callable[[str, str], Optional[Dict[str, Any]]]


class ProConnectMovementService:
    """Summarize relationship leverage for movement rows using per-person ProConnect payloads."""

    def __init__(
        self,
        person_loader: Optional[PersonLoader] = None,
        client: Optional[ProConnectClient] = None,
    ) -> None:
        self.client = client
        self._company_account_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._person_payload_cache: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
        self._person_detail_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        if person_loader is not None:
            self.person_loader = person_loader
        elif client is not None:
            self.person_loader = self._load_live_person_payload
        else:
            self.person_loader = lambda _name, _company: None

    def light_enrich_movements(self, movement_rows: List[MovementRecord]) -> List[Dict[str, Any]]:
        """Return compact leverage facts for all movement rows."""
        return [
            self.enrich_movement(row, include_person_detail=False)
            for row in movement_rows
        ]

    def deep_enrich_movements(
        self,
        movement_rows: List[MovementRecord],
        *,
        max_rows: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return richer person detail for the highest-priority movement rows."""
        selected = movement_rows[:max_rows]
        return [
            self.enrich_movement(row, include_person_detail=True)
            for row in selected
        ]

    def enrich_movement(
        self,
        row: MovementRecord,
        *,
        company_hint: Optional[str] = None,
        include_person_detail: bool = False,
    ) -> Dict[str, Any]:
        """Return leverage facts for a single movement row, optionally scoped to a specific company."""
        payload = self.person_loader(row.person_name, company_hint or row.target_company) or {}
        return self._build_enrichment(row, payload=payload, include_person_detail=include_person_detail)

    def _build_enrichment(
        self,
        row: MovementRecord,
        *,
        payload: Optional[Dict[str, Any]] = None,
        include_person_detail: bool,
    ) -> Dict[str, Any]:
        payload = payload or {}
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

    def _load_live_person_payload(self, person_name: str, target_company: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None

        cache_key = (self._cache_key(person_name), self._cache_key(target_company))
        if cache_key in self._person_payload_cache:
            return self._person_payload_cache[cache_key]

        account = self._resolve_company_account(person_name=person_name, target_company=target_company)
        if not account:
            self._person_payload_cache[cache_key] = None
            return None

        account_id = str(account.get("id") or "").strip()
        exact_person = self._resolve_exact_person(person_name=person_name, account=account, account_id=account_id)
        if not exact_person:
            self._person_payload_cache[cache_key] = None
            return None

        detail = self._load_person_detail(exact_person)
        payload = dict(exact_person)
        if detail:
            payload = merge_person_candidates(
                candidates=[payload, detail],
                selected=payload,
                title_hints=[],
            )
            payload["id"] = payload.get("id") or detail.get("id")
            payload["accountId"] = payload.get("accountId") or detail.get("accountId")

        self._person_payload_cache[cache_key] = payload
        return payload

    def _resolve_company_account(self, person_name: str, target_company: str) -> Optional[Dict[str, Any]]:
        cache_key = self._cache_key(target_company)
        if cache_key in self._company_account_cache:
            return self._company_account_cache[cache_key]

        _, account, _ = resolve_company_and_account(self.client, target_company, key_person_name=person_name)
        self._company_account_cache[cache_key] = account
        return account

    def _resolve_exact_person(
        self,
        *,
        person_name: str,
        account: Dict[str, Any],
        account_id: str,
    ) -> Optional[Dict[str, Any]]:
        exact_candidates: List[Dict[str, Any]] = []

        search_response = self.client.search_prospects(person_name)
        if search_response.get("success"):
            for candidate in extract_person_search_candidates(search_response.get("data")):
                candidate_name = full_person_name(candidate)
                if not exact_name_equals(person_name, candidate_name):
                    continue
                candidate_account_id = str(candidate.get("accountId") or "").strip()
                if account_id and candidate_account_id and candidate_account_id != account_id:
                    continue
                if account_id and not candidate_account_id:
                    continue
                exact_candidates.append(candidate)

        key_buyer_matches = self._exact_matches_from_records(person_name, account.get("keyBuyers") or [])
        if key_buyer_matches:
            exact_candidates.extend(key_buyer_matches)

        if not exact_candidates:
            return None

        selected = exact_candidates[0]
        for candidate in exact_candidates[1:]:
            selected = merge_person_candidates(
                candidates=[selected, candidate],
                selected=selected,
                title_hints=[],
            )
        return selected

    def _exact_matches_from_records(self, person_name: str, records: List[Any]) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            if not exact_name_equals(person_name, full_person_name(item)):
                continue
            match = dict(item)
            if "id" not in match and "contactId" in match:
                match["id"] = match.get("contactId")
            matches.append(match)
        return matches

    def _load_person_detail(self, person_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None

        prospect_id = self._person_identifier(person_payload)
        if not prospect_id:
            return None

        if prospect_id in self._person_detail_cache:
            return self._person_detail_cache[prospect_id]

        response = self.client.get_endpoint(f"/api/prospects/{prospect_id}", stop_on_auth=True)
        if not response.get("success"):
            self._person_detail_cache[prospect_id] = None
            return None

        detail = extract_person_detail_candidate(response.get("data"))
        self._person_detail_cache[prospect_id] = detail
        return detail

    @staticmethod
    def _person_identifier(payload: Dict[str, Any]) -> Optional[str]:
        for key in ("contactId", "id", "prospectId", "personId"):
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _cache_key(value: str) -> str:
        return " ".join(str(value or "").lower().split())

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
            "title": str(payload.get("titleExternal") or payload.get("title") or "").strip(),
            "location": str(payload.get("location") or "").strip(),
            "linkedin_url": str(payload.get("linkedinUrl") or payload.get("linkedInUrl") or "").strip(),
        }
