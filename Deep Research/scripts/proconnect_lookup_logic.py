#!/usr/bin/env python3
"""Local lookup logic for company/person resolution against ProConnect."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # pragma: no cover - import style depends on entrypoint
    from .proconnect_client import ProConnectClient
except ImportError:  # pragma: no cover
    from proconnect_client import ProConnectClient

DEPARTMENT_TO_SFDC_FUNCTIONS: Dict[str, List[str]] = {
    "C-Suite": [
        "Executive",
        "Marketing & Sales",
        "Accounting and Finance",
        "Human Resource Management",
        "IT - Systems and Applications",
        "Legal / General Counsel",
        "Innovation & Digital",
        "Operations",
        "Strategy and Corporate Development",
    ],
    "Finance": [
        "Accounting and Finance",
        "Compliance",
        "Risk Management",
        "IT - Systems and Applications",
        "Purchasing and Procurement",
        "Strategy and Corporate Development",
        "Customer Service / Support",
    ],
    "Human Resources": ["Human Resource Management", "IT - Systems and Applications"],
    "Sales": [
        "Marketing & Sales",
        "Customer Service / Support",
        "Operations",
        "Accounting and Finance",
        "Strategy and Corporate Development",
    ],
    "Operations": [
        "Customer Service / Support",
        "Purchasing and Procurement",
        "Operations",
        "Strategy and Corporate Development",
        "Legal / General Counsel",
        "Risk Management",
    ],
    "Information Technology": [
        "IT - Systems and Applications",
        "Customer Service / Support",
        "Data and Analytics",
        "Innovation & Digital",
        "Security and Privacy",
        "Purchasing and Procurement",
    ],
    "Engineering & Technical": [
        "Data and Analytics",
        "IT - Systems and Applications",
        "Innovation & Digital",
        "Research and Development (R&D)",
    ],
    "Marketing": [
        "Marketing & Sales",
        "Innovation & Digital",
        "Strategy and Corporate Development",
        "Customer Service / Support",
    ],
    "Legal": [
        "Compliance",
        "Security and Privacy",
        "Legal / General Counsel",
        "Research and Development (R&D)",
        "Strategy and Corporate Development",
    ],
    "Medical & Health": ["Research and Development (R&D)", "Operations", "IT - Systems and Applications"],
    "Other": ["All"],
}


def resolve_company_and_account(
    client: ProConnectClient,
    company_name: str,
    key_person_name: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], List[str]]:
    """Resolve best account candidate for a company via prospects search."""
    errors: List[str] = []

    search_response = client.search_prospects(company_name)
    result: Dict[str, Any] = {
        "query": company_name,
        "search_status_code": search_response.get("status_code"),
        "search_success": search_response.get("success", False),
        "candidate_count": 0,
        "candidates": [],
        "selected_candidate": None,
        "selected_score": None,
        "account_fetch_status_code": None,
        "resolved_account": False,
    }

    if not search_response.get("success"):
        errors.append(
            f"Prospects search failed for '{company_name}' with status {search_response.get('status_code')}"
        )
        return result, None, errors

    candidates = extract_account_candidates(search_response.get("data"))
    scored: List[Dict[str, Any]] = []
    for candidate in candidates:
        company_score = score_company_candidate(company_name, candidate)
        person_boost = 0.05 if key_person_name and name_match_score(key_person_name, candidate.get("name", "")) >= 0.85 else 0.0
        total_score = min(company_score + person_boost, 1.0)
        augmented = dict(candidate)
        augmented["score"] = round(total_score, 4)
        scored.append(augmented)

    scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    result["candidate_count"] = len(scored)
    result["candidates"] = scored[:10]

    if not scored:
        errors.append(f"No prospects candidates returned for '{company_name}'.")
        return result, None, errors

    selected = scored[0]
    result["selected_candidate"] = selected
    result["selected_score"] = selected.get("score")

    account_id = selected.get("accountId")
    if not account_id:
        errors.append("Top candidate did not include an accountId.")
        return result, None, errors

    account_response = client.get_account_by_id(account_id)
    result["account_fetch_status_code"] = account_response.get("status_code")

    if not account_response.get("success"):
        errors.append(
            f"Account retrieval failed for accountId '{account_id}' with status {account_response.get('status_code')}"
        )
        return result, None, errors

    account_data = account_response.get("data") if isinstance(account_response.get("data"), dict) else None
    result["resolved_account"] = bool(account_data)

    return result, account_data, errors


def resolve_person_tiered(
    client: ProConnectClient,
    account: Optional[Dict[str, Any]],
    person_name: Optional[str],
    department_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve person in tiers: key buyers -> exec team -> department sweeps."""
    output: Dict[str, Any] = {
        "status": "not_requested",
        "match_source": None,
        "matched_person": None,
        "checked": {
            "key_buyers": 0,
            "executive_team": 0,
            "department_people": 0,
            "department_calls": 0,
            "person_search_candidates": 0,
        },
        "warnings": [],
    }

    if not person_name:
        return output

    output["status"] = "not_found"
    if not account:
        output["warnings"].append("No account context available for person lookup.")
        return output

    key_buyers = account.get("keyBuyers") or []
    key_buyer_match = match_person_in_key_buyers(person_name, key_buyers)
    output["checked"]["key_buyers"] = len(key_buyers)
    if key_buyer_match:
        output["status"] = "matched"
        output["match_source"] = "key_buyers"
        output["matched_person"] = key_buyer_match
        return output

    zoom_info_account_id = get_zoom_info_account_id(account)
    if not zoom_info_account_id:
        output["warnings"].append("Account does not include zoomInfoAccountId; org chart lookup skipped.")
        return output

    exec_team_result = fetch_executive_team(client, zoom_info_account_id)
    output["checked"]["executive_team"] = len(exec_team_result["employees"])
    exec_match = match_person_in_people(person_name, exec_team_result["employees"])
    if exec_match:
        output["status"] = "matched"
        output["match_source"] = "executive_team"
        output["matched_person"] = exec_match
        return output

    departments_to_search: List[str]
    if department_hint and department_hint in DEPARTMENT_TO_SFDC_FUNCTIONS:
        departments_to_search = [department_hint]
    else:
        departments_to_search = list(DEPARTMENT_TO_SFDC_FUNCTIONS.keys())

    merged_people: List[Dict[str, Any]] = []
    department_calls = 0
    for department in departments_to_search:
        dept_result = fetch_department_people(client, zoom_info_account_id, department)
        merged_people.extend(dept_result["employees"])
        department_calls += dept_result["department_calls"]

    if department_hint and output["status"] != "matched":
        remaining = [dept for dept in DEPARTMENT_TO_SFDC_FUNCTIONS if dept != department_hint]
        for department in remaining:
            dept_result = fetch_department_people(client, zoom_info_account_id, department)
            merged_people.extend(dept_result["employees"])
            department_calls += dept_result["department_calls"]

    deduped_people = dedupe_people(merged_people)
    output["checked"]["department_people"] = len(deduped_people)
    output["checked"]["department_calls"] = department_calls

    dept_match = match_person_in_people(person_name, deduped_people)
    if dept_match:
        output["status"] = "matched"
        output["match_source"] = "department_sweep"
        output["matched_person"] = dept_match
        return output

    account_id = str(account.get("id") or "").strip()
    if not account_id:
        return output

    person_search_response = client.search_prospects(person_name)
    if not person_search_response.get("success"):
        output["warnings"].append(
            f"Person search fallback failed with status {person_search_response.get('status_code')}."
        )
        return output

    person_candidates = extract_person_candidates(person_search_response.get("data"))
    output["checked"]["person_search_candidates"] = len(person_candidates)

    exact_account_matches = [
        candidate
        for candidate in person_candidates
        if str(candidate.get("accountId") or "").strip() == account_id
        and exact_name_equals(person_name, full_person_name(candidate))
    ]
    if not exact_account_matches:
        return output

    selected = sorted(
        exact_account_matches,
        key=lambda candidate: (
            1 if exact_name_equals(person_name, full_person_name(candidate)) else 0,
            1 if same_first_last_name(person_name, full_person_name(candidate)) else 0,
            name_match_score(person_name, full_person_name(candidate)),
        ),
        reverse=True,
    )[0]

    output["status"] = "matched"
    output["match_source"] = "person_search"
    output["matched_person"] = {
        "id": first_non_empty(selected, ["contactId", "id"]),
        "name": full_person_name(selected),
        "title": selected.get("title"),
        "department": selected.get("department") or selected.get("function"),
        "sfdcJobFunction": selected.get("sfdcJobFunction"),
        "linkedinUrl": selected.get("linkedinUrl"),
        "emailAddress": selected.get("emailAddress"),
        "score": 1.0,
        "accountId": selected.get("accountId"),
    }

    return output


