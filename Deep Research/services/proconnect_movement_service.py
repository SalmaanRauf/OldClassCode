"""
Lightweight two-pass ProConnect enrichment for movement-led workflows.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.movement_schemas import MovementRecord
from scripts.proconnect_client import ProConnectClient
from scripts.proconnect_lookup_logic import (
    exact_name_equals,
    full_person_name,
    resolve_company_and_account,
    same_first_last_name,
)
from scripts.proconnect_stakeholder_payload import (
    extract_person_detail_candidate,
    extract_person_search_candidates,
    merge_person_candidates,
)


PersonLoader = Callable[[str, str], Optional[Dict[str, Any]]]
logger = logging.getLogger(__name__)


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
            logger.info(
                "ProConnect movement lookup unresolved person=%s company=%s reason=account_unresolved",
                person_name,
                target_company,
            )
            self._person_payload_cache[cache_key] = None
            return None

        account_id = str(account.get("id") or "").strip()
        exact_person = self._resolve_exact_person(person_name=person_name, account=account, account_id=account_id)
        if not exact_person:
            logger.info(
                "ProConnect movement lookup unresolved person=%s company=%s account_id=%s reason=no_exact_person",
                person_name,
                target_company,
                account_id,
            )
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
        payload = self._merge_account_relationship_context(
            payload=payload,
            account=account,
            person_name=person_name,
        )

        logger.info(
            "ProConnect movement lookup matched person=%s company=%s account_id=%s projects=%s wins=%s owner=%s",
            person_name,
            target_company,
            account_id,
            self._project_count(payload),
            self._win_count(payload),
            self._relationship_owner(payload),
        )
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
        fallback_candidates: List[Dict[str, Any]] = []

        search_response = self.client.search_prospects(person_name)
        if search_response.get("success"):
            for candidate in extract_person_search_candidates(search_response.get("data")):
                candidate_name = full_person_name(candidate)
                name_matches_exact = exact_name_equals(person_name, candidate_name)
                name_matches_first_last = same_first_last_name(person_name, candidate_name)
                if not name_matches_exact and not name_matches_first_last:
                    continue
                candidate_account_id = str(candidate.get("accountId") or "").strip()
                if account_id and candidate_account_id and candidate_account_id != account_id:
                    continue
                if account_id and not candidate_account_id:
                    continue
                if name_matches_exact:
                    exact_candidates.append(candidate)
                else:
                    fallback_candidates.append(candidate)

        key_buyer_exact_matches = self._matching_records_from_account(
            person_name,
            account.get("keyBuyers") or [],
            allow_first_last=False,
        )
        if key_buyer_exact_matches:
            exact_candidates.extend(key_buyer_exact_matches)

        if not exact_candidates:
            key_buyer_fallback_matches = self._matching_records_from_account(
                person_name,
                account.get("keyBuyers") or [],
                allow_first_last=True,
            )
            fallback_candidates.extend(key_buyer_fallback_matches)

        candidates_to_merge = exact_candidates or fallback_candidates
        if not candidates_to_merge:
            return None

        selected = candidates_to_merge[0]
        for candidate in candidates_to_merge[1:]:
            selected = merge_person_candidates(
                candidates=[selected, candidate],
                selected=selected,
                title_hints=[],
            )
        return selected

    def _matching_records_from_account(
        self,
        person_name: str,
        records: List[Any],
        *,
        allow_first_last: bool,
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            candidate_name = full_person_name(item)
            if not candidate_name:
                continue
            if exact_name_equals(person_name, candidate_name):
                pass
            elif allow_first_last and same_first_last_name(person_name, candidate_name):
                pass
            else:
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
    def _coerce_count(value: Any) -> int:
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, str) and value.strip():
            try:
                return max(int(float(value)), 0)
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _person_reference_ids(payload: Dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for key in ("contactId", "id", "prospectId", "personId", "primaryKeyBuyerId", "buyerId"):
            value = payload.get(key)
            text = str(value or "").strip()
            if text:
                ids.add(text)
        return ids

    @staticmethod
    def _record_matches_person(person_name: str, record: Dict[str, Any], person_ids: set[str]) -> bool:
        for key in ("primaryKeyBuyer", "buyer", "buyerName", "primaryKeyBuyerName"):
            candidate_name = str(record.get(key) or "").strip()
            if candidate_name and (
                exact_name_equals(person_name, candidate_name) or same_first_last_name(person_name, candidate_name)
            ):
                return True
        candidate_id = str(
            record.get("primaryKeyBuyerId")
            or record.get("buyerId")
            or record.get("contactId")
            or record.get("id")
            or record.get("personId")
            or ""
        ).strip()
        if candidate_id and candidate_id in person_ids:
            return True
        candidate_name = full_person_name(record) or str(record.get("name") or record.get("fullName") or "").strip()
        return bool(candidate_name) and (
            exact_name_equals(person_name, candidate_name) or same_first_last_name(person_name, candidate_name)
        )

    def _best_matching_account_record(
        self,
        person_name: str,
        records: List[Any],
        person_ids: set[str],
    ) -> Dict[str, Any]:
        matches = self._matching_account_records(person_name, records, person_ids)
        return matches[0] if matches else {}

    def _matching_account_records(
        self,
        person_name: str,
        records: List[Any],
        person_ids: set[str],
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            if self._record_matches_person(person_name, item, person_ids):
                matches.append(dict(item))
        return matches

    @staticmethod
    def _merge_record_lists(*candidate_lists: Any, identity_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[Tuple[str, ...]] = set()
        for candidate_list in candidate_lists:
            if not isinstance(candidate_list, list):
                continue
            for item in candidate_list:
                if not isinstance(item, dict):
                    continue
                identity = tuple(str(item.get(key) or "").strip().lower() for key in identity_keys)
                if not any(identity):
                    identity = (str(item),)
                if identity in seen:
                    continue
                seen.add(identity)
                merged.append(dict(item))
        return merged

    def _merge_account_relationship_context(
        self,
        *,
        payload: Dict[str, Any],
        account: Dict[str, Any],
        person_name: str,
    ) -> Dict[str, Any]:
        merged = dict(payload)
        person_ids = self._person_reference_ids(merged)
        key_buyer = self._best_matching_account_record(person_name, account.get("keyBuyers") or [], person_ids)
        if key_buyer:
            merged = merge_person_candidates(
                candidates=[merged, key_buyer],
                selected=merged,
                title_hints=[],
            )

        account_projects = self._matching_account_records(person_name, account.get("project") or [], person_ids)
        scoped_wins = [
            item
            for bucket in ("allOpportunity", "openOpportunity")
            for item in self._matching_account_records(person_name, account.get(bucket) or [], person_ids)
            if str(item.get("opportunityStage") or item.get("stage") or "").strip().lower() == "closed - won"
        ]

        merged_projects = self._merge_record_lists(
            merged.get("projects"),
            key_buyer.get("projects"),
            account_projects,
            identity_keys=("projectId", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        merged_wins = self._merge_record_lists(
            merged.get("closeWonOpps") or merged.get("closeWonOpportunities"),
            key_buyer.get("closeWonOpps") or key_buyer.get("closeWonOpportunities"),
            scoped_wins,
            identity_keys=("opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        if merged_projects:
            merged["projects"] = merged_projects
        if merged_wins:
            merged["closeWonOpps"] = merged_wins
            merged["closeWonOpportunities"] = merged_wins

        merged["projectCount"] = max(
            self._coerce_count(merged.get("projectCount")),
            self._coerce_count(merged.get("project_count")),
            self._coerce_count(merged.get("numberOfProjects")),
            self._coerce_count(merged.get("numberOfProject")),
            self._coerce_count(key_buyer.get("projectCount") or key_buyer.get("project_count") or key_buyer.get("numberOfProjects") or key_buyer.get("numberOfProject")),
            len(merged_projects),
        )
        merged["winCount"] = max(
            self._coerce_count(merged.get("winCount")),
            self._coerce_count(merged.get("win_count")),
            self._coerce_count(merged.get("numberOfWins")),
            self._coerce_count(merged.get("wins")),
            self._coerce_count(key_buyer.get("winCount") or key_buyer.get("win_count") or key_buyer.get("numberOfWins") or key_buyer.get("wins")),
            len(merged_wins),
        )
        if not merged.get("relationshipOwner") and not merged.get("relationship_owner"):
            relationship_owner = key_buyer.get("relationshipOwner") or key_buyer.get("relationship_owner")
            if relationship_owner:
                merged["relationshipOwner"] = relationship_owner
        return merged

    @staticmethod
    def _project_count(payload: Dict[str, Any]) -> int:
        explicit_count = max(
            ProConnectMovementService._coerce_count(payload.get("projectCount")),
            ProConnectMovementService._coerce_count(payload.get("project_count")),
            ProConnectMovementService._coerce_count(payload.get("numberOfProjects")),
            ProConnectMovementService._coerce_count(payload.get("numberOfProject")),
        )
        projects = payload.get("projects")
        if isinstance(projects, list):
            return max(explicit_count, len(projects))
        return explicit_count

    @staticmethod
    def _win_count(payload: Dict[str, Any]) -> int:
        explicit_count = max(
            ProConnectMovementService._coerce_count(payload.get("winCount")),
            ProConnectMovementService._coerce_count(payload.get("win_count")),
            ProConnectMovementService._coerce_count(payload.get("numberOfWins")),
            ProConnectMovementService._coerce_count(payload.get("wins")),
        )
        explicit_wins = payload.get("closeWonOpps") or payload.get("closeWonOpportunities")
        if isinstance(explicit_wins, list):
            explicit_count = max(
                explicit_count,
                len([item for item in explicit_wins if isinstance(item, dict)]),
            )
        wins = 0
        for item in payload.get("primaryKeyBuyerOf") or []:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("opportunityStage") or "").strip().lower()
            if stage == "closed - won":
                wins += 1
        return max(explicit_count, wins)

    @staticmethod
    def _has_relationship_evidence(payload: Dict[str, Any], *, project_count: int, win_count: int) -> bool:
        if project_count > 0 or win_count > 0:
            return True
        connections = payload.get("connections")
        if isinstance(connections, list) and connections:
            return True
        relationship_owner = payload.get("relationshipOwner") or payload.get("relationship_owner")
        return bool(str(relationship_owner or "").strip())

    @staticmethod
    def _relationship_owner(payload: Dict[str, Any]) -> Optional[str]:
        direct = str(payload.get("relationshipOwner") or payload.get("relationship_owner") or "").strip()
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
