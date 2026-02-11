#!/usr/bin/env python3
"""Smoke test ProConnect endpoints with direct account check first."""

from __future__ import annotations

import argparse
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
from proconnect_lookup_logic import build_account_summary, get_zoom_info_account_id, resolve_company_and_account


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run standalone ProConnect smoke tests.")
    parser.add_argument("--account-id", default=None, help="Known account ID for direct /api/accounts/{id} check.")
    parser.add_argument("--search", default=None, help="Optional company string for /api/prospects search.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="ProConnect base URL.")
    parser.add_argument("--token", default=None, help="Bearer token (with or without 'Bearer ' prefix).")
    parser.add_argument(
        "--token-file",
        default=None,
        help="Optional token file path (raw token or 'Bearer <token>'). Defaults to ./token.txt when present.",
    )
    parser.add_argument("--extra-headers-file", default=None, help="Optional JSON object file for extra request headers.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds.")
    parser.add_argument("--output-dir", default=default_output_dir(), help="Directory for JSON artifacts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []
    account_summary: Optional[Dict[str, Any]] = None
    company_resolution: Optional[Dict[str, Any]] = None
    person_resolution: Dict[str, Any] = {"status": "not_requested", "match_source": None, "matched_person": None}

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

    if not args.account_id and not args.search:
        print("Nothing to test. Provide --account-id and/or --search.")
        return 1

    client = ProConnectClient(
        base_url=args.base_url,
        bearer_token=token,
        timeout_seconds=args.timeout,
        extra_headers=extra_headers,
    )

    if args.account_id:
        account_response = client.get_account_by_id(args.account_id)
        if account_response.get("success"):
            account_data = account_response.get("data") if isinstance(account_response.get("data"), dict) else {}
            account_summary = build_account_summary(account_data)
            checks.append(
                {
                    "check": "Direct account retrieval",
                    "status": "PASS",
                    "http": account_response.get("status_code"),
                    "details": f"Account '{account_data.get('name', 'unknown')}' loaded.",
                }
            )

            zoom_info_id = get_zoom_info_account_id(account_data)
            if zoom_info_id:
                exec_response = client.get_org_chart(
                    zoom_info_account_id=zoom_info_id,
                    department="C-Suite",
                    sfdc_job_function="Executive",
                    page=None,
                    size=None,
                )
                if exec_response.get("success"):
                    employees = []
                    data = exec_response.get("data")
                    if isinstance(data, dict) and isinstance(data.get("employees"), list):
                        employees = data.get("employees")
                    checks.append(
                        {
                            "check": "Executive org chart",
                            "status": "PASS",
                            "http": exec_response.get("status_code"),
                            "details": f"Returned {len(employees)} employees.",
                        }
                    )
                else:
                    checks.append(
                        {
                            "check": "Executive org chart",
                            "status": "FAIL",
                            "http": exec_response.get("status_code"),
                            "details": exec_response.get("error") or "Request failed.",
                        }
                    )
                    errors.append("Executive org chart request failed.")
            else:
                checks.append(
                    {
                        "check": "Executive org chart",
                        "status": "WARN",
                        "http": "-",
                        "details": "zoomInfoAccountId missing; org chart skipped.",
                    }
                )
        else:
            checks.append(
                {
                    "check": "Direct account retrieval",
                    "status": "FAIL",
                    "http": account_response.get("status_code"),
                    "details": account_response.get("error") or "Request failed.",
                }
            )
            errors.append("Direct account retrieval failed.")

            if account_response.get("status_code") in {401, 403}:
                user_response = client.get_user()
                if user_response.get("success"):
                    checks.append(
                        {
                            "check": "User endpoint auth check",
                            "status": "PASS",
                            "http": user_response.get("status_code"),
                            "details": "Token is valid for /api/user.",
                        }
                    )
                else:
                    checks.append(
                        {
                            "check": "User endpoint auth check",
                            "status": "FAIL",
                            "http": user_response.get("status_code"),
                            "details": user_response.get("error") or "User endpoint failed.",
                        }
                    )
                    errors.append("User endpoint auth check failed.")

    if args.search:
        resolution, searched_account, resolution_errors = resolve_company_and_account(client, args.search)
        company_resolution = resolution
        errors.extend(resolution_errors)

        if resolution.get("search_success"):
            checks.append(
                {
                    "check": "Prospects search",
                    "status": "PASS",
                    "http": resolution.get("search_status_code"),
                    "details": f"Candidates: {resolution.get('candidate_count', 0)}",
                }
            )
        else:
            checks.append(
                {
                    "check": "Prospects search",
                    "status": "FAIL",
                    "http": resolution.get("search_status_code"),
                    "details": "Search endpoint failed.",
                }
            )

        if resolution.get("resolved_account"):
            checks.append(
                {
                    "check": "Resolved account fetch",
                    "status": "PASS",
                    "http": resolution.get("account_fetch_status_code"),
                    "details": "Selected candidate account loaded.",
                }
            )
            if account_summary is None and isinstance(searched_account, dict):
                account_summary = build_account_summary(searched_account)
        else:
            checks.append(
                {
                    "check": "Resolved account fetch",
                    "status": "WARN",
                    "http": resolution.get("account_fetch_status_code"),
                    "details": "No account resolved from search candidates.",
                }
            )

    statuses = {row.get("status") for row in checks}
    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARN" in statuses:
        overall_status = "WARN"
    else:
        overall_status = "PASS"

    run_id = make_run_id()
    payload = {
        "run_id": run_id,
        "timestamp_utc": utc_timestamp(),
        "inputs_redacted": {
            "base_url": args.base_url,
            "account_id": args.account_id,
            "search": args.search,
            "token_source": token_source,
            "token_preview": redact_token(token),
            "token_file": args.token_file,
            "extra_header_keys": sorted(extra_headers.keys()),
            "timeout_seconds": args.timeout,
        },
        "http_calls": client.http_calls,
        "company_resolution": company_resolution,
        "person_resolution": person_resolution,
        "account_summary": account_summary,
        "errors": errors,
        "pass_fail": {
            "status": overall_status,
            "checks": checks,
            "token_health": token_health,
        },
    }

    artifact_path = write_json_artifact(args.output_dir, "proconnect_smoke", payload)

    print("\nProConnect Smoke Test")
    print("======================")
    print_check_table(checks)
    for warning in token_health.get("warnings", []):
        print(f"Token warning: {warning}")
    print(f"\nArtifact: {artifact_path}")
    print(f"Overall: {overall_status}")

    return 1 if overall_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
