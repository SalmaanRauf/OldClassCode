#!/usr/bin/env python3
"""Stakeholder-aligned ProConnect payload assembly for local script testing."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from proconnect_client import ProConnectClient
from proconnect_lookup_logic import (
    DEPARTMENT_TO_SFDC_FUNCTIONS,
    build_account_summary,
    dedupe_people,
    exact_name_equals,
    find_exact_person_match,
    full_person_name,
    get_zoom_info_account_id,
    resolve_company_and_account,
    top_person_candidates,
)

PROBE_ENDPOINT_ALLOWLIST = [
    "/api/taggedrelationships",
    "/api/relationshiplead",
    "/api/userHistory",
]


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
    company: str,
    person: str,
    department_hint: Optional[str] = None,
    account_id_override: Optional[str] = None,
    research_inputs: Optional[Dict[str, Any]] = None,
    enable_probes: bool = True,
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []
    research_inputs = normalize_research_inputs(research_inputs)

    account: Optional[Dict[str, Any]] = None
    company_resolution: Optional[Dict[str, Any]] = None
    account_summary: Optional[Dict[str, Any]] = None

    if account_id_override:
        account_response = client.get_account_by_id(account_id_override)
        company_resolution = {
            "query": company,
            "search_status_code": None,
            "search_success": None,
            "candidate_count": 0,
            "candidates": [],
            "selected_candidate": {"accountId": account_id_override},
            "selected_score": None,
            "account_fetch_status_code": account_response.get("status_code"),
            "resolved_account": bool(account_response.get("success")),
            "account_id_override": True,
        }
        if account_response.get("success"):
            account = account_response.get("data") if isinstance(account_response.get("data"), dict) else None
            checks.append(
                {
                    "check": "Account retrieval",
                    "status": "PASS",
                    "http": account_response.get("status_code"),
                    "details": f"Loaded account id {account_id_override}",
                }
            )
        else:
            checks.append(
                {
                    "check": "Account retrieval",
                    "status": "FAIL",
                    "http": account_response.get("status_code"),
                    "details": account_response.get("error") or "Account retrieval failed.",
                }
            )
            errors.append("No account context resolved from account-id override.")
    else:
        company_resolution, account, resolution_errors = resolve_company_and_account(
            client=client,
            company_name=company,
            key_person_name=person,
        )
        errors.extend(resolution_errors)

        if company_resolution.get("search_success"):
            checks.append(
                {
                    "check": "Prospects search",
                    "status": "PASS",
                    "http": company_resolution.get("search_status_code"),
                    "details": f"Candidates: {company_resolution.get('candidate_count', 0)}",
                }
            )
        else:
            checks.append(
                {
                    "check": "Prospects search",
                    "status": "FAIL",
                    "http": company_resolution.get("search_status_code"),
                    "details": "Search failed.",
                }
            )

        if account:
            checks.append(
                {
                    "check": "Account retrieval",
                    "status": "PASS",
                    "http": company_resolution.get("account_fetch_status_code"),
                    "details": f"Resolved account: {account.get('name', 'unknown')}",
                }
            )
        else:
            checks.append(
                {
                    "check": "Account retrieval",
                    "status": "FAIL",
                    "http": company_resolution.get("account_fetch_status_code"),
                    "details": "No account resolved from company search.",
                }
            )
            errors.append("No account context resolved from company search.")

    if account:
        account_summary = build_account_summary(account)

    stakeholder_payload = default_stakeholder_payload(person=person, research_inputs=research_inputs)

    if not account:
        person_profile = stakeholder_payload.get("person_profile") or {}
        person_profile["match_status"] = "not_found"
        person_profile["candidate_suggestions"] = []
        stakeholder_payload["person_profile"] = person_profile
        status = "FAIL"
        return {
            "status": status,
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
            "company_resolution": company_resolution,
            "person_resolution": {
                "status": "not_found",
                "match_source": None,
                "matched_person": None,
                "candidate_suggestions": [],
            },
            "account_summary": None,
            "stakeholder_payload": stakeholder_payload,
        }

    account_id = str(account.get("id") or "")
    zoom_info_account_id = get_zoom_info_account_id(account)

    org_chart_items, org_chart_people, org_warnings = collect_org_chart_people(
        client=client,
        zoom_info_account_id=zoom_info_account_id,
        department_hint=department_hint,
    )
    warnings.extend(org_warnings)
    checks.append(
        {
            "check": "Org chart collection",
            "status": "PASS" if org_chart_items else "WARN",
            "http": "-",
            "details": f"People collected: {len(org_chart_items)}",
        }
    )

    probe_payloads: List[Dict[str, Any]] = []
    probe_warnings: List[str] = []
    if enable_probes:
        probe_payloads, probe_warnings = probe_additional_endpoints(
            client=client,
            account_id=account_id or None,
            zoom_info_account_id=zoom_info_account_id,
        )
        warnings.extend(probe_warnings)

    probe_people = extract_probe_people(probe_payloads)
    key_buyer_people = to_people_from_key_buyers(account.get("keyBuyers"))
    candidate_people = key_buyer_people + org_chart_people + probe_people
    candidate_people = dedupe_people(candidate_people)

    matched = find_exact_person_match(person, key_buyer_people)
    match_source = "key_buyers" if matched else None

    if not matched:
        matched = find_exact_person_match(person, org_chart_people)
        if matched:
            match_source = "org_chart"

    if not matched:
        matched = find_exact_person_match(person, probe_people)
        if matched:
            match_source = "probe"

    suggestions = top_person_candidates(person, candidate_people, top_n=3) if not matched else []

    person_profile = build_person_profile(
        person_requested=person,
        matched_person=matched,
        match_source=match_source,
        candidate_suggestions=suggestions,
        probe_people=probe_people,
        warnings=warnings,
    )

    if person_profile.get("match_status") == "matched":
        checks.append(
            {
                "check": "Exact person match",
                "status": "PASS",
                "http": "-",
                "details": f"Matched via {match_source}",
            }
        )
    else:
        checks.append(
            {
                "check": "Exact person match",
                "status": "WARN",
                "http": "-",
                "details": "Exact name not found; candidate suggestions returned.",
            }
        )

    technologies = extract_technologies(account, probe_payloads)
    if technologies:
        checks.append(
            {
                "check": "Technologies",
                "status": "PASS",
                "http": "-",
                "details": f"Technology records: {len(technologies)}",
            }
        )
    else:
        warnings.append("No technologies returned from ProConnect sources.")
        checks.append(
            {
                "check": "Technologies",
                "status": "WARN",
                "http": "-",
                "details": "No technologies found; returned empty list.",
            }
        )

    stakeholder_payload["account_context"] = build_account_context(account)
    stakeholder_payload["projects"] = build_projects_section(account)
    stakeholder_payload["opportunities"] = build_opportunities_section(account)
    stakeholder_payload["key_buyers"] = build_key_buyers_section(account)
    stakeholder_payload["org_chart"] = {"items": org_chart_items}
    stakeholder_payload["technologies"] = {"items": technologies}
    stakeholder_payload["person_profile"] = person_profile
    stakeholder_payload["research_inputs"] = research_inputs
    stakeholder_payload["provenance"] = build_provenance(stakeholder_payload, probe_payloads)

    person_resolution = {
        "status": person_profile.get("match_status"),
        "match_source": match_source,
        "matched_person": person_profile.get("matched_person"),
        "candidate_suggestions": person_profile.get("candidate_suggestions"),
    }

    status = derive_status(checks=checks, errors=errors, warnings=warnings)
    return {
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "company_resolution": company_resolution,
        "person_resolution": person_resolution,
        "account_summary": account_summary,
        "stakeholder_payload": stakeholder_payload,
    }


def derive_status(checks: List[Dict[str, Any]], errors: List[str], warnings: List[str]) -> str:
    if errors or any(item.get("status") == "FAIL" for item in checks):
        return "FAIL"
    if warnings or any(item.get("status") == "WARN" for item in checks):
        return "WARN"
    return "PASS"


def default_stakeholder_payload(person: str, research_inputs: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "account_context": {
            "account_id": None,
            "company_name": None,
            "industry": None,
            "website": None,
            "ticker": None,
            "zoom_info_account_id": None,
            "worked_before": False,
            "company_summary_raw": None,
            "company_summary_concise": None,
        },
        "projects": {
            "items": [],
            "total_projects": 0,
            "solutions_list": [],
        },
        "opportunities": {
            "items": [],
        },
        "key_buyers": {
            "items": [],
        },
        "org_chart": {
            "items": [],
        },
        "technologies": {
            "items": [],
        },
        "person_profile": {
            "person_requested": person,
            "match_status": "not_found",
            "matched_person": None,
            "title_salesforce": None,
            "title_external": None,
            "location": None,
            "in_salesforce": None,
            "protiviti_alumni": None,
            "contact_at_robert_half": None,
            "past_job_experience": [],
            "education": [],
            "candidate_suggestions": [],
        },
        "research_inputs": research_inputs,
        "provenance": {},
    }


def build_account_context(account: Dict[str, Any]) -> Dict[str, Any]:
    projects = account.get("project") if isinstance(account.get("project"), list) else []
    number_of_project = to_int(account.get("numberOfProject"))
    worked_before = bool((number_of_project and number_of_project > 0) or projects)
    raw_summary = first_non_empty(account, ["companyDescription", "description"])
    concise = concise_summary(raw_summary)

    return {
        "account_id": account.get("id"),
        "company_name": account.get("name"),
        "industry": account.get("industry"),
        "website": account.get("websiteUrl"),
        "ticker": account.get("tickerSymbol"),
        "zoom_info_account_id": account.get("zoomInfoAccountId"),
        "worked_before": worked_before,
        "company_summary_raw": raw_summary,
        "company_summary_concise": concise,
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
                "project_name": first_non_empty(project, ["name", "projectName", "budgetKey"]),
                "year_ended_or_status": first_non_empty(project, ["endedDate", "projectStatus", "yearEnded"]),
                "solution": solution,
                "emd": first_non_empty(project, ["engagementManagingDirector", "emd"]),
                "em": first_non_empty(project, ["engagementManager", "em"]),
            }
        )

    total_projects = to_int(account.get("numberOfProject"))
    if total_projects is None:
        total_projects = len(items)

    if not solutions:
        for opp_key in ["allOpportunity", "openOpportunity"]:
            opps = account.get(opp_key)
            if not isinstance(opps, list):
                continue
            for opp in opps:
                if isinstance(opp, dict):
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
    if not isinstance(opportunities, list):
        opportunities = []

    items: List[Dict[str, Any]] = []
    for opp in opportunities:
        if not isinstance(opp, dict):
            continue
        items.append(
            {
                "opportunity": first_non_empty(opp, ["name", "opportunity", "opportunityName"]),
                "close_date": first_non_empty(opp, ["opportunityCloseDate", "closeDate"]),
                "md_d": first_non_empty(opp, ["opportunityManagingDirector", "md", "director"]),
                "primary_key_buyer": first_non_empty(opp, ["primaryKeyBuyer"]),
                "solution": first_non_empty(opp, ["solution"]),
                "service_name": first_non_empty(opp, ["serviceOffering", "serviceName"]),
                "stage": first_non_empty(opp, ["opportunityStage", "stage"]),
                "em": first_non_empty(opp, ["engagementManager"]),
            }
        )

    return {"items": items}


def build_key_buyers_section(account: Dict[str, Any]) -> Dict[str, Any]:
    key_buyers = account.get("keyBuyers")
    if not isinstance(key_buyers, list):
        key_buyers = []

    items: List[Dict[str, Any]] = []
    for buyer in key_buyers:
        if not isinstance(buyer, dict):
            continue
        items.append(
            {
                "name": full_person_name(buyer),
                "title": first_non_empty(buyer, ["title"]),
                "wins_5y": to_int(first_non_empty(buyer, ["numberOfWins", "wins", "winCount"])),
                "last_opportunity_won_date": first_non_empty(
                    buyer,
                    ["lastOpportunityWonDate", "lastWinDate"],
                ),
            }
        )
    return {"items": items}


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

    deduped_people = dedupe_people(people)
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

    param_templates: List[Dict[str, Any]] = []
    if account_id:
        param_templates.append({"accountId": account_id})
    if zoom_info_account_id:
        param_templates.append({"zoomInfoAccountId": zoom_info_account_id})
    if account_id and zoom_info_account_id:
        param_templates.append({"accountId": account_id, "zoomInfoAccountId": zoom_info_account_id})

    unique_templates = dedupe_param_templates(param_templates)
    if not unique_templates:
        return payloads, warnings

    for endpoint in PROBE_ENDPOINT_ALLOWLIST:
        auth_blocked = False
        for params in unique_templates:
            if auth_blocked:
                break
            response = client.get_endpoint(
                endpoint=endpoint,
                params=params,
                retry_on_5xx=1,
                retry_delay_seconds=0.25,
                stop_on_auth=True,
            )

            payloads.append(
                {
                    "endpoint": endpoint,
                    "params": params,
                    "status_code": response.get("status_code"),
                    "success": response.get("success"),
                    "data": response.get("data"),
                }
            )

            status_code = response.get("status_code")
            if response.get("auth_blocked") or status_code in {401, 403}:
                auth_blocked = True
                warnings.append(f"Probe endpoint {endpoint} blocked by authorization ({status_code}).")
            elif not response.get("success"):
                warnings.append(f"Probe endpoint {endpoint} failed with status {status_code}.")

    return payloads, warnings


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

    deduped = dedupe_people(people)
    for person in deduped:
        person.setdefault("_source", "probe")
    return deduped


def build_person_profile(
    person_requested: str,
    matched_person: Optional[Dict[str, Any]],
    match_source: Optional[str],
    candidate_suggestions: List[Dict[str, Any]],
    probe_people: List[Dict[str, Any]],
    warnings: List[str],
) -> Dict[str, Any]:
    profile = {
        "person_requested": person_requested,
        "match_status": "matched" if matched_person else "not_found",
        "matched_person": matched_person,
        "title_salesforce": None,
        "title_external": None,
        "location": None,
        "in_salesforce": None,
        "protiviti_alumni": None,
        "contact_at_robert_half": None,
        "past_job_experience": [],
        "education": [],
        "candidate_suggestions": candidate_suggestions,
    }

    if not matched_person:
        return profile

    merged = dict(matched_person)
    probe_overlay = find_probe_overlay(matched_person.get("name"), probe_people)
    if probe_overlay:
        for key, value in probe_overlay.items():
            if key not in merged or merged.get(key) in (None, "", []):
                merged[key] = value

    profile["matched_person"] = {
        "name": merged.get("name"),
        "title": merged.get("title"),
        "source": match_source,
        "score": merged.get("score", 1.0),
    }

    profile["title_salesforce"] = first_non_empty(merged, ["titleSalesforce", "salesforceTitle", "title"])
    profile["title_external"] = first_non_empty(merged, ["titleExternal", "externalTitle"])
    profile["location"] = first_non_empty(merged, ["location"])
    profile["in_salesforce"] = to_bool(first_non_empty(merged, ["isInSalesforce", "inSalesforce"]))
    profile["protiviti_alumni"] = to_bool(first_non_empty(merged, ["isProtivitiAlumni", "protivitiAlumni"]))
    profile["contact_at_robert_half"] = to_bool(
        first_non_empty(merged, ["hasRoberthalfContact", "contactAtRobertHalf"])
    )
    profile["past_job_experience"] = to_list(first_non_empty(merged, ["pastJobExperience", "pastJobs"]))
    profile["education"] = to_list(first_non_empty(merged, ["education", "educationList"]))

    profile_fields = [
        profile["title_salesforce"],
        profile["title_external"],
        profile["location"],
        profile["in_salesforce"],
        profile["protiviti_alumni"],
        profile["contact_at_robert_half"],
    ]
    if not any(value not in (None, "", []) for value in profile_fields) and not profile["past_job_experience"] and not profile["education"]:
        warnings.append("Person profile fields were unavailable from ProConnect sources.")

    return profile


def extract_technologies(account: Dict[str, Any], probe_payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    account_tech = extract_technologies_from_node(account)
    records.extend(account_tech)

    for payload in probe_payloads:
        endpoint = payload.get("endpoint") or "probe"
        for item in extract_technologies_from_node(payload.get("data")):
            if item.get("source") is None:
                item["source"] = f"probe:{endpoint}"
            records.append(item)

    return dedupe_simple_records(records, keys=["technology", "website"])


def build_provenance(payload: Dict[str, Any], probe_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    account_context = payload.get("account_context", {})
    projects = payload.get("projects", {})
    opportunities = payload.get("opportunities", {})
    key_buyers = payload.get("key_buyers", {})
    org_chart = payload.get("org_chart", {})
    technologies = payload.get("technologies", {})
    person_profile = payload.get("person_profile", {})
    research_inputs = payload.get("research_inputs", {})

    tech_source = "proconnect_account_or_probe" if probe_payloads else "proconnect_account"
    return {
        "account_context": {
            "account_id": prov("proconnect_account", present(account_context.get("account_id"))),
            "company_name": prov("proconnect_account", present(account_context.get("company_name"))),
            "industry": prov("proconnect_account", present(account_context.get("industry"))),
            "website": prov("proconnect_account", present(account_context.get("website"))),
            "ticker": prov("proconnect_account", present(account_context.get("ticker"))),
            "zoom_info_account_id": prov("proconnect_account", present(account_context.get("zoom_info_account_id"))),
            "worked_before": prov("derived", present(account_context.get("worked_before"))),
            "company_summary_raw": prov("proconnect_account", present(account_context.get("company_summary_raw"))),
            "company_summary_concise": prov("derived", present(account_context.get("company_summary_concise"))),
        },
        "projects": {
            "items": prov("proconnect_account", present(projects.get("items"))),
            "total_projects": prov("proconnect_account", present(projects.get("total_projects"))),
            "solutions_list": prov("derived", present(projects.get("solutions_list"))),
        },
        "opportunities": {
            "items": prov("proconnect_account", present(opportunities.get("items"))),
        },
        "key_buyers": {
            "items": prov("proconnect_account", present(key_buyers.get("items"))),
        },
        "org_chart": {
            "items": prov("proconnect_orgchart", present(org_chart.get("items"))),
        },
        "technologies": {
            "items": prov(tech_source, present(technologies.get("items"))),
        },
        "person_profile": {
            "match_status": prov("derived", present(person_profile.get("match_status"))),
            "matched_person": prov("derived", present(person_profile.get("matched_person"))),
            "title_salesforce": prov("proconnect_or_probe", present(person_profile.get("title_salesforce"))),
            "title_external": prov("proconnect_or_probe", present(person_profile.get("title_external"))),
            "location": prov("proconnect_or_probe", present(person_profile.get("location"))),
            "in_salesforce": prov("proconnect_or_probe", present(person_profile.get("in_salesforce"))),
            "protiviti_alumni": prov("proconnect_or_probe", present(person_profile.get("protiviti_alumni"))),
            "contact_at_robert_half": prov(
                "proconnect_or_probe",
                present(person_profile.get("contact_at_robert_half")),
            ),
            "past_job_experience": prov("proconnect_or_probe", present(person_profile.get("past_job_experience"))),
            "education": prov("proconnect_or_probe", present(person_profile.get("education"))),
            "candidate_suggestions": prov("derived", present(person_profile.get("candidate_suggestions"))),
        },
        "research_inputs": {
            "provided_name": prov("research_input", present(research_inputs.get("provided_name"))),
            "provided_role": prov("research_input", present(research_inputs.get("provided_role"))),
            "potential_service_needs": prov("research_input", present(research_inputs.get("potential_service_needs"))),
            "simulated_research_datapoint": prov(
                "research_input",
                present(research_inputs.get("simulated_research_datapoint")),
            ),
        },
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
                "id": buyer.get("id"),
                "name": full_person_name(buyer),
                "title": buyer.get("title"),
                "linkedinUrl": buyer.get("linkedinUrl"),
                "emailAddress": buyer.get("emailAddress"),
                "_source": "key_buyers",
            }
        )
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
    }


def find_probe_overlay(name: Optional[str], probe_people: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    for record in probe_people:
        candidate = full_person_name(record)
        if candidate and exact_name_equals(name, candidate):
            return record
    return None


def extract_technologies_from_node(node: Any) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    direct_candidates = []
    if isinstance(node, dict):
        for key in ["technologies", "technology", "companyTechnologies", "technologiesUsed"]:
            if key in node:
                direct_candidates.append(node.get(key))

    for candidate in direct_candidates:
        results.extend(parse_technology_container(candidate, source="proconnect_account"))

    for obj in iter_dict_nodes(node):
        for key, value in obj.items():
            if "technolog" not in str(key).lower():
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
    concise = " ".join(trimmed[:max(max_sentences, 1)])
    if len(concise) > 600:
        concise = concise[:597].rstrip() + "..."
    return concise


def first_non_empty(payload: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


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
    return [str(value).strip()] if str(value).strip() else []


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
    for record in records:
        fingerprint = tuple(str(record.get(key) or "").strip().lower() for key in keys)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(record)
    return deduped


def present(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, str) and not value.strip():
        return "missing"
    if isinstance(value, list) and len(value) == 0:
        return "missing"
    return "present"


def prov(source: str, status: str, confidence: float = 1.0) -> Dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "confidence": round(float(confidence), 4),
    }
