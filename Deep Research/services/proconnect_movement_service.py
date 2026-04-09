"""
Lightweight two-pass ProConnect enrichment for movement-led workflows.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.movement_schemas import MovementRecord
from scripts.proconnect_client import ProConnectClient
from scripts.proconnect_lookup_logic import (
    exact_name_equals,
    full_person_name,
    get_zoom_info_account_id,
    resolve_company_and_account,
    same_first_last_name,
)
from scripts.proconnect_stakeholder_payload import (
    build_people_candidates_for_account,
    collect_org_chart_people,
    extract_person_search_candidates,
    merge_person_candidates,
    select_best_candidate,
    select_person_detail_candidate,
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
        self._person_payload_cache: Dict[Tuple[str, str, str], Optional[Dict[str, Any]]] = {}
        self._person_detail_cache: Dict[str, Optional[Dict[str, Any]]] = {}
        self._account_people_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._account_people_warnings_cache: Dict[str, List[str]] = {}
        self._uses_live_person_loader = person_loader is None and client is not None
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
        if self._uses_live_person_loader:
            payload = self._load_live_person_payload(
                row.person_name,
                company_hint or row.target_company,
                title_hint=row.new_role,
            ) or {}
        else:
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
        known = matched
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

    def _load_live_person_payload(
        self,
        person_name: str,
        target_company: str,
        *,
        title_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None

        cache_key = (
            self._cache_key(person_name),
            self._cache_key(target_company),
            self._cache_key(title_hint or ""),
        )
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
        title_hints = [title_hint] if str(title_hint or "").strip() else []
        exact_person = self._resolve_exact_person(
            person_name=person_name,
            account=account,
            account_id=account_id,
            title_hints=title_hints,
        )
        if not exact_person:
            logger.info(
                "ProConnect movement lookup unresolved person=%s company=%s account_id=%s reason=no_exact_person",
                person_name,
                target_company,
                account_id,
            )
            self._person_payload_cache[cache_key] = None
            return None

        detail = self._load_person_detail(exact_person, person_name=person_name)
        payload = dict(exact_person)
        trust_person_delivery_fields = self._has_direct_person_relationship_signal(exact_person)
        if detail:
            selected = select_best_candidate([payload, detail], title_hints=title_hints)
            payload = merge_person_candidates(
                candidates=[payload, detail],
                selected=selected,
                title_hints=title_hints,
            )
            payload = self._prefer_detail_profile_fields(payload, detail)
            payload["id"] = payload.get("id") or detail.get("id")
            payload["accountId"] = payload.get("accountId") or detail.get("accountId")
        payload = self._merge_account_relationship_context(
            payload=payload,
            account=account,
            person_name=person_name,
            trust_person_delivery_fields=trust_person_delivery_fields,
        )
        payload = self._preserve_requested_identity(
            payload=payload,
            requested_name=person_name,
            fallback=exact_person,
        )

        logger.info(
            "ProConnect movement lookup matched person=%s company=%s account_id=%s projects=%s wins=%s owner=%s raw_project_count=%s raw_win_count=%s projects_list=%s wins_list=%s payload_debug=%s",
            person_name,
            target_company,
            account_id,
            self._project_count(payload),
            self._win_count(payload),
            self._relationship_owner(payload),
            payload.get("projectCount") or payload.get("project_count") or payload.get("numberOfProjects"),
            payload.get("winCount") or payload.get("win_count") or payload.get("numberOfWins") or payload.get("wins"),
            len(payload.get("projects") or []) if isinstance(payload.get("projects"), list) else 0,
            len(payload.get("closeWonOpps") or payload.get("closeWonOpportunities") or [])
            if isinstance(payload.get("closeWonOpps") or payload.get("closeWonOpportunities"), list)
            else 0,
            self._payload_debug_snapshot(payload),
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
        title_hints: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        exact_candidates: List[Dict[str, Any]] = []
        fallback_candidates: List[Dict[str, Any]] = []
        search_exact_count = 0
        search_fallback_count = 0
        name_variants = self._person_name_variants(person_name)

        seen_search_queries: set[str] = set()
        for variant in name_variants:
            if variant in seen_search_queries:
                continue
            seen_search_queries.add(variant)
            search_response = self.client.search_prospects(variant)
            if not search_response.get("success"):
                continue
            for candidate in extract_person_search_candidates(search_response.get("data")):
                candidate_name = full_person_name(candidate)
                name_matches_exact = self._matches_name_exact(name_variants, candidate_name)
                name_matches_first_last = self._matches_name_fallback(name_variants, candidate_name)
                if not name_matches_exact and not name_matches_first_last:
                    continue
                candidate_account_id = str(candidate.get("accountId") or "").strip()
                if account_id and candidate_account_id and candidate_account_id != account_id:
                    continue
                if account_id and not candidate_account_id:
                    continue
                if name_matches_exact:
                    exact_candidates.append(candidate)
                    search_exact_count += 1
                else:
                    fallback_candidates.append(candidate)
                    search_fallback_count += 1

        key_buyer_exact_matches = self._matching_records_from_account(
            name_variants,
            account.get("keyBuyers") or [],
            allow_first_last=False,
        )
        if key_buyer_exact_matches:
            exact_candidates.extend(key_buyer_exact_matches)

        if not exact_candidates:
            key_buyer_fallback_matches = self._matching_records_from_account(
                name_variants,
                account.get("keyBuyers") or [],
                allow_first_last=True,
            )
            fallback_candidates.extend(key_buyer_fallback_matches)

        account_people = self._build_account_people_pool(account, account_id=account_id)
        account_people_exact_matches = self._matching_records_from_account(
            name_variants,
            account_people,
            allow_first_last=False,
        )
        if account_people_exact_matches:
            exact_candidates.extend(account_people_exact_matches)

        account_people_fallback_matches: List[Dict[str, Any]] = []
        if not exact_candidates:
            account_people_fallback_matches = self._matching_records_from_account(
                name_variants,
                account_people,
                allow_first_last=True,
            )
            fallback_candidates.extend(account_people_fallback_matches)

        logger.info(
            "ProConnect movement candidate pool person=%s variants=%s account_id=%s search_exact=%s search_fallback=%s key_buyer_exact=%s key_buyer_fallback=%s account_people_exact=%s account_people_fallback=%s org_warnings=%s search_exact_names=%s fallback_names=%s account_people_exact_names=%s",
            person_name,
            name_variants,
            account_id,
            search_exact_count,
            search_fallback_count,
            len(key_buyer_exact_matches),
            len(key_buyer_fallback_matches) if 'key_buyer_fallback_matches' in locals() else 0,
            len(account_people_exact_matches),
            len(account_people_fallback_matches),
            len(self._account_people_warnings_cache.get(account_id, [])),
            self._summarize_candidate_names(exact_candidates),
            self._summarize_candidate_names(fallback_candidates),
            self._summarize_candidate_names(account_people_exact_matches),
        )

        candidates_to_merge = exact_candidates or fallback_candidates
        if not candidates_to_merge:
            return None

        hints = [hint for hint in (title_hints or []) if str(hint or "").strip()]
        selected = select_best_candidate(candidates_to_merge, title_hints=hints)
        return merge_person_candidates(
            candidates=candidates_to_merge,
            selected=selected,
            title_hints=hints,
        )

    def _build_account_people_pool(self, account: Dict[str, Any], *, account_id: str) -> List[Dict[str, Any]]:
        cache_key = account_id or self._cache_key(str(account.get("name") or ""))
        if cache_key in self._account_people_cache:
            return self._account_people_cache[cache_key]

        org_chart_people: List[Dict[str, Any]] = []
        warnings: List[str] = []
        if self.client:
            _, org_chart_people, warnings = collect_org_chart_people(
                client=self.client,
                zoom_info_account_id=get_zoom_info_account_id(account),
                department_hint=None,
            )

        people = build_people_candidates_for_account(
            account=account,
            company_scope="to",
            account_id=account_id,
            org_chart_people=org_chart_people,
            probe_payloads=[],
        )
        self._account_people_cache[cache_key] = people
        self._account_people_warnings_cache[cache_key] = warnings
        return people

    def _matching_records_from_account(
        self,
        person_names: List[str],
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
            if self._matches_name_exact(person_names, candidate_name):
                pass
            elif allow_first_last and self._matches_name_fallback(person_names, candidate_name):
                pass
            else:
                continue
            match = dict(item)
            if "id" not in match and "contactId" in match:
                match["id"] = match.get("contactId")
            matches.append(match)
        return matches

    def _load_person_detail(
        self,
        person_payload: Dict[str, Any],
        *,
        person_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
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

        detail, _diagnostics = select_person_detail_candidate(
            payload=response.get("data"),
            person_name=person_name,
            matched_person=person_payload,
        )
        if detail:
            detail_name = full_person_name(detail) or str(detail.get("name") or "").strip()
            requested_name = str(person_name or full_person_name(person_payload) or "").strip()
            if requested_name and detail_name and not (
                exact_name_equals(requested_name, detail_name) or same_first_last_name(requested_name, detail_name)
            ):
                detail = None
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
        for key in ("contactId", "id", "prospectId", "personId"):
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
    def _best_matching_key_buyer_record(person_name: str, records: List[Any]) -> Dict[str, Any]:
        for item in records:
            if not isinstance(item, dict):
                continue
            candidate_name = full_person_name(item) or str(item.get("name") or "").strip()
            if not candidate_name:
                continue
            if exact_name_equals(person_name, candidate_name) or same_first_last_name(person_name, candidate_name):
                return dict(item)
        return {}

    @staticmethod
    def _merge_record_lists(*candidate_lists: Any, identity_keys: Tuple[str, ...]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: Dict[str, int] = {}
        weak_identity_keys = {
            "primaryKeyBuyerId",
            "primaryKeyBuyer",
            "buyerId",
            "buyer",
            "buyerName",
            "primaryKeyBuyerName",
        }
        for candidate_list in candidate_lists:
            if not isinstance(candidate_list, list):
                continue
            for item in candidate_list:
                if not isinstance(item, dict):
                    continue
                strong_fingerprints = [
                    f"{key}:{str(item.get(key) or '').strip().lower()}"
                    for key in identity_keys
                    if key not in weak_identity_keys
                    if str(item.get(key) or "").strip()
                ]
                weak_fingerprints = [
                    f"{key}:{str(item.get(key) or '').strip().lower()}"
                    for key in identity_keys
                    if key in weak_identity_keys
                    if str(item.get(key) or "").strip()
                ]
                fingerprints = strong_fingerprints or weak_fingerprints
                if not fingerprints:
                    fingerprints = [f"record:{str(item).strip().lower()}"]

                existing_index = next((seen[fingerprint] for fingerprint in fingerprints if fingerprint in seen), None)
                if existing_index is None:
                    merged.append(dict(item))
                    new_index = len(merged) - 1
                    for fingerprint in fingerprints:
                        seen[fingerprint] = new_index
                    continue

                merged_item = dict(merged[existing_index])
                for key, value in item.items():
                    if key in {"projects", "closeWonOpps", "closeWonOpportunities", "connections"}:
                        merged_item[key] = merge_person_candidates(
                            candidates=[merged_item, {key: value}],
                            selected=merged_item,
                            title_hints=[],
                        ).get(key)
                        continue
                    if merged_item.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                        merged_item[key] = value
                merged[existing_index] = merged_item
                for fingerprint in fingerprints:
                    seen[fingerprint] = existing_index
        return merged

    @staticmethod
    def _closed_won_records(value: Any) -> List[Dict[str, Any]]:
        wins: List[Dict[str, Any]] = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict):
                continue
            stage = str(item.get("opportunityStage") or item.get("stage") or "").strip().lower()
            if stage == "closed - won":
                wins.append(dict(item))
        return wins

    @staticmethod
    def _has_direct_person_relationship_signal(payload: Dict[str, Any]) -> bool:
        if str(payload.get("relationshipOwner") or payload.get("relationship_owner") or "").strip():
            return True
        connections = payload.get("connections")
        return isinstance(connections, list) and bool(connections)

    def _merge_account_relationship_context(
        self,
        *,
        payload: Dict[str, Any],
        account: Dict[str, Any],
        person_name: str,
        trust_person_delivery_fields: bool = False,
    ) -> Dict[str, Any]:
        merged = dict(payload)
        person_ids = self._person_reference_ids(merged)
        key_buyer = self._best_matching_key_buyer_record(person_name, account.get("keyBuyers") or [])
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
        has_direct_relationship_signal = trust_person_delivery_fields
        trusted_raw_wins = self._merge_record_lists(
            (merged.get("closeWonOpps") or merged.get("closeWonOpportunities")) if has_direct_relationship_signal else [],
            self._closed_won_records(merged.get("primaryKeyBuyerOf")) if has_direct_relationship_signal else [],
            identity_keys=("opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        key_buyer_wins = self._merge_record_lists(
            key_buyer.get("closeWonOpps") or key_buyer.get("closeWonOpportunities"),
            self._closed_won_records(key_buyer.get("primaryKeyBuyerOf")),
            identity_keys=("opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )

        merged_projects = self._merge_record_lists(
            merged.get("projects") if has_direct_relationship_signal else [],
            key_buyer.get("projects"),
            account_projects,
            identity_keys=("projectId", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        merged_wins = self._merge_record_lists(
            trusted_raw_wins,
            key_buyer_wins,
            scoped_wins,
            identity_keys=("opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        if merged_projects:
            merged["projects"] = merged_projects
        else:
            merged.pop("projects", None)
        if merged_wins:
            merged["closeWonOpps"] = merged_wins
            merged["closeWonOpportunities"] = merged_wins
        else:
            merged.pop("closeWonOpps", None)
            merged.pop("closeWonOpportunities", None)

        scoped_project_count = max(
            (
                max(
                    self._coerce_count(merged.get("projectCount")),
                    self._coerce_count(merged.get("project_count")),
                    self._coerce_count(merged.get("numberOfProjects")),
                    self._coerce_count(merged.get("numberOfProject")),
                    len(merged.get("projects")) if isinstance(merged.get("projects"), list) else 0,
                )
                if has_direct_relationship_signal
                else 0
            ),
            self._coerce_count(key_buyer.get("projectCount") or key_buyer.get("project_count") or key_buyer.get("numberOfProjects") or key_buyer.get("numberOfProject")),
            len(merged_projects),
        )
        scoped_win_count = max(
            (
                max(
                    self._coerce_count(merged.get("winCount")),
                    self._coerce_count(merged.get("win_count")),
                    self._coerce_count(merged.get("numberOfWins")),
                    self._coerce_count(merged.get("wins")),
                    len(trusted_raw_wins),
                )
                if has_direct_relationship_signal
                else 0
            ),
            self._coerce_count(key_buyer.get("winCount") or key_buyer.get("win_count") or key_buyer.get("numberOfWins") or key_buyer.get("wins")),
            len(merged_wins),
        )
        merged["projectCount"] = scoped_project_count
        merged["project_count"] = scoped_project_count
        merged["numberOfProjects"] = scoped_project_count
        merged["numberOfProject"] = scoped_project_count
        merged["winCount"] = scoped_win_count
        merged["win_count"] = scoped_win_count
        merged["numberOfWins"] = scoped_win_count
        merged["wins"] = scoped_win_count
        trusted_primary_key_buyer_of = self._merge_record_lists(
            self._closed_won_records(merged.get("primaryKeyBuyerOf")) if has_direct_relationship_signal else [],
            self._closed_won_records(key_buyer.get("primaryKeyBuyerOf")),
            identity_keys=("opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyer", "primaryKeyBuyerId"),
        )
        if trusted_primary_key_buyer_of:
            merged["primaryKeyBuyerOf"] = trusted_primary_key_buyer_of
        else:
            merged.pop("primaryKeyBuyerOf", None)
        if not merged.get("relationshipOwner") and not merged.get("relationship_owner"):
            relationship_owner = key_buyer.get("relationshipOwner") or key_buyer.get("relationship_owner")
            if relationship_owner:
                merged["relationshipOwner"] = relationship_owner
        merged["_account_project_matches"] = len(account_projects)
        merged["_account_win_matches"] = len(scoped_wins)
        logger.info(
            "ProConnect account-context merge person=%s key_buyer=%s account_project_matches=%s account_win_matches=%s merged_project_count=%s merged_win_count=%s merged_project_names=%s merged_win_names=%s owner=%s",
            person_name,
            full_person_name(key_buyer) or key_buyer.get("name") or None,
            len(account_projects),
            len(scoped_wins),
            self._project_count(merged),
            self._win_count(merged),
            self._list_names(merged.get("projects")),
            self._list_names(merged.get("closeWonOpps") or merged.get("closeWonOpportunities")),
            self._relationship_owner(merged),
        )
        return merged

    @staticmethod
    def _prefer_detail_profile_fields(payload: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(payload)
        for key in (
            "name",
            "firstName",
            "lastName",
            "title",
            "titleExternal",
            "location",
            "linkedinUrl",
            "linkedInUrl",
            "emailAddress",
            "email",
            "phone",
            "photoUrl",
        ):
            value = detail.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
        connections = detail.get("connections")
        if isinstance(connections, list) and connections:
            merged["connections"] = connections
        return merged

    @classmethod
    def _preserve_requested_identity(
        cls,
        *,
        payload: Dict[str, Any],
        requested_name: str,
        fallback: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested_variants = cls._person_name_variants(requested_name)
        payload_name = full_person_name(payload) or str(payload.get("name") or "").strip()
        if cls._matches_name_exact(requested_variants, payload_name) or cls._matches_name_fallback(
            requested_variants, payload_name
        ):
            return payload

        restored = dict(payload)
        fallback_name = full_person_name(fallback) or str(fallback.get("name") or "").strip()
        if not (
            cls._matches_name_exact(requested_variants, fallback_name)
            or cls._matches_name_fallback(requested_variants, fallback_name)
        ):
            return payload

        identity_fields = (
            "name",
            "firstName",
            "lastName",
            "title",
            "titleExternal",
            "location",
            "linkedinUrl",
            "linkedInUrl",
            "emailAddress",
            "email",
            "phone",
            "photoUrl",
            "pastJobExperience",
            "education",
            "function",
            "level",
            "lastUpdated",
            "connections",
            "connectedColleagues",
            "connectedColleague",
        )
        for key in identity_fields:
            if key in fallback:
                restored[key] = fallback.get(key)
            else:
                restored.pop(key, None)
        return restored

    @staticmethod
    def _person_name_variants(person_name: str) -> List[str]:
        variants: List[str] = []
        raw = str(person_name or "").strip()
        if not raw:
            return variants

        def _add(value: str) -> None:
            candidate = " ".join(value.split()).strip()
            if candidate and candidate not in variants:
                variants.append(candidate)

        _add(raw)
        stripped = re.sub(r"\([^)]*\)", "", raw).strip()
        _add(stripped)
        stripped_parts = stripped.split()
        last_name = stripped_parts[-1] if stripped_parts else ""
        for alias in re.findall(r"\(([^)]*)\)", raw):
            alias_parts = alias.split()
            if len(alias_parts) >= 2:
                _add(alias)
            elif alias_parts and last_name:
                _add(f"{alias_parts[0]} {last_name}")

        normalized = unicodedata.normalize("NFKD", raw)
        ascii_name = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        _add(ascii_name)
        stripped_ascii = re.sub(r"\([^)]*\)", "", ascii_name).strip()
        _add(stripped_ascii)
        stripped_ascii_parts = stripped_ascii.split()
        last_ascii_name = stripped_ascii_parts[-1] if stripped_ascii_parts else ""
        for alias in re.findall(r"\(([^)]*)\)", ascii_name):
            alias_parts = alias.split()
            if len(alias_parts) >= 2:
                _add(alias)
            elif alias_parts and last_ascii_name:
                _add(f"{alias_parts[0]} {last_ascii_name}")
        return variants

    @staticmethod
    def _matches_name_exact(person_names: List[str], candidate_name: str) -> bool:
        return any(exact_name_equals(name, candidate_name) for name in person_names if name)

    @staticmethod
    def _matches_name_fallback(person_names: List[str], candidate_name: str) -> bool:
        return any(same_first_last_name(name, candidate_name) for name in person_names if name)

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
            "internal_connections": ProConnectMovementService._internal_connection_names(payload),
        }

    @classmethod
    def _internal_connection_names(cls, payload: Dict[str, Any], *, limit: int = 3) -> List[str]:
        names: List[str] = []
        for key in ("connections", "connectedColleagues", "connectedColleague"):
            for name in cls._list_names(payload.get(key), limit=limit):
                if name not in names:
                    names.append(name)
                if len(names) >= limit:
                    return names
        return names

    @staticmethod
    def _list_names(value: Any, *, limit: int = 6) -> List[str]:
        if not isinstance(value, list):
            return []
        names: List[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            employee = item.get("employee") if isinstance(item.get("employee"), dict) else {}
            name = str(
                item.get("name")
                or item.get("opportunity")
                or item.get("project")
                or item.get("buyer")
                or item.get("primaryKeyBuyer")
                or employee.get("name")
                or ""
            ).strip()
            if name:
                names.append(name)
            if len(names) >= limit:
                break
        return names

    @classmethod
    def _summarize_candidate_names(cls, candidates: List[Dict[str, Any]], *, limit: int = 6) -> List[str]:
        summary: List[str] = []
        for candidate in candidates[:limit]:
            name = full_person_name(candidate) or str(candidate.get("name") or candidate.get("fullName") or "").strip()
            source = str(candidate.get("_source") or "").strip()
            account_id = str(candidate.get("accountId") or candidate.get("linked_account_id") or "").strip()
            bits = [name] if name else []
            if source:
                bits.append(f"source={source}")
            if account_id:
                bits.append(f"account={account_id}")
            if bits:
                summary.append(" | ".join(bits))
        return summary

    @classmethod
    def _payload_debug_snapshot(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": str(payload.get("name") or "").strip() or None,
            "title": str(payload.get("titleExternal") or payload.get("title") or "").strip() or None,
            "source": str(payload.get("_source") or "").strip() or None,
            "account_id": str(payload.get("accountId") or payload.get("linked_account_id") or "").strip() or None,
            "relationship_owner": cls._relationship_owner(payload),
            "project_count": cls._project_count(payload),
            "win_count": cls._win_count(payload),
            "project_names": cls._list_names(payload.get("projects")),
            "win_names": cls._list_names(payload.get("closeWonOpps") or payload.get("closeWonOpportunities")),
            "connection_names": cls._list_names(payload.get("connections")),
            "account_project_matches": payload.get("_account_project_matches"),
            "account_win_matches": payload.get("_account_win_matches"),
        }