def fetch_executive_team(client: ProConnectClient, zoom_info_account_id: str) -> Dict[str, Any]:
    response = client.get_org_chart(
        zoom_info_account_id=zoom_info_account_id,
        department="C-Suite",
        sfdc_job_function="Executive",
        page=None,
        size=None,
    )
    employees = extract_employees(response.get("data")) if response.get("success") else []
    return {
        "status_code": response.get("status_code"),
        "success": response.get("success", False),
        "employees": employees,
    }


def fetch_department_people(
    client: ProConnectClient,
    zoom_info_account_id: str,
    department: str,
) -> Dict[str, Any]:
    employees: List[Dict[str, Any]] = []
    department_calls = 0

    functions = DEPARTMENT_TO_SFDC_FUNCTIONS.get(department, [])
    for job_function in functions:
        department_calls += 1
        response = client.get_org_chart(
            zoom_info_account_id=zoom_info_account_id,
            department=department,
            sfdc_job_function=job_function,
            page=1,
            size=3,
        )
        if response.get("success"):
            employees.extend(extract_employees(response.get("data")))

    return {
        "department": department,
        "job_functions": functions,
        "employees": dedupe_people(employees),
        "department_calls": department_calls,
    }


def build_account_summary(account: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not account:
        return None

    open_opps = account.get("openOpportunity") or []
    all_opps = account.get("allOpportunity") or []
    key_buyers = account.get("keyBuyers") or []

    return {
        "id": account.get("id"),
        "name": account.get("name"),
        "zoomInfoAccountId": account.get("zoomInfoAccountId"),
        "tickerSymbol": account.get("tickerSymbol"),
        "industry": account.get("industry"),
        "websiteUrl": account.get("websiteUrl"),
        "errorMessage": account.get("errorMessage"),
        "numberOfOpenOpportunity": account.get("numberOfOpenOpportunity", len(open_opps)),
        "numberOfAllOpportunity": account.get("numberOfAllOpportunity", len(all_opps)),
        "keyBuyerCount": len(key_buyers),
    }


def extract_account_candidates(payload: Any) -> List[Dict[str, Any]]:
    value = []
    if isinstance(payload, dict):
        raw_value = payload.get("value")
        if isinstance(raw_value, list):
            value = raw_value

    candidates: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        document = item.get("document")
        if not isinstance(document, dict):
            continue
        candidates.append(
            {
                "accountId": document.get("accountId"),
                "companyName": document.get("companyName"),
                "name": document.get("name"),
                "companyTicker": document.get("companyTicker"),
                "companyUrl": document.get("companyUrl"),
                "companyDescription": document.get("companyDescription"),
            }
        )
    return candidates


def extract_person_candidates(payload: Any) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return candidates

    for item in payload.get("value") or []:
        if not isinstance(item, dict):
            continue
        document = item.get("document") if isinstance(item.get("document"), dict) else item
        if not isinstance(document, dict):
            continue
        name = first_non_empty(document, ["name", "contactName", "fullName"])
        if not name:
            continue
        candidates.append(
            {
                "contactId": first_non_empty(document, ["contactId", "id"]),
                "accountId": first_non_empty(document, ["accountId", "sfdcAccountId"]),
                "name": name,
                "firstName": first_non_empty(document, ["firstName"]),
                "lastName": first_non_empty(document, ["lastName"]),
                "title": first_non_empty(document, ["title"]),
                "department": first_non_empty(document, ["department", "function"]),
                "function": first_non_empty(document, ["function"]),
                "sfdcJobFunction": first_non_empty(document, ["sfdcJobFunction"]),
                "linkedinUrl": first_non_empty(document, ["linkedinUrl", "linkedInUrl"]),
                "emailAddress": first_non_empty(document, ["emailAddress", "email"]),
            }
        )
    return candidates


def extract_employees(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    employees = payload.get("employees")
    if not isinstance(employees, list):
        return []
    return [item for item in employees if isinstance(item, dict)]


def get_zoom_info_account_id(account: Dict[str, Any]) -> Optional[str]:
    value = account.get("zoomInfoAccountId")
    if value is None:
        return None
    string_value = str(value).strip()
    return string_value or None


def score_company_candidate(query: str, candidate: Dict[str, Any]) -> float:
    company_name = str(candidate.get("companyName") or "")
    candidate_name = str(candidate.get("name") or "")

    score = max(
        name_match_score(query, company_name),
        name_match_score(query, candidate_name),
    )

    query_norm = normalize_text(query)
    if query_norm and query_norm in normalize_text(company_name):
        score = max(score, 0.95)

    return float(round(score, 4))


def match_person_in_key_buyers(person_name: str, key_buyers: Iterable[Any]) -> Optional[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in key_buyers:
        if not isinstance(item, dict):
            continue
        records.append(item)

    return _best_person_match(person_name, records, ["name"])


def match_person_in_people(person_name: str, people: Iterable[Any]) -> Optional[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in people:
        if isinstance(item, dict):
            records.append(item)

    return _best_person_match(person_name, records, ["name"])


def dedupe_people(people: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for person in people:
        identifier = (
            str(person.get("id") or ""),
            normalize_text(full_person_name(person)),
            normalize_text(str(person.get("title") or "")),
        )
        if identifier in seen:
            continue
        seen.add(identifier)
        result.append(person)
    return result


def _best_person_match(person_name: str, records: List[Dict[str, Any]], keys: List[str]) -> Optional[Dict[str, Any]]:
    best_score = 0.0
    best_record: Optional[Dict[str, Any]] = None
    best_option = ""
    best_exact = False
    best_first_last = False
    best_last_name = False

    for record in records:
        options = _record_name_options(record, keys)
        for option in options:
            score = name_match_score(person_name, option)
            exact = exact_name_equals(person_name, option)
            first_last = same_first_last_name(person_name, option)
            last_name = same_last_name(person_name, option)
            rank = (
                1 if exact else 0,
                1 if first_last else 0,
                1 if last_name else 0,
                score,
            )
            best_rank = (
                1 if best_exact else 0,
                1 if best_first_last else 0,
                1 if best_last_name else 0,
                best_score,
            )
            if rank > best_rank:
                best_score = score
                best_record = record
                best_option = option
                best_exact = exact
                best_first_last = first_last
                best_last_name = last_name

    if best_record is None:
        return None
    if best_exact or best_first_last:
        pass
    elif best_score < 0.72 or not best_last_name:
        return None

    normalized = {
        "id": best_record.get("id"),
        "name": full_person_name(best_record),
        "title": best_record.get("title"),
        "department": best_record.get("department") or best_record.get("function"),
        "sfdcJobFunction": best_record.get("sfdcJobFunction") or best_record.get("sfdcJobFunction"),
        "linkedinUrl": best_record.get("linkedinUrl"),
        "emailAddress": best_record.get("emailAddress"),
        "score": round(best_score if best_option else 0.0, 4),
    }
    return normalized


def _record_name_options(record: Dict[str, Any], keys: List[str]) -> List[str]:
    options: List[str] = []

    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            options.append(value.strip())

    first = record.get("firstName")
    last = record.get("lastName")
    if isinstance(first, str) and isinstance(last, str):
        full = f"{first.strip()} {last.strip()}".strip()
        if full:
            options.append(full)

    return options


def full_person_name(record: Dict[str, Any]) -> str:
    direct = record.get("name")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    first = record.get("firstName")
    last = record.get("lastName")
    if isinstance(first, str) or isinstance(last, str):
        return " ".join(part for part in [str(first or "").strip(), str(last or "").strip()] if part).strip()

    return ""


def name_match_score(target: str, candidate: str) -> float:
    t = normalize_text(target)
    c = normalize_text(candidate)
    if not t or not c:
        return 0.0
    if t == c:
        return 1.0
    if t in c or c in t:
        return 0.9

    t_tokens = set(t.split())
    c_tokens = set(c.split())
    overlap = len(t_tokens & c_tokens)
    token_score = overlap / max(len(t_tokens), 1)

    seq_score = SequenceMatcher(None, t, c).ratio()
    return max(token_score, seq_score)


def normalize_text(value: str) -> str:
    value = (value or "").lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_person_name(value: str) -> str:
    return normalize_text(value)


def first_last_name_key(value: str) -> Tuple[str, str]:
    tokens = normalize_person_name(value).split()
    if len(tokens) < 2:
        return ("", "")
    return (tokens[0], tokens[-1])


def exact_name_equals(left: str, right: str) -> bool:
    return bool(normalize_person_name(left) and normalize_person_name(left) == normalize_person_name(right))


def same_first_last_name(left: str, right: str) -> bool:
    left_key = first_last_name_key(left)
    right_key = first_last_name_key(right)
    return bool(left_key[0] and left_key == right_key)


def same_last_name(left: str, right: str) -> bool:
    left_key = first_last_name_key(left)
    right_key = first_last_name_key(right)
    return bool(left_key[1] and right_key[1] and left_key[1] == right_key[1])


def first_non_empty(payload: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def find_exact_person_match(person_name: str, people: Iterable[Any]) -> Optional[Dict[str, Any]]:
    for item in people:
        if not isinstance(item, dict):
            continue
        candidate_name = full_person_name(item)
        if not candidate_name:
            continue
        if exact_name_equals(person_name, candidate_name):
            return {
                "id": item.get("id"),
                "name": candidate_name,
                "title": item.get("title"),
                "department": item.get("department") or item.get("function"),
                "sfdcJobFunction": item.get("sfdcJobFunction"),
                "linkedinUrl": item.get("linkedinUrl"),
                "emailAddress": item.get("emailAddress"),
                "score": 1.0,
                "source": item.get("_source"),
            }
    return None


def top_person_candidates(person_name: str, people: Iterable[Any], top_n: int = 3) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    seen = set()

    for item in people:
        if not isinstance(item, dict):
            continue
        candidate_name = full_person_name(item)
        if not candidate_name:
            continue
        score = name_match_score(person_name, candidate_name)
        if score <= 0:
            continue

        key = (normalize_person_name(candidate_name), normalize_text(str(item.get("title") or "")))
        if key in seen:
            continue
        seen.add(key)

        ranked.append(
            {
                "name": candidate_name,
                "title": item.get("title"),
                "source": item.get("_source", "unknown"),
                "company_scope": item.get("_company_scope"),
                "linked_account_id": item.get("linked_account_id"),
                "score": round(score, 4),
            }
        )

    ranked.sort(key=lambda row: (row.get("score", 0.0), row.get("name", "")), reverse=True)
    return ranked[: max(int(top_n), 0)]
