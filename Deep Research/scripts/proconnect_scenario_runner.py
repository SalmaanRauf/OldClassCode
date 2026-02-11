#!/usr/bin/env python3
"""Run multiple ProConnect local test scenarios and aggregate results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from proconnect_client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    ProConnectClient,
    default_output_dir,
    load_extra_headers,
    make_run_id,
    print_check_table,
    redact_token,
    resolve_bearer_token,
    token_health_summary,
    utc_timestamp,
    write_json_artifact,
)
from proconnect_lookup_logic import build_account_summary, resolve_company_and_account, resolve_person_tiered
from proconnect_stakeholder_payload import load_research_inputs, run_stakeholder_case


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run predefined ProConnect scenarios.")
    parser.add_argument(
        "--scenarios-file",
        required=True,
        help="Path to JSON file containing a top-level 'scenarios' array (or a direct array).",
    )
    parser.add_argument(
        "--payload-type",
        choices=["legacy", "stakeholder"],
        default="legacy",
        help="Scenario execution mode. Omit to preserve legacy behavior.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="ProConnect base URL.")
    parser.add_argument("--token", default=None, help="Bearer token (with or without 'Bearer ' prefix).")
    parser.add_argument(
        "--token-file",
        default=None,
        help="Optional token file path (raw token or 'Bearer <token>'). Defaults to ./token.txt when present.",
    )
    parser.add_argument("--extra-headers-file", default=None, help="Optional JSON object file for extra headers.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds.")
    parser.add_argument("--output-dir", default=default_output_dir(), help="Directory for JSON artifacts.")
    return parser.parse_args()


def load_scenarios(path: str) -> List[Dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        scenarios = payload.get("scenarios")
        if isinstance(scenarios, list):
            return [item for item in scenarios if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("Scenario file must be a JSON array or object with a 'scenarios' array.")


def execute_legacy_scenario(
    scenario: Dict[str, Any],
    base_url: str,
    base_token: str,
    timeout_seconds: int,
    extra_headers: Dict[str, str],
) -> Dict[str, Any]:
    scenario_name = str(scenario.get("name") or "Unnamed Scenario")
    scenario_token_raw = scenario.get("token")
    token = base_token if not scenario_token_raw else str(scenario_token_raw)

    client = ProConnectClient(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=timeout_seconds,
        extra_headers=extra_headers,
    )

    checks: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []
    company_resolution: Optional[Dict[str, Any]] = None
    account_summary: Optional[Dict[str, Any]] = None
    person_resolution: Dict[str, Any] = {"status": "not_requested", "match_source": None, "matched_person": None}

    account_id = scenario.get("account_id")
    if account_id:
        response = client.get_account_by_id(str(account_id))
        if response.get("success"):
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            account_summary = build_account_summary(data)
            checks.append(
                {
                    "check": "Direct account",
                    "status": "PASS",
                    "http": response.get("status_code"),
                    "details": f"Loaded {data.get('name', 'account')}",
                }
            )
        else:
            checks.append(
                {
                    "check": "Direct account",
                    "status": "FAIL",
                    "http": response.get("status_code"),
                    "details": response.get("error") or "Request failed",
                }
            )
            errors.append("Direct account call failed.")

    company = scenario.get("company")
    person = scenario.get("person")
    department = scenario.get("department")

    if company:
        company_resolution, account, resolution_errors = resolve_company_and_account(
            client=client,
            company_name=str(company),
            key_person_name=str(person) if person else None,
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
                    "details": "Search failed",
                }
            )

        if account:
            account_summary = build_account_summary(account)
        else:
            errors.append("No account returned from company resolution.")

        person_resolution = resolve_person_tiered(
            client=client,
            account=account,
            person_name=str(person) if person else None,
            department_hint=str(department) if department else None,
        )

        person_status = person_resolution.get("status")
        if person_status == "matched":
            matched = person_resolution.get("matched_person") or {}
            checks.append(
                {
                    "check": "Person lookup",
                    "status": "PASS",
                    "http": "-",
                    "details": f"Matched {matched.get('name', 'unknown')}",
                }
            )
        elif person_status == "not_found":
            warnings.append("Person not found for requested company.")
            checks.append(
                {
                    "check": "Person lookup",
                    "status": "WARN",
                    "http": "-",
                    "details": "Person not found",
                }
            )
        else:
            checks.append(
                {
                    "check": "Person lookup",
                    "status": "PASS",
                    "http": "-",
                    "details": "Not requested",
                }
            )

    status = derive_status(checks=checks, errors=errors, warnings=warnings)
    return {
        "name": scenario_name,
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "http_calls": client.http_calls,
        "company_resolution": company_resolution,
        "person_resolution": person_resolution,
        "account_summary": account_summary,
    }


def execute_stakeholder_scenario(
    scenario: Dict[str, Any],
    base_url: str,
    base_token: str,
    timeout_seconds: int,
    extra_headers: Dict[str, str],
) -> Dict[str, Any]:
    scenario_name = str(scenario.get("name") or "Unnamed Scenario")
    scenario_token_raw = scenario.get("token")
    token = base_token if not scenario_token_raw else str(scenario_token_raw)

    client = ProConnectClient(
        base_url=base_url,
        bearer_token=token,
        timeout_seconds=timeout_seconds,
        extra_headers=extra_headers,
    )

    company = scenario.get("company")
    person = scenario.get("person")
    if not company or not person:
        checks = [
            {
                "check": "Scenario input validation",
                "status": "FAIL",
                "http": "-",
                "details": "Stakeholder scenarios require both 'company' and 'person'.",
            }
        ]
        return {
            "name": scenario_name,
            "status": "FAIL",
            "checks": checks,
            "warnings": [],
            "errors": ["Missing required stakeholder scenario fields: company/person."],
            "http_calls": client.http_calls,
            "company_resolution": None,
            "person_resolution": {"status": "not_found"},
            "account_summary": None,
            "stakeholder_payload": None,
        }

    research_inputs = scenario.get("research_inputs")
    if not isinstance(research_inputs, dict):
        research_inputs_file = scenario.get("research_inputs_file")
        if research_inputs_file:
            try:
                research_inputs = load_research_inputs(str(research_inputs_file))
            except Exception as exc:
                research_inputs = None
                input_warning = f"Could not load research_inputs_file '{research_inputs_file}': {exc}"
            else:
                input_warning = None
        else:
            input_warning = None
    else:
        input_warning = None

    result = run_stakeholder_case(
        client=client,
        company=str(company),
        person=str(person),
        department_hint=str(scenario.get("department")) if scenario.get("department") else None,
        account_id_override=str(scenario.get("account_id")) if scenario.get("account_id") else None,
        research_inputs=research_inputs,
        enable_probes=True,
    )

    if input_warning:
        result.setdefault("warnings", []).append(input_warning)
        if result.get("status") == "PASS":
            result["status"] = "WARN"

    return {
        "name": scenario_name,
        "status": result.get("status", "FAIL"),
        "checks": result.get("checks", []),
        "warnings": result.get("warnings", []),
        "errors": result.get("errors", []),
        "http_calls": client.http_calls,
        "company_resolution": result.get("company_resolution"),
        "person_resolution": result.get("person_resolution"),
        "account_summary": result.get("account_summary"),
        "stakeholder_payload": result.get("stakeholder_payload"),
    }


def execute_scenario(
    scenario: Dict[str, Any],
    base_url: str,
    base_token: str,
    timeout_seconds: int,
    extra_headers: Dict[str, str],
    default_payload_type: str,
) -> Dict[str, Any]:
    payload_type = str(scenario.get("payload_type") or default_payload_type or "legacy").strip().lower()
    if payload_type == "stakeholder":
        result = execute_stakeholder_scenario(
            scenario=scenario,
            base_url=base_url,
            base_token=base_token,
            timeout_seconds=timeout_seconds,
            extra_headers=extra_headers,
        )
    else:
        result = execute_legacy_scenario(
            scenario=scenario,
            base_url=base_url,
            base_token=base_token,
            timeout_seconds=timeout_seconds,
            extra_headers=extra_headers,
        )

    expected_status = scenario.get("expected_status")
    expected_value = str(expected_status).upper() if expected_status else None
    actual_value = str(result.get("status") or "FAIL").upper()
    status_match = True if expected_value is None else (actual_value == expected_value)
    unexpected_failure = expected_value is None and actual_value == "FAIL"

    result["payload_type"] = payload_type
    result["expected_status"] = expected_value
    result["status_match"] = status_match
    result["unexpected_failure"] = unexpected_failure
    return result


def derive_status(checks: List[Dict[str, Any]], errors: List[str], warnings: List[str]) -> str:
    if errors or any(item.get("status") == "FAIL" for item in checks):
        return "FAIL"
    if warnings or any(item.get("status") == "WARN" for item in checks):
        return "WARN"
    return "PASS"


def main() -> int:
    args = parse_args()

    try:
        token, token_source = resolve_bearer_token(args.token, args.token_file)
    except Exception as exc:
        print(f"Token resolution failed: {exc}")
        return 1

    token_health = token_health_summary(token)

    try:
        extra_headers = load_extra_headers(args.extra_headers_file)
    except Exception as exc:
        print(f"Failed to load extra headers: {exc}")
        return 1

    try:
        scenarios = load_scenarios(args.scenarios_file)
    except Exception as exc:
        print(f"Failed to load scenarios: {exc}")
        return 1

    if not scenarios:
        print("No scenarios found.")
        return 1

    scenario_results: List[Dict[str, Any]] = []
    all_http_calls: List[Dict[str, Any]] = []
    all_errors: List[str] = []
    all_warnings: List[str] = []

    for index, scenario in enumerate(scenarios, start=1):
        result = execute_scenario(
            scenario=scenario,
            base_url=args.base_url,
            base_token=token,
            timeout_seconds=args.timeout,
            extra_headers=extra_headers,
            default_payload_type=args.payload_type,
        )
        scenario_results.append(result)
        all_http_calls.extend(result.get("http_calls", []))

        scenario_name = result.get("name", f"Scenario #{index}")
        for error in result.get("errors", []):
            all_errors.append(f"{scenario_name}: {error}")
        for warning in result.get("warnings", []):
            all_warnings.append(f"{scenario_name}: {warning}")

    rows_for_console = []
    for result in scenario_results:
        checks = result.get("checks") or []
        failed_checks = sum(1 for check in checks if check.get("status") == "FAIL")
        warn_checks = sum(1 for check in checks if check.get("status") == "WARN")
        expected_status = result.get("expected_status")
        expected_label = expected_status if expected_status else "n/a"
        match_label = "match" if result.get("status_match", True) else "mismatch"
        rows_for_console.append(
            {
                "check": result.get("name", "Scenario"),
                "status": result.get("status"),
                "http": "-",
                "details": f"type={result.get('payload_type')}, expected={expected_label} ({match_label}), fail={failed_checks}, warn={warn_checks}",
            }
        )

    has_mismatch = any(not result.get("status_match", True) for result in scenario_results)
    has_unexpected_failure = any(result.get("unexpected_failure", False) for result in scenario_results)
    any_warn = any(result.get("status") == "WARN" for result in scenario_results)

    if has_mismatch or has_unexpected_failure:
        overall_status = "FAIL"
    elif any_warn:
        overall_status = "WARN"
    else:
        overall_status = "PASS"

    matched_count = sum(1 for result in scenario_results if (result.get("person_resolution") or {}).get("status") == "matched")
    person_requested_count = sum(
        1
        for result in scenario_results
        if (result.get("person_resolution") or {}).get("status") in {"matched", "not_found"}
    )

    run_id = make_run_id()
    payload = {
        "run_id": run_id,
        "timestamp_utc": utc_timestamp(),
        "inputs_redacted": {
            "base_url": args.base_url,
            "scenarios_file": str(args.scenarios_file),
            "scenario_count": len(scenarios),
            "payload_type": args.payload_type,
            "token_source": token_source,
            "token_preview": redact_token(token),
            "token_file": args.token_file,
            "extra_header_keys": sorted(extra_headers.keys()),
            "timeout_seconds": args.timeout,
        },
        "http_calls": all_http_calls,
        "company_resolution": {
            "scenarios_with_company": sum(1 for item in scenarios if item.get("company")),
            "resolved_accounts": sum(1 for result in scenario_results if result.get("account_summary")),
        },
        "person_resolution": {
            "person_requested": person_requested_count,
            "person_matched": matched_count,
            "person_not_found": person_requested_count - matched_count,
        },
        "account_summary": {
            "accounts_with_summary": sum(1 for result in scenario_results if result.get("account_summary")),
        },
        "scenario_results": scenario_results,
        "warnings": all_warnings,
        "errors": all_errors,
        "pass_fail": {
            "status": overall_status,
            "token_health": token_health,
            "has_status_mismatch": has_mismatch,
            "has_unexpected_failure": has_unexpected_failure,
            "scenario_status_counts": {
                "PASS": sum(1 for result in scenario_results if result.get("status") == "PASS"),
                "WARN": sum(1 for result in scenario_results if result.get("status") == "WARN"),
                "FAIL": sum(1 for result in scenario_results if result.get("status") == "FAIL"),
            },
            "expectation_match_counts": {
                "matched": sum(1 for result in scenario_results if result.get("status_match", True)),
                "mismatched": sum(1 for result in scenario_results if not result.get("status_match", True)),
            },
        },
    }

    artifact_path = write_json_artifact(args.output_dir, "proconnect_scenarios", payload)

    print("\nProConnect Scenario Runner")
    print("==========================")
    print_check_table(rows_for_console)
    for warning in token_health.get("warnings", []):
        print(f"Token warning: {warning}")
    for warning in all_warnings:
        print(f"Warning: {warning}")
    print(f"\nArtifact: {artifact_path}")
    print(f"Overall: {overall_status}")

    return 1 if overall_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
