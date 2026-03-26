#!/usr/bin/env python3
"""Transition-focused ProConnect payload assembly for local script testing."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - import style depends on entrypoint
    from .proconnect_client import ProConnectClient
    from .proconnect_lookup_logic import (
        DEPARTMENT_TO_SFDC_FUNCTIONS,
        build_account_summary,
        exact_name_equals,
        full_person_name,
        get_zoom_info_account_id,
        resolve_company_and_account,
        same_first_last_name,
        top_person_candidates,
    )
except ImportError:  # pragma: no cover
    from proconnect_client import ProConnectClient
    from proconnect_lookup_logic import (
        DEPARTMENT_TO_SFDC_FUNCTIONS,
        build_account_summary,
        exact_name_equals,
        full_person_name,
        get_zoom_info_account_id,
        resolve_company_and_account,
        same_first_last_name,
        top_person_candidates,
    )

ACCOUNT_PROBE_ENDPOINTS = [
    "/api/Intent",
    "/api/Scoop",
]

SOURCE_PRIORITY = {
    "to_key_buyers": 100,
    "to_account_roles": 95,
    "to_org_chart_executive": 90,
    "to_org_chart_department": 85,
    "from_key_buyers": 88,
    "from_account_roles": 84,
    "person_search": 80,
    "to_probe": 75,
    "from_probe": 70,
}

STAGE_SCORE_MAP = {
    "closed - won": 1.0,
    "opportunity qualified": 0.93,
    "client negotiation / review": 0.9,
    "proposal": 0.87,
    "prop appr": 0.85,
    "potential opportunity identified": 0.74,
    "closed - lost": 0.2,
}


def load_research_inputs(path: Optional[str]) -> Dict[str, Any]:
    defaults = {
        "provided_name": None,
        "provided_role": None,
        "potential_service_needs": None,
        "simulated_research_datapoint": None,
    }
    if not path:
        return defaults

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("research-inputs-file must contain a JSON object.")

    aliases = {
        "provided_name": ["provided_name", "providedName", "Provided Name", "ProvidedName"],
        "provided_role": ["provided_role", "providedRole", "Provided Role", "ProvidedRole"],
        "potential_service_needs": [
            "potential_service_needs",
            "potentialServiceNeeds",
            "Potential Service Needs",
            "PotentialServiceNeeds",
        ],
        "simulated_research_datapoint": [
            "simulated_research_datapoint",
            "simulatedResearchDatapoint",
            "Data Point Simulated From Research",
            "data_point_simulated_from_research",
        ],
    }

    result = dict(defaults)
    for normalized_key, candidate_keys in aliases.items():
        for key in candidate_keys:
            if key in payload:
                result[normalized_key] = payload[key]
                break
    return result


def run_stakeholder_case(
    client: ProConnectClient,
    person: str,
    from_company: str,
    to_company: str,
    department_hint: Optional[str] = None,
    from_account_id_override: Optional[str] = None,
    to_account_id_override: Optional[str] = None,
    research_inputs: Optional[Dict[str, Any]] = None,
    enable_probes: bool = True,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []

    normalized_research_inputs = normalize_research_inputs(research_inputs)
    transition_payload = default_transition_payload(
        person=person,
        from_company=from_company,
        to_company=to_company,
        research_inputs=normalized_research_inputs,
    )

    to_result = resolve_account_context(
        client=client,
        company_name=to_company,
        key_person_name=person,
        account_id_override=to_account_id_override,
        label="To company",
        required=True,
    )
    checks.extend(to_result["checks"])
    warnings.extend(to_result["warnings"])
    errors.extend(to_result["errors"])

    from_result = resolve_account_context(
        client=client,
        company_name=from_company,
        key_person_name=person,
        account_id_override=from_account_id_override,
        label="From company",
        required=False,
    )
    checks.extend(from_result["checks"])
    warnings.extend(from_result["warnings"])

    to_account = to_result["account"]
    from_account = from_result["account"]
    to_summary = build_account_summary(to_account) if to_account else None
    from_summary = build_account_summary(from_account) if from_account else None

    transition_payload["movement_event"].update(
        {
            "from_account_id": first_non_empty((from_account or {}), ["id"]),
            "to_account_id": first_non_empty((to_account or {}), ["id"]),
            "from_account_resolved": bool(from_account),
            "to_account_resolved": bool(to_account),
        }
    )

    if not to_account:
        errors.append("No destination account context resolved.")
        status = derive_transition_status(
            checks=checks,
            errors=errors,
            warnings=warnings,
            auth_failure=to_result["auth_failure"],
            destination_core_missing=["account_context", "opportunities", "key_buyers", "org_chart", "projects"],
        )
        return {
            "status": status,
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
            "to_company_resolution": to_result["resolution"],
            "from_company_resolution": from_result["resolution"],
            "person_resolution": {
                "status": "not_found",
                "match_source": None,
                "matched_person": None,
                "candidate_suggestions": [],
            },
            "to_account_summary": to_summary,
            "from_account_summary": from_summary,
            "account_summary": to_summary,
            "company_resolution": to_result["resolution"],
            "transition_payload": transition_payload,
            "stakeholder_payload": transition_payload,
        }

    to_account_id = str(to_account.get("id") or "")
    from_account_id = str((from_account or {}).get("id") or "")

    to_org_chart_items, to_org_chart_people, to_org_warnings = collect_org_chart_people(
        client=client,
        zoom_info_account_id=get_zoom_info_account_id(to_account),
        department_hint=department_hint,
    )
    warnings.extend(to_org_warnings)
    checks.append(
        {
            "check": "To org chart collection",
            "status": "PASS" if to_org_chart_items else "WARN",
            "http": "-",
            "details": f"People collected: {len(to_org_chart_items)}",
        }
    )

    to_probe_payloads: List[Dict[str, Any]] = []
    from_probe_payloads: List[Dict[str, Any]] = []
    if enable_probes:
        to_probe_payloads, to_probe_warnings = probe_additional_endpoints(
            client=client,
            account_id=to_account_id or None,
            zoom_info_account_id=get_zoom_info_account_id(to_account),
        )
        warnings.extend(to_probe_warnings)
        if from_account:
            from_probe_payloads, from_probe_warnings = probe_additional_endpoints(
                client=client,
                account_id=from_account_id or None,
                zoom_info_account_id=get_zoom_info_account_id(from_account),
            )
            warnings.extend(from_probe_warnings)

    to_account_context = build_account_context(to_account)
    to_projects = build_projects_section(to_account)
    to_opportunities = build_opportunities_section(to_account)
    to_key_buyers = build_key_buyers_section(to_account)
    to_technologies = extract_technologies(to_account, to_probe_payloads)

    if to_technologies:
        checks.append(
            {
                "check": "To technologies",
                "status": "PASS",
                "http": "-",
                "details": f"Technology records: {len(to_technologies)}",
            }
        )
    else:
        warnings.append("Destination company returned no technologies.")
        checks.append(
            {
                "check": "To technologies",
                "status": "WARN",
                "http": "-",
                "details": "No technologies found; returned empty list.",
            }
        )

    destination_core_missing = missing_destination_core_sections(
        account_context=to_account_context,
        projects=to_projects,
        opportunities=to_opportunities,
        key_buyers=to_key_buyers,
        org_chart_items=to_org_chart_items,
    )
    checks.append(
        {
            "check": "Destination core completeness",
            "status": "PASS" if not destination_core_missing else "FAIL",
            "http": "-",
            "details": "All required sections present"
            if not destination_core_missing
            else f"Missing: {', '.join(destination_core_missing)}",
        }
    )
    if destination_core_missing:
        errors.append(f"Destination core sections missing: {', '.join(destination_core_missing)}")

    from_context = build_from_company_context_lite(from_account, probe_payloads=from_probe_payloads)
    if from_account:
        checks.append(
            {
                "check": "From company lite context",
                "status": "PASS",
                "http": "-",
                "details": f"Resolved account: {from_account.get('name', 'unknown')}",
            }
        )
    else:
        warnings.append("From company could not be fully resolved; lite context is empty.")
        checks.append(
            {
                "check": "From company lite context",
                "status": "WARN",
                "http": "-",
                "details": "From company unresolved.",
            }
        )

    person_search_response = client.search_prospects(person)
    person_search_candidates = extract_person_search_candidates(person_search_response.get("data"))
    if person_search_response.get("success"):
        checks.append(
            {
                "check": "Person prospects search",
                "status": "PASS",
                "http": person_search_response.get("status_code"),
                "details": f"Candidates: {len(person_search_candidates)}",
            }
        )
    else:
        warnings.append(
            f"Person search failed with status {person_search_response.get('status_code')}; using account-derived pools only."
        )
        checks.append(
            {
                "check": "Person prospects search",
                "status": "WARN",
                "http": person_search_response.get("status_code"),
                "details": person_search_response.get("error") or "Search failed.",
            }
        )

    to_people = build_people_candidates_for_account(
        account=to_account,
        company_scope="to",
        account_id=to_account_id,
        org_chart_people=to_org_chart_people,
        probe_payloads=to_probe_payloads,
    )
    from_people = build_people_candidates_for_account(
        account=from_account,
        company_scope="from",
        account_id=from_account_id,
        org_chart_people=[],
        probe_payloads=from_probe_payloads,
    )
    search_people = normalize_person_search_candidates(
        person_search_candidates,
        to_account_id=to_account_id,
        from_account_id=from_account_id,
    )

    candidate_people = dedupe_transition_people(to_people + from_people + search_people)
    to_title_hints = collect_person_title_hints(to_account, person)
    from_title_hints = collect_person_title_hints(from_account, person)
    person_resolution = resolve_person_transition(
        person_name=person,
        candidates=candidate_people,
        to_account_id=to_account_id,
        from_account_id=from_account_id,
        to_title_hints=to_title_hints,
        from_title_hints=from_title_hints,
    )

    person_resolution = enrich_person_resolution_from_prospect_detail(
        client=client,
        person_name=person,
        person_resolution=person_resolution,
        candidate_people=candidate_people,
        warnings=warnings,
    )

    person_profile = build_person_profile_transition(
        person_requested=person,
        person_resolution=person_resolution,
        candidate_people=candidate_people,
        to_account=to_account,
        from_account=from_account,
        warnings=warnings,
    )

    if person_profile.get("match_status") == "matched":
        checks.append(
            {
                "check": "Exact person match",
                "status": "PASS",
                "http": "-",
                "details": f"Matched via {person_resolution.get('match_source')}",
            }
        )
    else:
        checks.append(
            {
                "check": "Exact person match",
                "status": "WARN",
                "http": "-",
                "details": "Exact company-anchored match not found; candidate suggestions returned.",
            }
        )

    ranked_top_10 = rank_destination_opportunities(
        opportunities=to_opportunities.get("items", []),
        person_name=person,
    )

    movement_evidence = {
        "person_search": {
            "status_code": person_search_response.get("status_code"),
            "success": person_search_response.get("success"),
            "candidate_count": len(person_search_candidates),
            "exact_match_count": person_resolution.get("exact_match_count", 0),
        },
        "person_match": {
            "status": person_profile.get("match_status"),
            "source": person_resolution.get("match_source"),
            "matched_name": first_non_empty(person_profile.get("matched_person") or {}, ["name"]),
            "company_scope": person_resolution.get("match_scope"),
            "direct_person_evidence": person_profile.get("direct_person_evidence"),
            "person_claim_allowed": person_profile.get("person_claim_allowed"),
            "claim_policy_note": person_profile.get("claim_policy_note"),
        },
        "ranked_opportunities_top10": ranked_top_10,
        "transition_summary": {
            "from_worked_before": from_context.get("worked_before"),
            "to_worked_before": to_account_context.get("worked_before"),
            "from_account_resolved": bool(from_account),
            "to_account_resolved": True,
        },
    }

    optional_sections = {
        "to_company": extract_optional_sections(to_account, to_probe_payloads),
        "from_company": extract_optional_sections(from_account, from_probe_payloads),
    }

    transition_payload.update(
        {
            "person_profile": person_profile,
            "from_company_context": from_context,
            "to_company_context": {
                "account_context": to_account_context,
                "account_team": build_account_team_section(to_account),
                "work_by_solution": build_work_by_solution_section(to_account),
                "projects": to_projects,
                "opportunities": to_opportunities,
                "key_buyers": to_key_buyers,
                "org_chart": {"items": to_org_chart_items},
                "technologies": {"items": to_technologies},
                "relationship_network": build_relationship_network_section(
                    to_account,
                    probe_payloads=to_probe_payloads,
                ),
            },
            "movement_evidence": movement_evidence,
            "optional_sections": optional_sections,
        }
    )

    transition_payload["provenance"] = build_transition_provenance(
        transition_payload=transition_payload,
        probe_payloads=to_probe_payloads + from_probe_payloads,
    )
    transition_payload["confidence"] = build_transition_confidence(
        transition_payload=transition_payload,
    )

    status = derive_transition_status(
        checks=checks,
        errors=errors,
        warnings=warnings,
        auth_failure=to_result["auth_failure"],
        destination_core_missing=destination_core_missing,
    )

    return {
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "to_company_resolution": to_result["resolution"],
        "from_company_resolution": from_result["resolution"],
        "person_resolution": {
            "status": person_profile.get("match_status"),
            "match_source": person_resolution.get("match_source"),
            "match_scope": person_resolution.get("match_scope"),
            "match_strategy": person_resolution.get("match_strategy"),
            "loose_match_count": person_resolution.get("loose_match_count"),
            "matched_person": person_profile.get("matched_person"),
            "candidate_suggestions": person_profile.get("candidate_suggestions"),
            "direct_person_evidence": person_profile.get("direct_person_evidence"),
            "person_claim_allowed": person_profile.get("person_claim_allowed"),
        },
        "to_account_summary": to_summary,
        "from_account_summary": from_summary,
        "account_summary": to_summary,
        "company_resolution": to_result["resolution"],
        "transition_payload": transition_payload,
        "stakeholder_payload": transition_payload,
    }


def resolve_account_context(
    client: ProConnectClient,
    company_name: str,
    key_person_name: Optional[str],
    account_id_override: Optional[str],
    label: str,
    required: bool,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []
    account: Optional[Dict[str, Any]] = None
    auth_failure = False

    failure_check_status = "FAIL" if required else "WARN"

    if account_id_override and is_placeholder_account_id(str(account_id_override)):
        warnings.append(
            f"{label} account-id override '{account_id_override}' looks like a placeholder; falling back to company search."
        )
        account_id_override = None

    if account_id_override:
        response = client.get_account_by_id(str(account_id_override))
        status_code = response.get("status_code")
        auth_failure = status_code in {401, 403}
        resolution = {
            "query": company_name,
            "search_status_code": None,
            "search_success": None,
            "candidate_count": 0,
            "candidates": [],
            "selected_candidate": {"accountId": account_id_override},
            "selected_score": None,
            "account_fetch_status_code": status_code,
            "resolved_account": bool(response.get("success")),
            "account_id_override": True,
        }
        if response.get("success") and isinstance(response.get("data"), dict):
            account = response["data"]
            checks.append(
                {
                    "check": f"{label} account retrieval",
                    "status": "PASS",
                    "http": status_code,
                    "details": f"Loaded account id {account_id_override}",
                }
            )
        else:
            checks.append(
                {
                    "check": f"{label} account retrieval",
                    "status": failure_check_status,
                    "http": status_code,
                    "details": response.get("error") or "Account retrieval failed.",
                }
            )
            message = f"{label} account override failed."
            if required:
                errors.append(message)
            else:
                warnings.append(message)
        return {
            "resolution": resolution,
            "account": account,
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
            "auth_failure": auth_failure,
        }

    resolution, account, resolution_errors = resolve_company_and_account(
        client=client,
        company_name=company_name,
        key_person_name=key_person_name,
    )

    search_status = resolution.get("search_status_code")
    fetch_status = resolution.get("account_fetch_status_code")
    if search_status in {401, 403} or fetch_status in {401, 403}:
        auth_failure = True

    if resolution.get("search_success"):
        checks.append(
            {
                "check": f"{label} prospects search",
                "status": "PASS",
                "http": search_status,
                "details": f"Candidates: {resolution.get('candidate_count', 0)}",
            }
        )
    else:
        checks.append(
            {
                "check": f"{label} prospects search",
                "status": failure_check_status,
                "http": search_status,
                "details": "Search failed.",
            }
        )

    if account:
        checks.append(
            {
                "check": f"{label} account retrieval",
                "status": "PASS",
                "http": fetch_status,
                "details": f"Resolved account: {account.get('name', 'unknown')}",
            }
        )
    else:
        checks.append(
            {
                "check": f"{label} account retrieval",
                "status": failure_check_status,
                "http": fetch_status,
                "details": "No account resolved from company search.",
            }
        )

    for error in resolution_errors:
        if required:
            errors.append(error)
        else:
            warnings.append(error)

    if not account:
        if required:
            errors.append(f"{label} account resolution returned no account.")
        else:
            warnings.append(f"{label} account resolution returned no account.")

    return {
        "resolution": resolution,
        "account": account,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "auth_failure": auth_failure,
    }


def derive_transition_status(
    checks: List[Dict[str, Any]],
    errors: List[str],
    warnings: List[str],
    auth_failure: bool,
    destination_core_missing: List[str],
) -> str:
    if auth_failure:
        return "FAIL"
    if destination_core_missing:
        return "FAIL"
    if errors or any(check.get("status") == "FAIL" for check in checks):
        return "FAIL"
    if warnings or any(check.get("status") == "WARN" for check in checks):
        return "WARN"
    return "PASS"


def default_transition_payload(
    person: str,
    from_company: str,
    to_company: str,
    research_inputs: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "movement_event": {
            "person_full_name": person,
            "from_company": from_company,
            "to_company": to_company,
            "from_account_id": None,
            "to_account_id": None,
            "from_account_resolved": False,
            "to_account_resolved": False,
            "move_date": None,
            "trigger_id": None,
        },
        "person_profile": {
            "person_requested": person,
            "match_status": "not_found",
            "person_unverified": True,
            "matched_person": None,
            "last_updated": None,
            "title_salesforce": None,
            "title_external": None,
            "location": None,
            "in_salesforce": None,
            "protiviti_alumni": None,
            "contact_at_robert_half": None,
            "function": None,
            "level": None,
            "email": None,
            "phone": None,
            "linkedin_url": None,
            "photo_url": None,
            "past_job_experience": [],
            "education": [],
            "candidate_suggestions": [],
            "direct_person_evidence": False,
            "person_claim_allowed": False,
            "claim_policy_note": "No direct person-level evidence available; account-level claim only.",
        },
        "from_company_context": {
            "account_header": {
                "account_id": None,
                "company_name": None,
                "industry": None,
                "website": None,
                "ticker": None,
                "zoom_info_account_id": None,
            },
            "account_team": {
                "account_pmo": None,
                "account_mdd": None,
                "account_executive": None,
            },
            "worked_before": False,
            "historical_solution_footprint": {
                "total_projects": 0,
                "total_all_opportunities": 0,
                "total_open_opportunities": 0,
                "solutions_list_5y": [],
                "most_recent_engagement_date": None,
            },
            "top_key_buyers": [],
            "prior_relationship_indicators": {
                "key_buyer_count": 0,
                "has_protiviti_alumni": False,
                "has_connected_colleague": False,
                "warm_intro_path_available": False,
                "relationship_routes": [],
                "notes": [],
            },
            "relationship_network": {
                "protiviti_alumni": {"items": []},
                "connected_colleagues": {"items": []},
            },
        },
        "to_company_context": {
            "account_context": {
                "account_id": None,
                "company_name": None,
                "industry": None,
                "website": None,
                "ticker": None,
                "zoom_info_account_id": None,
                "worked_before": False,
                "last_updated": None,
                "headquarters": None,
                "sub_industry": None,
                "annual_revenue": None,
                "number_of_employees": None,
                "ipo_date": None,
                "account_type": None,
                "short_name": None,
                "hub_id": None,
                "ownership": None,
                "ranking": None,
                "company_photo_url": None,
                "sfdc_account_ids": [],
                "is_client": None,
                "is_msa": None,
                "is_sanction": None,
                "is_external_only": None,
                "parent_company": None,
                "child_companies": [],
                "account_activity_status": None,
                "company_summary_raw": None,
                "company_summary_concise": None,
            },
            "account_team": {
                "account_pmo": None,
                "account_mdd": None,
                "account_executive": None,
            },
            "work_by_solution": {
                "total_projects": 0,
                "solutions_list": [],
                "time_period_label": None,
            },
            "projects": {"items": [], "total_projects": 0, "solutions_list": []},
            "opportunities": {"items": []},
            "key_buyers": {"items": []},
            "org_chart": {"items": []},
            "technologies": {"items": []},
            "relationship_network": {
                "protiviti_alumni": {"items": []},
                "connected_colleagues": {"items": []},
                "warm_intro_path_available": False,
                "relationship_routes": [],
            },
        },
        "movement_evidence": {
            "person_search": {},
            "person_match": {},
            "ranked_opportunities_top10": [],
            "transition_summary": {},
        },
        "optional_sections": {
            "to_company": {
                "competitors": [],
                "partners": [],
                "social_urls": [],
                "marketing_signals": [],
                "internal_connections": [],
                "intent_signals": [],
                "recent_activity": [],
                "probe_endpoint_statuses": [],
            },
            "from_company": {
                "competitors": [],
                "partners": [],
                "social_urls": [],
                "marketing_signals": [],
                "internal_connections": [],
                "intent_signals": [],
                "recent_activity": [],
                "probe_endpoint_statuses": [],
            },
        },
        "research_inputs": research_inputs,
        "provenance": {},
        "confidence": {},
    }


def build_child_company_rows(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key in ["childCompanies", "childCompany", "children", "parentChildAccounts"]:
        value = account.get(key)
        if isinstance(value, dict):
            value = [value]
        for item in to_list_dicts(value):
            company_name = first_non_empty(item, ["name", "companyName"])
            if not company_name:
                continue
            rows.append(
                {
                    "account_id": first_non_empty(item, ["id", "accountId"]),
                    "company_name": company_name,
                }
            )
    return dedupe_simple_records(rows, keys=["account_id", "company_name"])


def derive_account_activity_status(account: Dict[str, Any]) -> str:
    open_opportunities = to_int(account.get("numberOfOpenOpportunity"))
    if open_opportunities is None:
        open_opportunities = len(to_list_dicts(account.get("openOpportunity")))

    active_project_statuses = {
        "active",
        "open",
        "ongoing",
        "in progress",
        "pipeline",
        "proposal",
    }
    has_active_projects = False
    for project in to_list_dicts(account.get("project")):
        status = normalize_text(str(first_non_empty(project, ["projectStatus"]) or ""))
        if status in active_project_statuses:
            has_active_projects = True
            break

    if (open_opportunities or 0) > 0 or has_active_projects:
        return "active"

    historical_projects = to_int(account.get("numberOfProject"))
    if historical_projects is None:
        historical_projects = len(to_list_dicts(account.get("project")))
    if (historical_projects or 0) > 0 or (to_int(account.get("numberOfAllOpportunity")) or 0) > 0:
        return "dormant"

    return "unknown"


def build_account_team_section(account: Optional[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    defaults = {
        "account_pmo": None,
        "account_mdd": None,
        "account_executive": None,
    }
    if not isinstance(account, dict):
        return defaults

    output = dict(defaults)
    role_map = {
        "accountPMO": "account_pmo",
        "accountMDD": "account_mdd",
        "accountExecutive": "account_executive",
    }
    for role_key, output_key in role_map.items():
        role_value = account.get(role_key)
        if not isinstance(role_value, dict):
            continue
        role_name = full_person_name(role_value)
        if not role_name:
            continue
        output[output_key] = {
            "name": role_name,
            "title": first_non_empty(role_value, ["title"]),
            "email": first_non_empty(role_value, ["emailAddress", "principalName", "email"]),
            "linkedin_url": first_non_empty(role_value, ["linkedinUrl", "linkedInUrl"]),
        }
    return output


def build_protiviti_alumni_items(account: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(account, dict):
        return []

    rows: List[Dict[str, Any]] = []
    for item in to_list_dicts(account.get("protivitiAlumni")):
        name = full_person_name(item)
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "title": first_non_empty(item, ["title"]),
            }
        )
    return dedupe_simple_records(rows, keys=["name", "title"])


def build_connected_colleague_items(account: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(account, dict):
        return []

    rows: List[Dict[str, Any]] = []
    connected_items: List[Dict[str, Any]] = []
    connected_items.extend(to_list_dicts(account.get("connectedColleague")))
    connected_items.extend(to_list_dicts(account.get("connectedColleagues")))
    connected_items.extend(to_list_dicts(account.get("connections")))

    for item in connected_items:
        employee = item.get("employee") if isinstance(item.get("employee"), dict) else {}
        name = full_person_name(item) or full_person_name(employee) or first_non_empty(employee, ["name"])
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "employer": first_non_empty(item, ["companyName", "employer", "company"])
                or first_non_empty(employee, ["companyName", "employer", "company"]),
                "title": first_non_empty(item, ["title"]) or first_non_empty(employee, ["title"]),
                "last_connected_method": first_non_empty(
                    item,
                    ["lastConnectedMethod", "lastInteractionMethod", "lastConnectionMethod", "lastContactType"],
                ),
                "last_connected_date": first_non_empty(
                    item,
                    ["lastConnectedDate", "lastInteractionDate", "lastConnectionDate", "lastContactTime"],
                ),
                "number_of_interactions": to_int(
                    first_non_empty(item, ["numberOfInteractions", "interactionsCount", "interactionCount"])
                ),
            }
        )
    return dedupe_simple_records(rows, keys=["name", "employer", "title", "last_connected_date"])


def build_relationship_network_section(
    account: Optional[Dict[str, Any]],
    probe_payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    protiviti_alumni = build_protiviti_alumni_items(account)
    connected_colleagues = dedupe_simple_records(
        build_connected_colleague_items(account) + extract_probe_internal_connection_items(probe_payloads or []),
        keys=["name", "employer", "title", "last_connected_date"],
    )
    relationship_routes: List[str] = []
    if protiviti_alumni:
        relationship_routes.append("protiviti_alumni")
    if connected_colleagues:
        relationship_routes.append("connected_colleagues")

    return {
        "protiviti_alumni": {"items": protiviti_alumni},
        "connected_colleagues": {"items": connected_colleagues},
        "warm_intro_path_available": bool(relationship_routes),
        "relationship_routes": relationship_routes,
    }


def latest_engagement_date(account: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(account, dict):
        return None

    candidates: List[Tuple[datetime, str]] = []
    sources = [
        ("project", ["endedDate", "openDate"]),
        ("allOpportunity", ["opportunityCloseDate", "closeDate", "opportunityCreatedDate", "createdDate"]),
        ("openOpportunity", ["opportunityCloseDate", "closeDate", "opportunityCreatedDate", "createdDate"]),
        ("keyBuyers", ["lastOpportunityWonDate", "lastWinDate"]),
    ]

    for container_key, date_keys in sources:
        for item in to_list_dicts(account.get(container_key)):
            for date_key in date_keys:
                raw_value = first_non_empty(item, [date_key])
                if not raw_value:
                    continue
                parsed = parse_iso_datetime(str(raw_value))
                if parsed:
                    candidates.append((parsed, str(raw_value)))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def build_work_by_solution_section(account: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(account, dict):
        return {
            "total_projects": 0,
            "solutions_list": [],
            "time_period_label": None,
        }

    projects = build_projects_section(account)
    return {
        "total_projects": projects.get("total_projects") or 0,
        "solutions_list": projects.get("solutions_list", []),
        "time_period_label": first_non_empty(
            account,
            ["workBySolutionTimePeriod", "timePeriodLabel", "projectTimePeriodLabel"],
        ),
    }


def build_account_context(account: Dict[str, Any]) -> Dict[str, Any]:
    projects = account.get("project") if isinstance(account.get("project"), list) else []
    number_of_project = to_int(account.get("numberOfProject"))
    worked_before = bool((number_of_project and number_of_project > 0) or projects)
    raw_summary = first_non_empty(account, ["companyDescription", "description"])

    return {
        "account_id": account.get("id"),
        "company_name": account.get("name"),
        "industry": account.get("industry"),
        "website": account.get("websiteUrl"),
        "ticker": account.get("tickerSymbol"),
        "zoom_info_account_id": account.get("zoomInfoAccountId"),
        "worked_before": worked_before,
        "last_updated": first_non_empty(account, ["modifiedDate", "lastUpdated"]),
        "headquarters": account.get("headQuarters"),
        "sub_industry": account.get("subIndustry"),
        "annual_revenue": first_non_empty(account, ["annualRevenue"]),
        "number_of_employees": first_non_empty(account, ["numberOfEmployees", "employeeCount"]),
        "ipo_date": account.get("ipoDate"),
        "account_type": account.get("accountType"),
        "short_name": account.get("shortName"),
        "hub_id": account.get("hubId"),
        "ownership": account.get("ownership"),
        "ranking": account.get("ranking"),
        "company_photo_url": account.get("companyPhotoUrl"),
        "sfdc_account_ids": to_list(account.get("sfdcAccountIds")),
        "is_client": to_bool(account.get("isClient")),
        "is_msa": to_bool(account.get("isMSA")),
        "is_sanction": to_bool(account.get("isSanction")),
        "is_external_only": to_bool(account.get("isExternalOnly")),
        "parent_company": first_non_empty(account, ["parentCompany", "parentAccountName"]),
        "child_companies": build_child_company_rows(account),
        "account_activity_status": derive_account_activity_status(account),
        "company_summary_raw": raw_summary,
        "company_summary_concise": concise_summary(raw_summary),
    }


def build_projects_section(account: Dict[str, Any]) -> Dict[str, Any]:
    raw_projects = account.get("project")
    if not isinstance(raw_projects, list):
        raw_projects = []

    items: List[Dict[str, Any]] = []
    solutions = set()
    for project in raw_projects:
        if not isinstance(project, dict):
            continue
        solution = first_non_empty(project, ["solution"])
        if solution:
            solutions.add(solution)
        items.append(
            {
                "project_id": first_non_empty(project, ["projectId", "id", "budgetKey"]),
                "project_name": first_non_empty(project, ["name", "projectName", "budgetKey"]),
                "year_ended_or_status": first_non_empty(project, ["endedDate", "projectStatus", "yearEnded"]),
                "open_date": first_non_empty(project, ["openDate"]),
                "ended_date": first_non_empty(project, ["endedDate"]),
                "project_status": first_non_empty(project, ["projectStatus"]),
                "solution": solution,
                "emd": first_non_empty(project, ["engagementManagingDirector", "emd"]),
                "em": first_non_empty(project, ["engagementManager", "em"]),
                "primary_key_buyer": first_non_empty(project, ["primaryKeyBuyer"]),
                "primary_key_buyer_id": first_non_empty(project, ["primaryKeyBuyerId"]),
                "is_confidential": to_bool(first_non_empty(project, ["isConfidential"])),
            }
        )

    total_projects = to_int(account.get("numberOfProject"))
    if total_projects is None:
        total_projects = len(items)

    if not solutions:
        for opp_key in ["allOpportunity", "openOpportunity"]:
            for opp in to_list_dicts(account.get(opp_key)):
                solution = first_non_empty(opp, ["solution"])
                if solution:
                    solutions.add(solution)

    return {
        "items": items,
        "total_projects": total_projects,
        "solutions_list": sorted(solutions),
    }


def build_opportunities_section(account: Dict[str, Any]) -> Dict[str, Any]:
    opportunities = account.get("allOpportunity")
    if not isinstance(opportunities, list):
        opportunities = account.get("openOpportunity")
    opportunities = to_list_dicts(opportunities)

    items: List[Dict[str, Any]] = []
    for opp in opportunities:
        items.append(
            {
                "opportunity_id": first_non_empty(opp, ["opportunityId", "id"]),
                "opportunity_key": first_non_empty(opp, ["opportunityKey"]),
                "opportunity": first_non_empty(opp, ["name", "opportunity", "opportunityName"]),
                "close_date": first_non_empty(opp, ["opportunityCloseDate", "closeDate"]),
                "created_date": first_non_empty(opp, ["opportunityCreatedDate", "createdDate"]),
                "md_d": first_non_empty(opp, ["opportunityManagingDirector", "md", "director"]),
                "primary_key_buyer": first_non_empty(opp, ["primaryKeyBuyer"]),
                "primary_key_buyer_id": first_non_empty(opp, ["primaryKeyBuyerId"]),
                "solution": first_non_empty(opp, ["solution"]),
                "solution_segment": first_non_empty(opp, ["solutionSegment"]),
                "service_name": first_non_empty(opp, ["serviceOffering", "serviceName"]),
                "stage": first_non_empty(opp, ["opportunityStage", "stage"]),
                "em": first_non_empty(opp, ["engagementManager"]),
                "is_confidential": to_bool(first_non_empty(opp, ["isConfidential"])),
                "win_loss_explanation": first_non_empty(opp, ["winLossExplanation"]),
                "reason_for_loss": first_non_empty(opp, ["reasonForLoss"]),
            }
        )

    return {"items": items}


def build_key_buyers_section(account: Dict[str, Any]) -> Dict[str, Any]:
    key_buyers = to_list_dicts(account.get("keyBuyers"))

    items: List[Dict[str, Any]] = []
    for buyer in key_buyers:
        items.append(
            {
                "name": full_person_name(buyer),
                "title": first_non_empty(buyer, ["title"]),
                "email_address": first_non_empty(buyer, ["emailAddress", "email"]),
                "linkedin_url": first_non_empty(buyer, ["linkedinUrl", "linkedInUrl"]),
                "wins_5y": to_int(first_non_empty(buyer, ["numberOfWins", "wins", "winCount"])),
                "last_opportunity_won_date": first_non_empty(
                    buyer,
                    ["lastOpportunityWonDate", "lastWinDate"],
                ),
                "last_opportunity_stage": first_non_empty(buyer, ["lastOpportunityStage"]),
                "function": first_non_empty(buyer, ["function"]),
                "close_won_opportunities": to_list_dicts(
                    first_non_empty(buyer, ["closeWonOpps", "closeWonOpportunities"])
                ),
            }
        )

    return {
        "items": items,
    }


def build_from_company_context_lite(
    account: Optional[Dict[str, Any]],
    probe_payloads: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not account:
        return default_transition_payload("", "", "", normalize_research_inputs(None))["from_company_context"]

    account_context = build_account_context(account)
    projects = build_projects_section(account)
    opportunities = build_opportunities_section(account)
    key_buyers = build_key_buyers_section(account)

    ranked_buyers = sorted(
        key_buyers.get("items", []),
        key=lambda item: (to_int(item.get("wins_5y")) or 0, str(item.get("name") or "")),
        reverse=True,
    )
    relationship_network = build_relationship_network_section(account, probe_payloads=probe_payloads or [])

    return {
        "account_header": {
            "account_id": account_context.get("account_id"),
            "company_name": account_context.get("company_name"),
            "industry": account_context.get("industry"),
            "website": account_context.get("website"),
            "ticker": account_context.get("ticker"),
            "zoom_info_account_id": account_context.get("zoom_info_account_id"),
        },
        "account_team": build_account_team_section(account),
        "worked_before": bool(account_context.get("worked_before")),
        "historical_solution_footprint": {
            "total_projects": projects.get("total_projects") or 0,
            "total_all_opportunities": to_int(account.get("numberOfAllOpportunity")) or len(opportunities.get("items", [])),
            "total_open_opportunities": to_int(account.get("numberOfOpenOpportunity"))
            or len(to_list_dicts(account.get("openOpportunity"))),
            "solutions_list_5y": projects.get("solutions_list", []),
            "most_recent_engagement_date": latest_engagement_date(account),
        },
        "top_key_buyers": ranked_buyers[:5],
        "prior_relationship_indicators": {
            "key_buyer_count": len(key_buyers.get("items", [])),
            "has_protiviti_alumni": bool((relationship_network.get("protiviti_alumni") or {}).get("items")),
            "has_connected_colleague": bool((relationship_network.get("connected_colleagues") or {}).get("items")),
            "warm_intro_path_available": relationship_network.get("warm_intro_path_available", False),
            "relationship_routes": relationship_network.get("relationship_routes", []),
            "notes": [
                "Source company context is lightweight by design for transition analysis anchor.",
            ],
        },
        "relationship_network": {
            "protiviti_alumni": relationship_network.get("protiviti_alumni"),
            "connected_colleagues": relationship_network.get("connected_colleagues"),
        },
    }


def build_people_candidates_for_account(
    account: Optional[Dict[str, Any]],
    company_scope: str,
    account_id: str,
    org_chart_people: List[Dict[str, Any]],
    probe_payloads: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not account:
        return []

    key_buyer_people = annotate_people_scope(
        people=to_people_from_key_buyers(account.get("keyBuyers")),
        company_scope=company_scope,
        linked_account_id=account_id,
        linked_company_name=str(account.get("name") or ""),
        source_prefix=f"{company_scope}_",
    )

    role_people = annotate_people_scope(
        people=to_people_from_account_roles(account),
        company_scope=company_scope,
        linked_account_id=account_id,
        linked_company_name=str(account.get("name") or ""),
        source_prefix=f"{company_scope}_",
    )

    chart_people = annotate_people_scope(
        people=org_chart_people,
        company_scope=company_scope,
        linked_account_id=account_id,
        linked_company_name=str(account.get("name") or ""),
        source_prefix=f"{company_scope}_",
    )

    probe_people = annotate_people_scope(
        people=extract_probe_people(probe_payloads),
        company_scope=company_scope,
        linked_account_id=account_id,
        linked_company_name=str(account.get("name") or ""),
        source_prefix=f"{company_scope}_",
    )

    return key_buyer_people + role_people + chart_people + probe_people


def annotate_people_scope(
    people: List[Dict[str, Any]],
    company_scope: str,
    linked_account_id: str,
    linked_company_name: str,
    source_prefix: Optional[str] = None,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        candidate = dict(person)
        source_value = str(candidate.get("_source") or "unknown")
        if source_prefix and not source_value.startswith(source_prefix):
            source_value = f"{source_prefix}{source_value}"
        candidate["_source"] = source_value
        candidate["_company_scope"] = company_scope
        candidate["linked_account_id"] = linked_account_id
        candidate["linked_company_name"] = linked_company_name
        output.append(candidate)
    return output


def normalize_person_search_candidates(
    candidates: List[Dict[str, Any]],
    to_account_id: str,
    from_account_id: str,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for candidate in candidates:
        account_id = str(candidate.get("accountId") or "")
        if account_id and to_account_id and account_id == to_account_id:
            scope = "to"
        elif account_id and from_account_id and account_id == from_account_id:
            scope = "from"
        else:
            scope = "unknown"

        output.append(
            {
                "id": candidate.get("contactId") or candidate.get("id"),
                "name": candidate.get("name"),
                "title": candidate.get("title"),
                "emailAddress": candidate.get("emailAddress"),
                "linkedinUrl": candidate.get("linkedinUrl"),
                "location": candidate.get("location"),
                "isInSalesforce": candidate.get("isInSalesforce"),
                "isProtivitiAlumni": candidate.get("isProtivitiAlumni"),
                "hasRoberthalfContact": candidate.get("hasRoberthalfContact"),
                "phone": candidate.get("phone"),
                "pastJobExperience": candidate.get("pastJobExperience"),
                "education": candidate.get("education"),
                "function": candidate.get("function"),
                "level": candidate.get("level"),
                "photoUrl": candidate.get("photoUrl"),
                "lastUpdated": candidate.get("lastUpdated"),
                "_source": "person_search",
                "_company_scope": scope,
                "linked_account_id": account_id,
                "linked_company_name": candidate.get("companyName"),
            }
        )
    return output


def resolve_person_transition(
    person_name: str,
    candidates: List[Dict[str, Any]],
    to_account_id: str,
    from_account_id: str,
    to_title_hints: Optional[List[str]] = None,
    from_title_hints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    exact_matches = [candidate for candidate in candidates if exact_name_equals(person_name, full_person_name(candidate))]
    loose_matches = [
        candidate
        for candidate in candidates
        if same_first_last_name(person_name, full_person_name(candidate))
    ]

    def _match_payload(
        *,
        matches: List[Dict[str, Any]],
        scope: Optional[str],
        title_hints: List[str],
        strategy: str,
    ) -> Dict[str, Any]:
        selected = merge_person_candidates(
            candidates=matches,
            selected=select_best_candidate(matches, title_hints=title_hints),
            title_hints=title_hints,
        )
        return {
            "status": "matched",
            "match_source": selected.get("_source"),
            "match_scope": scope or selected.get("_company_scope") or "unknown",
            "matched": selected,
            "exact_match_count": len(exact_matches),
            "loose_match_count": len(loose_matches),
            "match_strategy": strategy,
        }

    if not exact_matches:
        to_loose_matches = [
            item for item in loose_matches if str(item.get("linked_account_id") or "") == to_account_id
        ]
        if len(to_loose_matches) == 1:
            return _match_payload(
                matches=to_loose_matches,
                scope="to",
                title_hints=to_title_hints or [],
                strategy="first_last_name_to_account",
            )

        from_loose_matches = [
            item for item in loose_matches if str(item.get("linked_account_id") or "") == from_account_id
        ]
        if len(from_loose_matches) == 1:
            return _match_payload(
                matches=from_loose_matches,
                scope="from",
                title_hints=from_title_hints or [],
                strategy="first_last_name_from_account",
            )

        if len(loose_matches) == 1:
            return _match_payload(
                matches=loose_matches,
                scope=str(loose_matches[0].get("_company_scope") or "unknown"),
                title_hints=[],
                strategy="first_last_name_global",
            )

        return {
            "status": "not_found",
            "match_source": None,
            "match_scope": None,
            "matched": None,
            "exact_match_count": 0,
            "loose_match_count": len(loose_matches),
            "match_strategy": None,
        }

    to_matches = [item for item in exact_matches if str(item.get("linked_account_id") or "") == to_account_id]
    if to_matches:
        return _match_payload(
            matches=to_matches,
            scope="to",
            title_hints=to_title_hints or [],
            strategy="exact_name_to_account",
        )

    from_matches = [item for item in exact_matches if str(item.get("linked_account_id") or "") == from_account_id]
    if from_matches:
        return _match_payload(
            matches=from_matches,
            scope="from",
            title_hints=from_title_hints or [],
            strategy="exact_name_from_account",
        )

    if len(exact_matches) == 1:
        return _match_payload(
            matches=exact_matches,
            scope=str(exact_matches[0].get("_company_scope") or "unknown"),
            title_hints=[],
            strategy="exact_name_global",
        )

    return {
        "status": "ambiguous",
        "match_source": None,
        "match_scope": None,
        "matched": None,
        "exact_match_count": len(exact_matches),
        "loose_match_count": len(loose_matches),
        "match_strategy": None,
    }


def select_best_candidate(candidates: List[Dict[str, Any]], title_hints: List[str]) -> Dict[str, Any]:
    ranked = sorted(candidates, key=lambda row: candidate_sort_key(row, title_hints=title_hints), reverse=True)
    return ranked[0]


def merge_person_candidates(
    candidates: List[Dict[str, Any]],
    selected: Dict[str, Any],
    title_hints: List[str],
) -> Dict[str, Any]:
    ranked = sorted(candidates, key=lambda row: candidate_sort_key(row, title_hints=title_hints), reverse=True)
    merged = dict(selected)
    selected_source = selected.get("_source")

    for candidate in ranked:
        for key, value in candidate.items():
            if key == "_source":
                continue
            normalized_key = normalize_text(key).replace(" ", "")
            if normalized_key in {"projects", "closewonopps", "closewonopportunities", "connections"}:
                merged[key] = _merge_person_list_field(normalized_key, merged.get(key), value)
                continue
            if not should_replace_person_field(
                key=key,
                current_value=merged.get(key),
                candidate_value=value,
            ):
                continue
            merged[key] = value

    merged["_source"] = selected_source
    return merged


def _merge_person_list_field(key: str, current_value: Any, candidate_value: Any) -> List[Dict[str, Any]]:
    current_items = to_list_dicts(current_value)
    candidate_items = to_list_dicts(candidate_value)
    if not current_items:
        return candidate_items
    if not candidate_items:
        return current_items
    if len(candidate_items) > len(current_items) and len(current_items) <= 1:
        return candidate_items
    if len(current_items) > len(candidate_items) and len(candidate_items) <= 1:
        return current_items
    if key == "connections":
        identity_keys = ["name", "employee", "employeeId", "id"]
    elif key in {"closewonopps", "closewonopportunities"}:
        identity_keys = ["opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyerId", "primaryKeyBuyer"]
    else:
        identity_keys = ["projectId", "id", "name", "primaryKeyBuyerId", "primaryKeyBuyer"]
    return dedupe_simple_records(current_items + candidate_items, keys=identity_keys)


def should_replace_person_field(key: str, current_value: Any, candidate_value: Any) -> bool:
    if present(candidate_value) != "present":
        return False
    if present(current_value) != "present":
        return True

    normalized_key = normalize_text(key).replace(" ", "")
    if normalized_key in {
        "projectcount",
        "project_count",
        "numberofprojects",
        "numberofproject",
        "wincount",
        "win_count",
        "numberofwins",
        "wins",
    }:
        current_int = to_int(current_value)
        candidate_int = to_int(candidate_value)
        if candidate_int is None:
            return False
        if current_int is None:
            return True
        return candidate_int > current_int

    if normalized_key in {"projects", "closewonopps", "closewonopportunities", "connections"}:
        return len(to_list_dicts(candidate_value)) > len(to_list_dicts(current_value))

    return False


def candidate_sort_key(candidate: Dict[str, Any], title_hints: List[str]) -> Tuple[int, int, float, int, int, int, str]:
    source = str(candidate.get("_source") or "")
    base_source = source
    for prefix in ["to_", "from_"]:
        if base_source.startswith(prefix):
            base_source = base_source[len(prefix) :]
            break
    scope_rank = {"to": 3, "from": 2, "unknown": 1}.get(str(candidate.get("_company_scope") or "unknown"), 1)
    source_rank = SOURCE_PRIORITY.get(source, SOURCE_PRIORITY.get(base_source, 10))
    hint_match = 1 if title_matches_hints(first_non_empty(candidate, ["title"]), title_hints) else 0
    has_title = 1 if first_non_empty(candidate, ["title", "titleSalesforce", "titleExternal"]) else 0
    has_email = 1 if first_non_empty(candidate, ["emailAddress", "email"]) else 0
    has_linkedin = 1 if first_non_empty(candidate, ["linkedinUrl", "linkedInUrl"]) else 0
    name = str(full_person_name(candidate) or "")
    return (scope_rank, hint_match, float(source_rank), has_title, has_email, has_linkedin, name)


def collect_person_title_hints(account: Optional[Dict[str, Any]], person_name: str) -> List[str]:
    if not isinstance(account, dict):
        return []

    hints: List[str] = []

    for buyer in to_list_dicts(account.get("keyBuyers")):
        if exact_name_equals(person_name, full_person_name(buyer)):
            title = first_non_empty(buyer, ["title"])
            if isinstance(title, str) and title.strip():
                hints.append(title.strip())

    for role_key in ["accountPMO", "accountMDD", "accountExecutive"]:
        role = account.get(role_key)
        if not isinstance(role, dict):
            continue
        if exact_name_equals(person_name, full_person_name(role)):
            title = first_non_empty(role, ["title"])
            if isinstance(title, str) and title.strip():
                hints.append(title.strip())

    return dedupe_list(hints)


def title_matches_hints(candidate_title: Any, title_hints: List[str]) -> bool:
    if not isinstance(candidate_title, str) or not candidate_title.strip():
        return False
    if not title_hints:
        return False

    candidate_norm = normalize_text(candidate_title)
    for hint in title_hints:
        hint_norm = normalize_text(hint)
        if not hint_norm:
            continue
        if candidate_norm == hint_norm:
            return True
        if candidate_norm in hint_norm or hint_norm in candidate_norm:
            return True
    return False


def _person_reference_ids(matched: Dict[str, Any]) -> set[str]:
    ids = set()
    for key in ["id", "contactId", "personId", "prospectId", "primaryKeyBuyerId", "buyerId"]:
        value = first_non_empty(matched, [key])
        text = str(value or "").strip()
        if text:
            ids.add(text)
    return ids


def _record_matches_person_reference(record: Dict[str, Any], person_name: str, person_ids: set[str]) -> bool:
    for key in ["primaryKeyBuyer", "buyer", "buyerName", "primaryKeyBuyerName"]:
        candidate_name = first_non_empty(record, [key])
        if not candidate_name:
            continue
        if exact_name_equals(person_name, candidate_name) or same_first_last_name(person_name, candidate_name):
            return True
    candidate_id = first_non_empty(record, ["primaryKeyBuyerId", "buyerId", "contactId", "id", "personId"])
    if candidate_id and str(candidate_id).strip() in person_ids:
        return True
    candidate_name = full_person_name(record) or first_non_empty(record, ["name", "fullName"])
    if candidate_name and (exact_name_equals(person_name, candidate_name) or same_first_last_name(person_name, candidate_name)):
        return True
    return False


def _matching_key_buyer_record(
    account: Optional[Dict[str, Any]],
    person_name: str,
    person_ids: set[str],
) -> Dict[str, Any]:
    if not isinstance(account, dict):
        return {}
    for buyer in to_list_dicts(account.get("keyBuyers")):
        if _record_matches_person_reference(buyer, person_name, person_ids):
            return buyer
    return {}


def _matching_account_projects(
    account: Optional[Dict[str, Any]],
    person_name: str,
    person_ids: set[str],
) -> List[Dict[str, Any]]:
    if not isinstance(account, dict):
        return []
    return [
        project
        for project in to_list_dicts(account.get("project"))
        if _record_matches_person_reference(project, person_name, person_ids)
    ]


def _matching_closed_won_opportunities(
    account: Optional[Dict[str, Any]],
    person_name: str,
    person_ids: set[str],
) -> List[Dict[str, Any]]:
    if not isinstance(account, dict):
        return []

    wins: List[Dict[str, Any]] = []
    for bucket in ["allOpportunity", "openOpportunity"]:
        for opportunity in to_list_dicts(account.get(bucket)):
            if not _record_matches_person_reference(opportunity, person_name, person_ids):
                continue
            stage = normalize_text(str(first_non_empty(opportunity, ["opportunityStage", "stage"]) or ""))
            if stage in {"closed won", "closed - won"}:
                wins.append(opportunity)
    return dedupe_simple_records(
        wins,
        keys=["opportunityId", "opportunityKey", "name", "primaryKeyBuyer", "primaryKeyBuyerId"],
    )


def build_person_profile_transition(
    person_requested: str,
    person_resolution: Dict[str, Any],
    candidate_people: List[Dict[str, Any]],
    to_account: Dict[str, Any],
    from_account: Optional[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    status = person_resolution.get("status") or "not_found"
    matched = person_resolution.get("matched") if isinstance(person_resolution.get("matched"), dict) else None

    suggestions = [] if status == "matched" else top_person_candidates(person_requested, candidate_people, top_n=3)

    if status == "ambiguous":
        warnings.append("Exact person match was ambiguous across candidates; person marked unverified.")
    elif status == "not_found":
        warnings.append("Exact person match not found; person marked unverified.")

    direct_evidence = False
    evidence_basis: List[str] = []
    if matched:
        direct_evidence, evidence_basis = detect_direct_person_evidence(
            person_name=full_person_name(matched),
            to_account=to_account,
            from_account=from_account,
        )

    profile = {
        "person_requested": person_requested,
        "match_status": status,
        "person_unverified": status != "matched",
        "matched_person": None,
        "last_updated": None,
        "title_salesforce": None,
        "title_external": None,
        "location": None,
        "in_salesforce": None,
        "protiviti_alumni": None,
        "contact_at_robert_half": None,
        "function": None,
        "level": None,
        "email": None,
        "phone": None,
        "linkedin_url": None,
        "photo_url": None,
        "past_job_experience": [],
        "education": [],
        "candidate_suggestions": suggestions,
        "direct_person_evidence": direct_evidence,
        "person_claim_allowed": bool(direct_evidence),
        "claim_policy_note": (
            "Direct person-level evidence found in ProConnect; person-level claim allowed."
            if direct_evidence
            else "No direct person-level evidence found; use account-level claim with caution."
        ),
        "evidence_basis": evidence_basis,
        "relationship_owner": None,
        "project_count": 0,
        "win_count": 0,
        "match_strategy": person_resolution.get("match_strategy"),
    }

    if not matched:
        return profile

    matched_name = full_person_name(matched)
    person_ids = _person_reference_ids(matched)
    scoped_account = (
        from_account
        if person_resolution.get("match_scope") == "from"
        else to_account
        if person_resolution.get("match_scope") == "to"
        else from_account or to_account
    )
    key_buyer_match = _matching_key_buyer_record(scoped_account, matched_name, person_ids)
    scoped_projects = _matching_account_projects(scoped_account, matched_name, person_ids)
    scoped_wins = _matching_closed_won_opportunities(scoped_account, matched_name, person_ids)
    merged_projects = dedupe_simple_records(
        to_list_dicts(first_non_empty(matched, ["projects"]))
        + to_list_dicts(first_non_empty(key_buyer_match, ["projects"]))
        + scoped_projects,
        keys=["projectId", "id", "name", "primaryKeyBuyerId", "primaryKeyBuyer"],
    )
    merged_wins = dedupe_simple_records(
        to_list_dicts(first_non_empty(matched, ["closeWonOpps", "closeWonOpportunities"]))
        + to_list_dicts(first_non_empty(key_buyer_match, ["closeWonOpps", "closeWonOpportunities"]))
        + scoped_wins,
        keys=["opportunityId", "opportunityKey", "id", "name", "primaryKeyBuyerId", "primaryKeyBuyer"],
    )

    project_count = max(
        to_int(first_non_empty(matched, ["projectCount", "project_count", "numberOfProjects"])) or 0,
        len(merged_projects),
        to_int(first_non_empty(key_buyer_match, ["projectCount", "project_count", "numberOfProjects"])) or 0,
    )
    win_count = max(
        to_int(first_non_empty(matched, ["winCount", "win_count", "numberOfWins", "wins"])) or 0,
        len(merged_wins),
        to_int(first_non_empty(key_buyer_match, ["winCount", "win_count", "numberOfWins", "wins"])) or 0,
    )

    profile["matched_person"] = {
        "name": matched_name,
        "title": first_non_empty(matched, ["title"]),
        "source": person_resolution.get("match_source"),
        "company_scope": person_resolution.get("match_scope"),
        "linked_account_id": matched.get("linked_account_id"),
        "relationship_owner": first_non_empty(
            matched,
            ["relationshipOwner", "relationship_owner"],
        )
        or first_non_empty(key_buyer_match, ["relationshipOwner", "relationship_owner"]),
        "project_count": project_count,
        "win_count": win_count,
        "projects": merged_projects,
        "closeWonOpps": merged_wins,
        "score": 1.0,
    }

    profile["title_salesforce"] = first_non_empty(matched, ["titleSalesforce", "title"])
    profile["title_external"] = first_non_empty(matched, ["titleExternal"])
    profile["location"] = first_non_empty(matched, ["location"])
    profile["in_salesforce"] = to_bool(first_non_empty(matched, ["isInSalesforce", "inSalesforce"]))
    profile["protiviti_alumni"] = to_bool(first_non_empty(matched, ["isProtivitiAlumni", "protivitiAlumni"]))
    profile["contact_at_robert_half"] = to_bool(
        first_non_empty(matched, ["hasRoberthalfContact", "contactAtRobertHalf"])
    )
    profile["function"] = first_non_empty(matched, ["function"])
    profile["level"] = first_non_empty(matched, ["level"])
    profile["email"] = first_non_empty(matched, ["emailAddress", "email"])
    profile["phone"] = first_non_empty(matched, ["phone"])
    profile["linkedin_url"] = first_non_empty(matched, ["linkedinUrl", "linkedInUrl"])
    profile["photo_url"] = first_non_empty(matched, ["photoUrl"])
    profile["last_updated"] = first_non_empty(matched, ["lastUpdated", "modifiedDate"])
    profile["past_job_experience"] = to_list(first_non_empty(matched, ["pastJobExperience", "pastJobs"]))
    profile["education"] = to_list(first_non_empty(matched, ["education", "educationList"]))
    profile["relationship_owner"] = first_non_empty(
        matched,
        ["relationshipOwner", "relationship_owner"],
    ) or first_non_empty(key_buyer_match, ["relationshipOwner", "relationship_owner"])
    profile["project_count"] = project_count
    profile["win_count"] = win_count

    if not any(
        [
            profile["title_salesforce"],
            profile["title_external"],
            profile["location"],
            profile["email"],
            profile["linkedin_url"],
            profile["past_job_experience"],
            profile["education"],
        ]
    ):
        warnings.append("Person profile fields were unavailable from ProConnect sources.")

    return profile


def detect_direct_person_evidence(
    person_name: str,
    to_account: Dict[str, Any],
    from_account: Optional[Dict[str, Any]],
) -> Tuple[bool, List[str]]:
    basis: List[str] = []
    normalized_person = normalize_text(person_name)

    if not normalized_person:
        return False, basis

    def _scan_account(account: Optional[Dict[str, Any]], scope: str) -> None:
        if not account:
            return

        for buyer in to_list_dicts(account.get("keyBuyers")):
            if normalize_text(full_person_name(buyer)) == normalized_person:
                basis.append(f"{scope}:key_buyers")
                break

        for opp in to_list_dicts(account.get("allOpportunity")) + to_list_dicts(account.get("openOpportunity")):
            if normalize_text(str(first_non_empty(opp, ["primaryKeyBuyer"]) or "")) == normalized_person:
                basis.append(f"{scope}:opportunity_primary_key_buyer")
                break

        for project in to_list_dicts(account.get("project")):
            if normalize_text(str(first_non_empty(project, ["primaryKeyBuyer"]) or "")) == normalized_person:
                basis.append(f"{scope}:project_primary_key_buyer")
                break

    _scan_account(to_account, "to")
    _scan_account(from_account, "from")

    return (len(basis) > 0), sorted(set(basis))


def missing_destination_core_sections(
    account_context: Dict[str, Any],
    projects: Dict[str, Any],
    opportunities: Dict[str, Any],
    key_buyers: Dict[str, Any],
    org_chart_items: List[Dict[str, Any]],
) -> List[str]:
    missing: List[str] = []

    account_ok = bool(account_context.get("account_id") and account_context.get("company_name"))
    projects_ok = bool((to_int(projects.get("total_projects")) or 0) > 0 or projects.get("items"))
    opp_ok = bool(opportunities.get("items"))
    buyers_ok = bool(key_buyers.get("items"))
    org_ok = bool(org_chart_items)

    if not account_ok:
        missing.append("account_context")
    if not opp_ok:
        missing.append("opportunities")
    if not buyers_ok:
        missing.append("key_buyers")
    if not org_ok:
        missing.append("org_chart")
    if not projects_ok:
        missing.append("projects")

    return missing


def rank_destination_opportunities(opportunities: List[Dict[str, Any]], person_name: str) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []

    for opp in opportunities:
        stage_score = stage_signal_score(str(opp.get("stage") or ""))
        buyer_score = 1.0 if first_non_empty(opp, ["primary_key_buyer"]) else 0.0
        md_score = 1.0 if first_non_empty(opp, ["md_d"]) else 0.0
        em_score = 1.0 if first_non_empty(opp, ["em"]) else 0.0
        recency_score = recency_signal_score(first_non_empty(opp, ["close_date", "created_date"]))

        score = round(
            (0.45 * stage_score) + (0.2 * buyer_score) + (0.15 * md_score) + (0.1 * em_score) + (0.1 * recency_score),
            4,
        )

        evidence_refs = [
            f"stage:{opp.get('stage') or 'unknown'}",
            "has_primary_key_buyer" if buyer_score else "no_primary_key_buyer",
            "has_md" if md_score else "no_md",
            "has_em" if em_score else "no_em",
        ]

        if exact_name_equals(person_name, str(opp.get("primary_key_buyer") or "")):
            score = round(min(score + 0.05, 1.0), 4)
            evidence_refs.append("person_matches_primary_key_buyer")

        ranked.append(
            {
                "rank_score": score,
                "rank_band": band_for_score(score),
                "evidence_refs": evidence_refs,
                **opp,
            }
        )

    ranked.sort(key=lambda row: (row.get("rank_score", 0.0), str(row.get("close_date") or "")), reverse=True)

    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx

    return ranked[:10]


def stage_signal_score(stage: str) -> float:
    normalized = normalize_text(stage)
    if not normalized:
        return 0.35
    for key, value in STAGE_SCORE_MAP.items():
        if key in normalized:
            return value
    return 0.5


def recency_signal_score(date_value: Any) -> float:
    if not date_value:
        return 0.5
    parsed = parse_iso_datetime(str(date_value))
    if not parsed:
        return 0.5

    now = datetime.now(timezone.utc)
    delta_days = abs((now - parsed).days)
    if delta_days >= 5 * 365:
        return 0.0
    return round(max(0.0, 1.0 - (delta_days / float(5 * 365))), 4)


def parse_iso_datetime(value: str) -> Optional[datetime]:
    text = value.strip()
    if not text:
        return None
    candidates = [text]
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def band_for_score(score: float) -> str:
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    if score > 0:
        return "Low"
    return "Unknown"


def collect_org_chart_people(
    client: ProConnectClient,
    zoom_info_account_id: Optional[str],
    department_hint: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    if not zoom_info_account_id:
        return [], [], ["Missing zoomInfoAccountId; org chart unavailable."]

    warnings: List[str] = []
    people: List[Dict[str, Any]] = []

    executive_response = client.get_org_chart(
        zoom_info_account_id=zoom_info_account_id,
        department="C-Suite",
        sfdc_job_function="Executive",
        page=None,
        size=None,
    )
    if executive_response.get("success"):
        employees = extract_employees(executive_response.get("data"))
        for employee in employees:
            employee["_source"] = "org_chart_executive"
            if not employee.get("department"):
                employee["department"] = "C-Suite"
            people.append(employee)
    else:
        warnings.append(
            f"Org chart executive lookup failed with status {executive_response.get('status_code')}."
        )

    ordered_departments: List[str]
    if department_hint and department_hint in DEPARTMENT_TO_SFDC_FUNCTIONS:
        ordered_departments = [department_hint] + [key for key in DEPARTMENT_TO_SFDC_FUNCTIONS if key != department_hint]
    else:
        ordered_departments = list(DEPARTMENT_TO_SFDC_FUNCTIONS.keys())

    for department in ordered_departments:
        for job_function in DEPARTMENT_TO_SFDC_FUNCTIONS.get(department, []):
            response = client.get_org_chart(
                zoom_info_account_id=zoom_info_account_id,
                department=department,
                sfdc_job_function=job_function,
                page=1,
                size=3,
            )
            if response.get("success"):
                employees = extract_employees(response.get("data"))
                for employee in employees:
                    employee["_source"] = "org_chart_department"
                    if not employee.get("department"):
                        employee["department"] = department
                    people.append(employee)
            else:
                warnings.append(
                    f"Org chart {department}/{job_function} failed with status {response.get('status_code')}."
                )

    deduped_people = dedupe_transition_people(people)
    for person in deduped_people:
        person.setdefault("_source", "org_chart")

    items = []
    for person in deduped_people:
        name = full_person_name(person)
        if not name:
            continue
        items.append(
            {
                "category_or_department": person.get("department") or person.get("sfdcJobFunction"),
                "executive_name": name,
                "title": person.get("title"),
            }
        )

    deduped_items = dedupe_simple_records(items, keys=["category_or_department", "executive_name", "title"])
    return deduped_items, deduped_people, warnings


def probe_additional_endpoints(
    client: ProConnectClient,
    account_id: Optional[str],
    zoom_info_account_id: Optional[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    payloads: List[Dict[str, Any]] = []

    del account_id
    if not zoom_info_account_id:
        return payloads, warnings

    params = {"zoomInfoAccountId": zoom_info_account_id}
    for endpoint in ACCOUNT_PROBE_ENDPOINTS:
        response = client.get_endpoint(
            endpoint=endpoint,
            params=params,
            retry_on_5xx=1,
            retry_delay_seconds=0.25,
            stop_on_auth=True,
        )
        response_kind, data_usable = classify_probe_response_data(response.get("data"))

        payloads.append(
            {
                "endpoint": endpoint,
                "params": dict(params),
                "status_code": response.get("status_code"),
                "success": response.get("success"),
                "response_kind": response_kind,
                "data_usable": data_usable,
                "data": response.get("data"),
            }
        )

        status_code = response.get("status_code")
        if response.get("auth_blocked") or status_code in {401, 403}:
            warnings.append(f"Probe endpoint {endpoint} blocked by authorization ({status_code}).")
        elif response.get("success") and response_kind == "html_shell":
            warnings.append(
                f"Probe endpoint {endpoint} returned ProConnect app HTML instead of JSON; path is likely not a live API route."
            )
        elif response.get("success") and response_kind == "html":
            warnings.append(
                f"Probe endpoint {endpoint} returned HTML instead of JSON; payload was not usable for extraction."
            )
        elif not response.get("success"):
            warnings.append(f"Probe endpoint {endpoint} failed with status {status_code}.")

    return payloads, warnings


def enrich_person_resolution_from_prospect_detail(
    client: ProConnectClient,
    person_name: str,
    person_resolution: Dict[str, Any],
    candidate_people: List[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    if str(person_resolution.get("status") or "") != "matched":
        return person_resolution

    matched = person_resolution.get("matched")
    if not isinstance(matched, dict):
        return person_resolution

    prospect_id = select_person_detail_prospect_id(
        person_name=person_name,
        matched_person=matched,
        candidate_people=candidate_people,
    )
    if not prospect_id:
        return person_resolution

    response = client.get_endpoint(
        endpoint=f"/api/prospects/{prospect_id}",
        params=None,
        retry_on_5xx=1,
        retry_delay_seconds=0.25,
        stop_on_auth=True,
    )
    status_code = response.get("status_code")
    if response.get("auth_blocked") or status_code in {401, 403}:
        warnings.append(f"Person detail lookup blocked by authorization ({status_code}).")
        return person_resolution
    if not response.get("success"):
        warnings.append(f"Person detail lookup failed with status {status_code}.")
        return person_resolution

    response_kind, _ = classify_probe_response_data(response.get("data"))
    if response_kind == "html_shell":
        warnings.append("Person detail lookup returned ProConnect app HTML instead of JSON.")
        return person_resolution
    if response_kind == "html":
        warnings.append("Person detail lookup returned HTML instead of JSON.")
        return person_resolution

    detail_candidate = extract_person_detail_candidate(response.get("data"))
    if not detail_candidate:
        return person_resolution

    enriched = merge_person_candidates(
        candidates=[matched, detail_candidate],
        selected=matched,
        title_hints=[],
    )
    enriched["_source"] = matched.get("_source")
    enriched["_company_scope"] = matched.get("_company_scope")
    enriched["linked_account_id"] = matched.get("linked_account_id")
    enriched["linked_company_name"] = matched.get("linked_company_name")

    result = dict(person_resolution)
    result["matched"] = enriched
    return result


def select_person_detail_prospect_id(
    person_name: str,
    matched_person: Dict[str, Any],
    candidate_people: List[Dict[str, Any]],
) -> Optional[str]:
    target_account_id = str(matched_person.get("linked_account_id") or "")
    target_scope = str(matched_person.get("_company_scope") or "")

    eligible: List[Dict[str, Any]] = []
    for candidate in candidate_people:
        if not isinstance(candidate, dict):
            continue
        candidate_id = first_non_empty(candidate, ["contactId", "id"])
        if not candidate_id:
            continue
        if not exact_name_equals(person_name, full_person_name(candidate)):
            continue
        candidate_account_id = str(candidate.get("linked_account_id") or "")
        candidate_scope = str(candidate.get("_company_scope") or "")
        if target_account_id and candidate_account_id and candidate_account_id != target_account_id:
            continue
        if target_scope and candidate_scope and candidate_scope != target_scope:
            continue
        eligible.append(candidate)

    if not eligible:
        return first_non_empty(matched_person, ["contactId", "id"])

    def _sort_key(candidate: Dict[str, Any]) -> Tuple[int, int, int]:
        source = str(candidate.get("_source") or "")
        person_search_rank = 1 if source == "person_search" else 0
        same_account_rank = 1 if str(candidate.get("linked_account_id") or "") == target_account_id else 0
        source_rank = SOURCE_PRIORITY.get(source, 0)
        return (person_search_rank, same_account_rank, source_rank)

    selected = sorted(eligible, key=_sort_key, reverse=True)[0]
    return str(first_non_empty(selected, ["contactId", "id"]) or "")


def extract_person_detail_candidate(payload: Any) -> Optional[Dict[str, Any]]:
    candidate_nodes: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        candidate_nodes.append(payload)
        document = payload.get("document")
        if isinstance(document, dict):
            candidate_nodes.append(document)
    elif isinstance(payload, list):
        candidate_nodes.extend(to_list_dicts(payload))

    for node in candidate_nodes:
        record = parse_person_like_record(node)
        if not record:
            continue
        external_view_raw = node.get("externalProspectView")
        if not isinstance(external_view_raw, dict):
            external_view_raw = node.get("ExternalProspectView")
        external_view = external_view_raw if isinstance(external_view_raw, dict) else {}
        supplemental = {
            "titleExternal": first_non_empty(external_view, ["title"]),
            "phone": first_non_empty(external_view, ["phone"]),
            "education": first_non_empty(external_view, ["education"]),
            "linkedinUrl": first_non_empty(external_view, ["linkedinUrl", "linkedInUrl"]),
            "emailAddress": first_non_empty(external_view, ["emailAddress", "email"]),
            "location": first_non_empty(external_view, ["location"]),
            "photoUrl": first_non_empty(external_view, ["photoUrl"]),
        }
        record = merge_person_candidates(
            candidates=[record, supplemental],
            selected=record,
            title_hints=[],
        )
        record["id"] = first_non_empty(node, ["contactId", "id", "prospectId", "personId"]) or record.get("id")
        record["accountId"] = first_non_empty(node, ["accountId", "sfdcAccountId"])
        record["_source"] = "person_detail"
        return record

    for node in iter_dict_nodes(payload):
        record = parse_person_like_record(node)
        if not record:
            continue
        record["id"] = first_non_empty(node, ["contactId", "id", "prospectId", "personId"]) or record.get("id")
        record["accountId"] = first_non_empty(node, ["accountId", "sfdcAccountId"])
        record["_source"] = "person_detail"
        return record

    return None


def extract_person_search_candidates(payload: Any) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return candidates

    for item in to_list_dicts(payload.get("value")):
        document = item.get("document") if isinstance(item.get("document"), dict) else item
        if not isinstance(document, dict):
            continue

        name = first_non_empty(document, ["name", "contactName", "fullName"])
        if not name:
            continue

        candidates.append(
            {
                "contactId": first_non_empty(document, ["contactId", "id"]),
                "name": name,
                "title": first_non_empty(document, ["title"]),
                "emailAddress": first_non_empty(document, ["emailAddress"]),
                "linkedinUrl": first_non_empty(document, ["linkedinUrl", "linkedInUrl"]),
                "location": first_non_empty(document, ["location"]),
                "isInSalesforce": first_non_empty(document, ["isInSalesforce", "inSalesforce"]),
                "isProtivitiAlumni": first_non_empty(document, ["isProtivitiAlumni", "protivitiAlumni"]),
                "hasRoberthalfContact": first_non_empty(document, ["hasRoberthalfContact", "contactAtRobertHalf"]),
                "phone": first_non_empty(document, ["phone"]),
                "pastJobExperience": first_non_empty(document, ["pastJobExperience", "pastJobs"]),
                "education": first_non_empty(document, ["education", "educationList"]),
                "function": first_non_empty(document, ["function"]),
                "level": first_non_empty(document, ["level"]),
                "photoUrl": first_non_empty(document, ["photoUrl"]),
                "lastUpdated": first_non_empty(document, ["lastUpdated", "modifiedDate"]),
                "accountId": first_non_empty(document, ["accountId", "sfdcAccountId"]),
                "companyName": first_non_empty(document, ["companyName", "name"]),
                "relationshipOwner": first_non_empty(document, ["relationshipOwner", "relationship_owner"]),
                "projectCount": first_non_empty(document, ["projectCount", "project_count", "numberOfProjects"]),
                "winCount": first_non_empty(document, ["winCount", "win_count", "numberOfWins", "wins"]),
                "projects": first_non_empty(document, ["projects"]),
                "closeWonOpps": first_non_empty(document, ["closeWonOpps", "closeWonOpportunities"]),
                "connections": first_non_empty(document, ["connections"]),
            }
        )

    return candidates


def extract_probe_people(probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    people: List[Dict[str, Any]] = []
    for payload in probe_payloads:
        endpoint = payload.get("endpoint") or "probe"
        for node in iter_dict_nodes(payload.get("data")):
            record = parse_person_like_record(node)
            if not record:
                continue
            record["_source"] = f"probe:{endpoint}"
            people.append(record)

    return dedupe_transition_people(people)


def build_transition_provenance(
    transition_payload: Dict[str, Any],
    probe_payloads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    to_context = transition_payload.get("to_company_context") or {}
    from_context = transition_payload.get("from_company_context") or {}
    person_profile = transition_payload.get("person_profile") or {}

    return {
        "precedence_rule": "Matrix > Per-source dictionary > Consolidated dictionary",
        "movement_event": prov("runtime_input", "present"),
        "person_profile": {
            "source": "proconnect_person_search_and_company_context",
            "status": present(person_profile.get("match_status")),
            "confidence": 1.0,
        },
        "from_company_context": {
            "source": "proconnect_account_lite",
            "status": present(from_context.get("account_header", {}).get("account_id")),
            "confidence": 1.0,
        },
        "to_company_context": {
            "source": "proconnect_account_full",
            "status": present(to_context.get("account_context", {}).get("account_id")),
            "confidence": 1.0,
        },
        "movement_evidence": {
            "source": "derived_from_proconnect",
            "status": present(transition_payload.get("movement_evidence", {}).get("ranked_opportunities_top10")),
            "confidence": 1.0,
        },
        "optional_sections": {
            "source": "proconnect_optional",
            "status": present(transition_payload.get("optional_sections")),
            "confidence": 1.0,
        },
        "probe_summary": {
            "source": "proconnect_probes",
            "status": "present" if probe_payloads else "missing",
            "confidence": 1.0,
        },
    }


def build_transition_confidence(transition_payload: Dict[str, Any]) -> Dict[str, Any]:
    person_profile = transition_payload.get("person_profile") or {}
    from_context = transition_payload.get("from_company_context") or {}
    to_context = transition_payload.get("to_company_context") or {}
    movement_evidence = transition_payload.get("movement_evidence") or {}

    person_score = person_confidence_score(person_profile)
    from_score = section_completeness_score(from_context.get("account_header") or {})

    to_scores = [
        section_completeness_score(to_context.get("account_context") or {}),
        section_item_score(to_context.get("projects", {}).get("items")),
        section_item_score(to_context.get("opportunities", {}).get("items")),
        section_item_score(to_context.get("key_buyers", {}).get("items")),
        section_item_score(to_context.get("org_chart", {}).get("items")),
    ]
    to_score = round(sum(to_scores) / float(len(to_scores)), 4) if to_scores else 0.0

    ranked = to_list_dicts(movement_evidence.get("ranked_opportunities_top10"))
    if ranked:
        movement_score = round(sum(float(item.get("rank_score") or 0.0) for item in ranked) / len(ranked), 4)
    else:
        movement_score = 0.0

    return {
        "person_profile": confidence_obj(person_score),
        "from_company_context": confidence_obj(from_score),
        "to_company_context": confidence_obj(to_score),
        "movement_evidence": confidence_obj(movement_score),
        "ranked_opportunities_top10": [
            {
                "opportunity": item.get("opportunity"),
                "score": item.get("rank_score"),
                "band": item.get("rank_band"),
            }
            for item in ranked
        ],
    }


def person_confidence_score(person_profile: Dict[str, Any]) -> float:
    status = str(person_profile.get("match_status") or "not_found").lower()
    if status == "matched":
        scope = str((person_profile.get("matched_person") or {}).get("company_scope") or "unknown")
        if scope == "to":
            return 0.95
        if scope == "from":
            return 0.85
        return 0.75
    if status == "ambiguous":
        return 0.4
    return 0.2


def confidence_obj(score: float) -> Dict[str, Any]:
    value = round(max(0.0, min(float(score), 1.0)), 4)
    return {
        "score": value,
        "band": band_for_score(value),
    }


def section_completeness_score(section: Dict[str, Any]) -> float:
    if not section:
        return 0.0
    values = list(section.values())
    if not values:
        return 0.0
    present_count = sum(1 for value in values if present(value) == "present")
    return round(present_count / float(len(values)), 4)


def section_item_score(items: Any) -> float:
    if isinstance(items, list) and items:
        return 1.0
    return 0.0


def extract_optional_sections(account: Optional[Dict[str, Any]], probe_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not account:
        return {
            "competitors": [],
            "partners": [],
            "social_urls": [],
            "marketing_signals": [],
            "internal_connections": [],
            "intent_signals": [],
            "recent_activity": [],
            "probe_payload_shapes": summarize_probe_payloads(probe_payloads),
            "probe_endpoint_statuses": [
                {
                    "endpoint": payload.get("endpoint"),
                    "status_code": payload.get("status_code"),
                    "success": payload.get("success"),
                }
                for payload in probe_payloads
            ],
        }

    competitors = extract_company_nodes(account, include_terms=["competitor"], site_key="website")
    partners = extract_company_nodes(account, include_terms=["partner"], site_key="website")
    social_urls = extract_social_urls(account)
    marketing_signals = extract_marketing_signals(account)
    internal_connections = extract_probe_internal_connection_items(probe_payloads)
    intent_signals = extract_probe_intent_signals(probe_payloads)
    recent_activity = extract_probe_recent_activity(probe_payloads)

    return {
        "competitors": competitors,
        "partners": partners,
        "social_urls": social_urls,
        "marketing_signals": marketing_signals,
        "internal_connections": internal_connections,
        "intent_signals": intent_signals,
        "recent_activity": recent_activity,
        "probe_payload_shapes": summarize_probe_payloads(probe_payloads),
        "probe_endpoint_statuses": [
            {
                "endpoint": payload.get("endpoint"),
                "status_code": payload.get("status_code"),
                "success": payload.get("success"),
            }
            for payload in probe_payloads
        ],
    }


def extract_company_nodes(account: Dict[str, Any], include_terms: List[str], site_key: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for node in iter_dict_nodes(account):
        if not isinstance(node, dict):
            continue
        keys_lower = [str(key).lower() for key in node.keys()]
        if not any(any(term in key for term in include_terms) for key in keys_lower):
            continue

        name = first_non_empty(node, ["name", "companyName", "competitor", "partner"])
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "website": first_non_empty(node, [site_key, "websiteUrl", "url"]),
                "employee_count": to_int(first_non_empty(node, ["employeeCount", "numberOfEmployees"])),
            }
        )

    return dedupe_simple_records(rows, keys=["name", "website"])


def extract_social_urls(account: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for node in iter_dict_nodes(account):
        if isinstance(node, str):
            if node.startswith("http") and any(site in node.lower() for site in ["linkedin", "twitter", "facebook", "instagram"]):
                urls.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                if "social" not in str(key).lower():
                    continue
                if isinstance(value, str) and value.startswith("http"):
                    urls.append(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.startswith("http"):
                            urls.append(item)
                        elif isinstance(item, dict):
                            url = first_non_empty(item, ["url", "socialUrl", "website"])
                            if isinstance(url, str) and url.startswith("http"):
                                urls.append(url)
    return dedupe_list(urls)


def extract_marketing_signals(account: Dict[str, Any]) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []

    marketing_a = account.get("marketingSolutionA")
    if isinstance(marketing_a, list):
        signals.append({"signal": "marketingSolutionA", "count": len(marketing_a)})

    marketing_1y = account.get("marketingSolution1Year")
    if isinstance(marketing_1y, list):
        signals.append({"signal": "marketingSolution1Year", "count": len(marketing_1y)})

    campaign_actions = account.get("campaignsActionsA")
    if isinstance(campaign_actions, list):
        signals.append({"signal": "campaignsActionsA", "count": len(campaign_actions)})

    campaigns = account.get("campaigns")
    if isinstance(campaigns, list):
        signals.append({"signal": "campaigns", "count": len(campaigns)})

    return signals


def summarize_probe_payloads(probe_payloads: List[Dict[str, Any]], max_node_samples: int = 6) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for payload in probe_payloads:
        data = payload.get("data")
        top_level_keys = sorted(list(data.keys()))[:20] if isinstance(data, dict) else []
        raw_text = data.get("raw_text") if isinstance(data, dict) else None
        response_kind, data_usable = classify_probe_response_data(data)
        summaries.append(
            {
                "endpoint": payload.get("endpoint"),
                "status_code": payload.get("status_code"),
                "success": payload.get("success"),
                "params": payload.get("params"),
                "data_type": type(data).__name__,
                "top_level_keys": top_level_keys,
                "response_kind": payload.get("response_kind") or response_kind,
                "data_usable": payload.get("data_usable") if payload.get("data_usable") is not None else data_usable,
                "raw_text_length": len(raw_text) if isinstance(raw_text, str) else None,
                "raw_text_preview": summarize_raw_text(raw_text),
                "dict_node_samples": collect_dict_node_samples(data, max_samples=max_node_samples),
            }
        )
    return summaries


def collect_dict_node_samples(value: Any, max_samples: int = 6) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []

    def _walk(current: Any, path: str) -> None:
        if len(samples) >= max_samples:
            return
        if isinstance(current, dict):
            samples.append(
                {
                    "path": path,
                    "keys": sorted(str(key) for key in current.keys())[:20],
                }
            )
            for key, child in current.items():
                if len(samples) >= max_samples:
                    break
                if isinstance(child, dict):
                    _walk(child, f"{path}.{key}")
                elif isinstance(child, list):
                    for idx, item in enumerate(child):
                        if len(samples) >= max_samples:
                            break
                        if isinstance(item, dict):
                            _walk(item, f"{path}.{key}[{idx}]")
        elif isinstance(current, list):
            for idx, item in enumerate(current):
                if len(samples) >= max_samples:
                    break
                if isinstance(item, dict):
                    _walk(item, f"{path}[{idx}]")

    _walk(value, "$")
    return samples


def summarize_raw_text(value: Any, max_chars: int = 240) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def classify_probe_response_data(data: Any) -> Tuple[str, bool]:
    if isinstance(data, dict):
        raw_text = data.get("raw_text")
        if isinstance(raw_text, str):
            stripped = raw_text.strip()
            if not stripped:
                return "empty", False
            if is_proconnect_html_shell_text(stripped):
                return "html_shell", False
            if stripped.lower().startswith("<!doctype html") or stripped.lower().startswith("<html"):
                return "html", False
            return "plain_text", False
        return "json", True
    if isinstance(data, list):
        return "json", True
    if data is None:
        return "empty", False
    return type(data).__name__, True


def is_proconnect_html_shell_text(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    if not ("<!doctype html" in text or text.startswith("<html")):
        return False
    return "proconnect-logo.png" in text or "name=\"theme-color\"" in text or "id=\"root\"" in text


def extract_probe_internal_connection_items(probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for payload in probe_payloads:
        for node in iter_dict_nodes(payload.get("data")):
            record = parse_internal_connection_record(node)
            if record:
                rows.append(record)
    return dedupe_simple_records(rows, keys=["name", "employer", "title", "last_connected_date"])


def parse_internal_connection_record(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = first_non_empty(node, ["name", "person", "employeeName", "internalEmployeeName", "fullName"])
    if not name:
        return None

    has_connection_signal = bool(
        first_non_empty(
            node,
            [
                "lastConnected",
                "lastConnectedMethod",
                "lastConnectionMethod",
                "lastInteractionMethod",
                "lastConnectedDate",
                "lastConnectionDate",
                "lastInteractionDate",
                "numberOfInteractions",
                "interactionCount",
            ],
        )
    )
    if not has_connection_signal:
        return None

    last_connected = first_non_empty(node, ["lastConnected"])
    last_connected_method = first_non_empty(
        node,
        ["lastConnectedMethod", "lastConnectionMethod", "lastInteractionMethod"],
    )
    last_connected_date = first_non_empty(
        node,
        ["lastConnectedDate", "lastConnectionDate", "lastInteractionDate"],
    )

    if isinstance(last_connected, str) and "," in last_connected:
        left, right = [part.strip() for part in last_connected.split(",", 1)]
        last_connected_method = last_connected_method or left or None
        last_connected_date = last_connected_date or right or None
    elif isinstance(last_connected, str):
        last_connected_date = last_connected_date or last_connected.strip() or None

    return {
        "name": str(name).strip(),
        "employer": first_non_empty(node, ["companyName", "employer", "company"]),
        "title": first_non_empty(node, ["title", "role"]),
        "last_connected_method": last_connected_method,
        "last_connected_date": last_connected_date,
        "number_of_interactions": to_int(
            first_non_empty(node, ["numberOfInteractions", "interactionCount", "interactionsCount"])
        ),
    }


def extract_probe_intent_signals(probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for payload in probe_payloads:
        endpoint = str(payload.get("endpoint") or "probe")
        for node in iter_dict_nodes(payload.get("data")):
            record = parse_intent_signal_record(node)
            if record:
                record["source"] = f"probe:{endpoint}"
                rows.append(record)
    return dedupe_simple_records(rows, keys=["topic", "strength", "date", "source"])


def parse_intent_signal_record(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    topic = first_non_empty(node, ["topic", "intentTopic", "signalTopic", "name"])
    strength = first_non_empty(
        node,
        ["intentStrength", "strength", "audienceStrength", "intentScore", "signalScore", "score"],
    )
    signal_date = first_non_empty(node, ["intentDate", "signalDate", "importedDate", "date", "createdDate"])

    key_text = " ".join(str(key).lower() for key in node.keys())
    if "intent" not in key_text and not first_non_empty(
        node,
        ["intentStrength", "audienceStrength", "intentScore", "signalScore", "intentDate", "signalDate"],
    ):
        return None
    if not topic:
        return None

    return {
        "topic": str(topic).strip(),
        "strength": strength,
        "date": signal_date,
    }


def extract_probe_recent_activity(probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for payload in probe_payloads:
        endpoint = str(payload.get("endpoint") or "probe")
        for node in iter_dict_nodes(payload.get("data")):
            record = parse_recent_activity_record(node, endpoint=endpoint)
            if record:
                record["source"] = f"probe:{endpoint}"
                rows.append(record)
    return dedupe_simple_records(rows, keys=["type", "date", "description", "source"])


def parse_recent_activity_record(node: Dict[str, Any], endpoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    endpoint_text = str(endpoint or "").lower()
    is_scoop_endpoint = endpoint_text.endswith("/scoop")

    activity_type = first_non_empty(
        node,
        ["activityType", "type", "eventType", "category", "scoopType", "headlineType"],
    )
    activity_date = first_non_empty(
        node,
        ["activityDate", "date", "eventDate", "createdDate", "publishedDate", "importedDate"],
    )
    description = first_non_empty(
        node,
        ["description", "activityDescription", "details", "summary", "headline", "title"],
    )

    key_text = " ".join(str(key).lower() for key in node.keys())
    has_recent_activity_signal = bool(
        first_non_empty(node, ["activityType", "activityDate", "eventType", "eventDate"])
    )
    has_scoop_signal = bool(
        is_scoop_endpoint
        and first_non_empty(node, ["category", "publishedDate", "headline", "title", "description"])
    )
    if "activity" not in key_text and "scoop" not in key_text and not has_recent_activity_signal and not has_scoop_signal:
        return None
    if not any([activity_type, activity_date, description]):
        return None

    return {
        "type": activity_type,
        "date": activity_date,
        "description": description,
    }


def normalize_research_inputs(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    defaults = {
        "provided_name": None,
        "provided_role": None,
        "potential_service_needs": None,
        "simulated_research_datapoint": None,
    }
    if not isinstance(value, dict):
        return defaults
    result = dict(defaults)
    for key in defaults:
        result[key] = value.get(key)
    return result


def to_people_from_key_buyers(key_buyers: Any) -> List[Dict[str, Any]]:
    if not isinstance(key_buyers, list):
        return []
    people: List[Dict[str, Any]] = []
    for buyer in key_buyers:
        if not isinstance(buyer, dict):
            continue
        people.append(
            {
                "id": buyer.get("id") or buyer.get("buyerId"),
                "name": full_person_name(buyer),
                "title": buyer.get("title"),
                "linkedinUrl": buyer.get("linkedinUrl"),
                "emailAddress": buyer.get("emailAddress"),
                "function": buyer.get("function"),
                "lastOpportunityWonDate": buyer.get("lastOpportunityWonDate"),
                "lastOpportunityStage": buyer.get("lastOpportunityStage"),
                "relationshipOwner": buyer.get("relationshipOwner"),
                "projectCount": first_non_empty(buyer, ["projectCount", "numberOfProjects", "numberOfProject"]),
                "winCount": first_non_empty(buyer, ["winCount", "wins", "numberOfWins"]),
                "projects": buyer.get("projects"),
                "closeWonOpps": buyer.get("closeWonOpps"),
                "_source": "key_buyers",
            }
        )
    return people


def to_people_from_account_roles(account: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(account, dict):
        return []

    people: List[Dict[str, Any]] = []
    for role_key in ["accountPMO", "accountMDD", "accountExecutive"]:
        role_value = account.get(role_key)
        if not isinstance(role_value, dict):
            continue
        name = full_person_name(role_value)
        if not name:
            continue
        person = {
            "id": first_non_empty(role_value, ["id", "employeeId"]),
            "name": name,
            "title": first_non_empty(role_value, ["title"]),
            "emailAddress": first_non_empty(role_value, ["emailAddress", "principalName"]),
            "linkedinUrl": first_non_empty(role_value, ["linkedinUrl"]),
            "_source": "account_roles",
        }
        people.append(person)
    return people


def extract_employees(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    employees = payload.get("employees")
    if not isinstance(employees, list):
        return []
    return [item for item in employees if isinstance(item, dict)]


def dedupe_param_templates(templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for template in templates:
        normalized = tuple(sorted((str(k), str(v)) for k, v in template.items() if v not in (None, "")))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append({key: value for key, value in template.items() if value not in (None, "")})
    return deduped


def iter_dict_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            for child in current.values():
                stack.append(child)
        elif isinstance(current, list):
            for child in current:
                stack.append(child)


def parse_person_like_record(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    first_name = first_non_empty(node, ["firstName", "first_name"])
    last_name = first_non_empty(node, ["lastName", "last_name"])
    combined_name = " ".join(part for part in [first_name, last_name] if part).strip()
    name = first_non_empty(node, ["name", "person", "fullName"]) or combined_name
    title = first_non_empty(node, ["title", "titleSalesforce", "titleExternal", "externalTitle"])
    has_person_signals = bool(
        title
        or first_non_empty(node, ["location", "isInSalesforce", "isProtivitiAlumni", "hasRoberthalfContact"])
        or first_non_empty(node, ["pastJobExperience", "pastJobs", "education"])
    )
    if not name or not has_person_signals:
        return None

    return {
        "id": first_non_empty(node, ["id", "personId", "contactId"]),
        "name": name,
        "firstName": first_name,
        "lastName": last_name,
        "title": title,
        "titleSalesforce": first_non_empty(node, ["titleSalesforce", "salesforceTitle"]),
        "titleExternal": first_non_empty(node, ["titleExternal", "externalTitle"]),
        "location": first_non_empty(node, ["location"]),
        "isInSalesforce": first_non_empty(node, ["isInSalesforce", "inSalesforce"]),
        "isProtivitiAlumni": first_non_empty(node, ["isProtivitiAlumni", "protivitiAlumni"]),
        "hasRoberthalfContact": first_non_empty(node, ["hasRoberthalfContact", "contactAtRobertHalf"]),
        "pastJobExperience": first_non_empty(node, ["pastJobExperience", "pastJobs"]),
        "education": first_non_empty(node, ["education", "educationList"]),
        "linkedinUrl": first_non_empty(node, ["linkedinUrl", "linkedInUrl"]),
        "emailAddress": first_non_empty(node, ["emailAddress", "email"]),
        "phone": first_non_empty(node, ["phone"]),
        "function": first_non_empty(node, ["function"]),
        "level": first_non_empty(node, ["level"]),
        "photoUrl": first_non_empty(node, ["photoUrl"]),
        "lastUpdated": first_non_empty(node, ["lastUpdated", "modifiedDate"]),
        "relationshipOwner": first_non_empty(node, ["relationshipOwner", "relationship_owner"]),
        "projectCount": first_non_empty(node, ["projectCount", "project_count", "numberOfProjects"]),
        "winCount": first_non_empty(node, ["winCount", "win_count", "numberOfWins", "wins"]),
        "projects": first_non_empty(node, ["projects"]),
        "closeWonOpps": first_non_empty(node, ["closeWonOpps", "closeWonOpportunities"]),
        "connections": first_non_empty(node, ["connections"]),
    }


def extract_technologies(account: Dict[str, Any], probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    records.extend(extract_technologies_from_node(account))

    for payload in probe_payloads:
        endpoint = payload.get("endpoint") or "probe"
        for item in extract_technologies_from_node(payload.get("data")):
            if item.get("source") is None:
                item["source"] = f"probe:{endpoint}"
            records.append(item)

    return dedupe_simple_records(records, keys=["technology", "website"])


def extract_technologies_from_node(node: Any) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    if isinstance(node, dict):
        for key in ["technologies", "technology", "companyTechnologies", "technologiesUsed", "externalPartner"]:
            if key in node:
                results.extend(parse_technology_container(node.get(key), source="proconnect_account"))

    for obj in iter_dict_nodes(node):
        for key, value in obj.items():
            if "technolog" not in str(key).lower() and "partner" not in str(key).lower():
                continue
            results.extend(parse_technology_container(value, source=None))

    return dedupe_simple_records(results, keys=["technology", "website"])


def parse_technology_container(value: Any, source: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if isinstance(value, str):
        if value.strip():
            rows.append({"technology": value.strip(), "website": None, "source": source})
        return rows

    if isinstance(value, dict):
        technology = first_non_empty(value, ["technology", "name", "vendor", "tool", "value"])
        website = first_non_empty(value, ["website", "websiteUrl", "url", "vendorWebsite"])
        if technology:
            rows.append({"technology": technology, "website": website, "source": source})
        return rows

    if isinstance(value, list):
        for item in value:
            rows.extend(parse_technology_container(item, source=source))
        return rows

    return rows


def concise_summary(raw_summary: Optional[str], max_sentences: int = 3) -> Optional[str]:
    if not raw_summary:
        return None
    text = " ".join(str(raw_summary).split())
    if not text:
        return None

    parts = re.split(r"(?<=[.!?])\s+", text)
    trimmed = [part.strip() for part in parts if part.strip()]
    if not trimmed:
        return None
    concise = " ".join(trimmed[: max(max_sentences, 1)])
    if len(concise) > 600:
        concise = concise[:597].rstrip() + "..."
    return concise


def dedupe_transition_people(people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for person in people:
        if not isinstance(person, dict):
            continue
        key = (
            normalize_text(full_person_name(person)),
            normalize_text(str(person.get("title") or "")),
            str(person.get("linked_account_id") or ""),
            str(person.get("_source") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(person)
    return output


def first_non_empty(payload: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        for candidate_key in key_variants(key):
            value = payload.get(candidate_key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def key_variants(key: str) -> List[str]:
    text = str(key or "")
    if not text:
        return []

    variants: List[str] = []
    for candidate in [text, text[:1].lower() + text[1:], text[:1].upper() + text[1:]]:
        if candidate not in variants:
            variants.append(candidate)
    return variants


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
    return None


def to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return dedupe_list(items)
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[;\n|]", value) if part.strip()]
        return dedupe_list(parts)
    text = str(value).strip()
    return [text] if text else []


def to_list_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dedupe_list(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def dedupe_simple_records(records: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    deduped = []
    weak_identity_keys = {
        "primaryKeyBuyerId",
        "primaryKeyBuyer",
        "buyerId",
        "buyer",
        "buyerName",
        "primaryKeyBuyerName",
    }
    for record in records:
        strong_fingerprints = [
            f"{key}:{str(record.get(key) or '').strip().lower()}"
            for key in keys
            if key not in weak_identity_keys
            if str(record.get(key) or "").strip()
        ]
        weak_fingerprints = [
            f"{key}:{str(record.get(key) or '').strip().lower()}"
            for key in keys
            if key in weak_identity_keys
            if str(record.get(key) or "").strip()
        ]
        fingerprints = strong_fingerprints or weak_fingerprints
        if not fingerprints:
            fallback = normalize_text(json.dumps(record, sort_keys=True, default=str))
            fingerprints = [f"record:{fallback}"]

        existing_index = next(
            (idx for idx, item in enumerate(deduped) if any(fingerprint in item["_fingerprints"] for fingerprint in fingerprints)),
            None,
        )
        if existing_index is None:
            clone = dict(record)
            clone["_fingerprints"] = set(fingerprints)
            deduped.append(clone)
            seen.update(fingerprints)
            continue

        merged = dict(deduped[existing_index])
        for key, value in record.items():
            if key == "_fingerprints":
                continue
            if present(merged.get(key)) == "present" and present(value) != "present":
                continue
            if key in {"projects", "closeWonOpps", "closeWonOpportunities", "connections"}:
                merged[key] = _merge_person_list_field(normalize_text(key).replace(" ", ""), merged.get(key), value)
                continue
            current_int = to_int(merged.get(key))
            candidate_int = to_int(value)
            normalized_key = normalize_text(key).replace(" ", "")
            if normalized_key in {
                "projectcount",
                "project_count",
                "numberofprojects",
                "numberofproject",
                "wincount",
                "win_count",
                "numberofwins",
                "wins",
            }:
                merged[key] = max(current_int or 0, candidate_int or 0)
                continue
            if present(merged.get(key)) != "present":
                merged[key] = value
        merged["_fingerprints"] = set(merged.get("_fingerprints") or set()).union(fingerprints)
        deduped[existing_index] = merged
        seen.update(fingerprints)
    return [{k: v for k, v in record.items() if k != "_fingerprints"} for record in deduped]


def normalize_text(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_placeholder_account_id(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    upper = text.upper()
    if (text.startswith("<") and text.endswith(">")) or "ACCOUNT_ID" in upper:
        return True
    return False


def present(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, str) and not value.strip():
        return "missing"
    if isinstance(value, list) and len(value) == 0:
        return "missing"
    if isinstance(value, dict) and len(value) == 0:
        return "missing"
    return "present"


def prov(source: str, status: str, confidence: float = 1.0) -> Dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "confidence": round(float(confidence), 4),
    }
