"""
Account-first ProConnect research collection.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from scripts.proconnect_lookup_logic import get_zoom_info_account_id, resolve_company_and_account
from scripts.proconnect_stakeholder_payload import (
    build_account_context,
    build_account_team_section,
    build_key_buyers_section,
    build_opportunities_section,
    build_projects_section,
    build_relationship_network_section,
    collect_org_chart_people_with_diagnostics,
    extract_optional_sections,
    latest_engagement_date,
    probe_additional_endpoints,
)


class ProConnectAccountResearchService:
    """Collect normalized internal account context for a target account."""

    def __init__(self, client: Optional[Any] = None) -> None:
        self.client = client

    def collect_account_research(
        self,
        company_name: str,
        *,
        department_hint: Optional[str] = None,
        enable_probes: bool = True,
    ) -> Dict[str, Any]:
        if self.client is None:
            raise ValueError("ProConnectAccountResearchService requires a client.")

        resolution, account, warnings = resolve_company_and_account(self.client, company_name)
        warnings = [str(item).strip() for item in list(warnings or []) if str(item or "").strip()]

        if not account:
            return {
                "account_resolution": self._build_account_resolution(resolution, account),
                "account_status": {
                    "summary": "Account resolution failed; internal account context is unavailable.",
                    "worked_before": None,
                    "account_activity_status": "unknown",
                    "is_client": None,
                    "is_msa": None,
                },
                "known_protiviti_team": build_account_team_section(None),
                "known_relationships": {
                    "protiviti_alumni": {"items": []},
                    "connected_colleagues": {"items": []},
                    "warm_intro_path_available": False,
                    "relationship_routes": [],
                },
                "known_buyers": [],
                "open_opportunities": [],
                "past_work": {
                    "total_projects": 0,
                    "projects": [],
                    "solutions_list": [],
                    "most_recent_engagement_date": None,
                    "closed_won_opportunities": [],
                },
                "org_chart_coverage": {
                    "available": False,
                    "people_count": 0,
                    "focus_department": department_hint,
                    "items": [],
                    "warnings": [],
                    "diagnostics": {},
                },
                "optional_internal_signals": None,
                "coverage_gaps": ["Internal ProConnect account context could not be resolved."],
                "diagnostics": {"warnings": warnings, "resolution": resolution},
            }

        zoom_info_account_id = get_zoom_info_account_id(account)
        probe_payloads: List[Dict[str, Any]] = []
        if enable_probes and zoom_info_account_id:
            probe_payloads, probe_warnings = probe_additional_endpoints(
                self.client,
                account.get("id"),
                zoom_info_account_id,
            )
            warnings.extend(
                str(item).strip() for item in list(probe_warnings or []) if str(item or "").strip()
            )

        org_items, org_people, org_warnings, org_diagnostics = collect_org_chart_people_with_diagnostics(
            client=self.client,
            zoom_info_account_id=zoom_info_account_id,
            department_hint=department_hint,
        )
        warnings.extend(
            str(item).strip()
            for item in list(org_warnings or [])
            if str(item or "").strip() and str(item).strip() not in warnings
        )

        account_context = build_account_context(account)
        buyers = self._sorted_buyers(build_key_buyers_section(account).get("items", []))
        relationships = build_relationship_network_section(account, probe_payloads=probe_payloads)
        coverage_gaps = self._build_coverage_gaps(
            zoom_info_account_id=zoom_info_account_id,
            enable_probes=enable_probes,
            org_people=org_people,
            relationships=relationships,
        )

        return {
            "account_resolution": self._build_account_resolution(resolution, account),
            "account_status": self._build_account_status(account_context, account),
            "known_protiviti_team": build_account_team_section(account),
            "known_relationships": relationships,
            "known_buyers": buyers,
            "open_opportunities": self._build_open_opportunities(account),
            "past_work": self._build_past_work(account),
            "org_chart_coverage": {
                "available": bool(org_people),
                "people_count": len(org_people),
                "focus_department": department_hint,
                "items": org_items,
                "warnings": org_warnings,
                "diagnostics": org_diagnostics,
            },
            "optional_internal_signals": extract_optional_sections(account, probe_payloads) if probe_payloads else None,
            "coverage_gaps": coverage_gaps,
            "diagnostics": {
                "warnings": warnings,
                "resolution": resolution,
            },
        }

    @staticmethod
    def _build_account_resolution(resolution: Dict[str, Any], account: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        selected = resolution.get("selected_candidate") if isinstance(resolution, dict) else None
        return {
            "query": str((resolution or {}).get("query") or ""),
            "resolved": bool((resolution or {}).get("resolved_account")),
            "account_id": (account or {}).get("id"),
            "company_name": (account or {}).get("name"),
            "selected_candidate": selected if isinstance(selected, dict) else None,
            "selected_score": (resolution or {}).get("selected_score"),
            "search_status_code": (resolution or {}).get("search_status_code"),
            "account_fetch_status_code": (resolution or {}).get("account_fetch_status_code"),
        }

    @staticmethod
    def _build_account_status(account_context: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
        worked_before = account_context.get("worked_before")
        is_client = account_context.get("is_client")
        is_msa = account_context.get("is_msa")
        activity = str(account_context.get("account_activity_status") or "unknown")

        if worked_before is True:
            summary = "Known ProConnect work is present for this account."
        elif worked_before is False:
            summary = "No known ProConnect work found."
        else:
            summary = "Known ProConnect work status is not available."
        if is_msa is False:
            summary = f"{summary} MSA not found in ProConnect payload."

        return {
            "summary": summary,
            "worked_before": worked_before,
            "account_activity_status": activity,
            "is_client": is_client,
            "is_msa": is_msa,
            "industry": account_context.get("industry"),
            "website": account_context.get("website"),
            "ticker": account_context.get("ticker"),
            "headquarters": account_context.get("headquarters"),
            "annual_revenue": account_context.get("annual_revenue"),
            "number_of_employees": account_context.get("number_of_employees"),
            "zoom_info_account_id": account_context.get("zoom_info_account_id"),
            "raw_open_opportunity_count": account.get("numberOfOpenOpportunity"),
            "raw_all_opportunity_count": account.get("numberOfAllOpportunity"),
            "raw_project_count": account.get("numberOfProject"),
        }

    @staticmethod
    def _sorted_buyers(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            list(items or []),
            key=lambda item: (int(item.get("wins_5y") or 0), str(item.get("name") or "")),
            reverse=True,
        )

    @staticmethod
    def _build_open_opportunities(account: Dict[str, Any]) -> List[Dict[str, Any]]:
        all_items = build_opportunities_section(account).get("items", [])
        open_items: List[Dict[str, Any]] = []
        for item in all_items:
            stage = str(item.get("stage") or "").strip().lower()
            if stage.startswith("closed"):
                continue
            open_items.append(item)
        return open_items

    @staticmethod
    def _build_past_work(account: Dict[str, Any]) -> Dict[str, Any]:
        projects = build_projects_section(account)
        opportunities = build_opportunities_section(account).get("items", [])
        closed_won = [
            item
            for item in opportunities
            if str(item.get("stage") or "").strip().lower() == "closed - won"
        ]
        return {
            "total_projects": int(projects.get("total_projects") or 0),
            "projects": list(projects.get("items") or []),
            "solutions_list": list(projects.get("solutions_list") or []),
            "most_recent_engagement_date": latest_engagement_date(account),
            "closed_won_opportunities": closed_won,
        }

    @staticmethod
    def _build_coverage_gaps(
        *,
        zoom_info_account_id: Optional[str],
        enable_probes: bool,
        org_people: List[Dict[str, Any]],
        relationships: Dict[str, Any],
    ) -> List[str]:
        gaps: List[str] = []
        if not zoom_info_account_id:
            gaps.append("Org chart unavailable until zoomInfoAccountId is present.")
            if enable_probes:
                gaps.append("Optional internal signals were not collected because zoomInfoAccountId is missing.")
        elif not org_people:
            gaps.append("Org chart coverage is present but sparse for this account.")

        if not relationships.get("warm_intro_path_available"):
            # Presence of no route is a fact, not a permanent truth.
            pass
        return gaps
