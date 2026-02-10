#!/usr/bin/env python3
"""Dynamic company/person ProConnect retrieval test harness."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dynamic company/person ProConnect lookup tests.")
    parser.add_argument("--company", required=True, help="Target company name to resolve dynamically.")
    parser.add_argument("--person", default=None, help="Optional person to resolve at the target company.")
    parser.add_argument("--department", default=None, help="Optional department hint for person lookup.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="ProConnect base URL.")
    parser.add_argument("--token", default=None, help="Bearer token (with or without 'Bearer ' prefix).")
    parser.add_argument("--extra-headers-file", default=None, help="Optional JSON object file for extra request headers.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout in seconds.")
    parser.add_argument("--output-dir", default=default_output_dir(), help="Directory for JSON artifacts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        token, token_source = resolve_bearer_token(args.token)
    except Exception as exc:
        print(f"Token resolution failed: {exc}")
        return 1

    token_health = token_health_summary(token)

    try:
        extra_headers = load_extra_headers(args.extra_headers_file)
    except Exception as exc:
        print(f"Failed to load extra headers: {exc}")
        return 1

    client = ProConnectClient(
        base_url=args.base_url,
        bearer_token=token,
        timeout_seconds=args.timeout,
        extra_headers=extra_headers,
    )

    company_resolution, account, resolution_errors = resolve_company_and_account(
        client=client,
        company_name=args.company,
        key_person_name=args.person,
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
                "details": "Search endpoint failed.",
            }
        )

    if company_resolution.get("resolved_account") and account:
        account_summary = build_account_summary(account)
        checks.append(
            {
                "check": "Account resolution",
                "status": "PASS",
                "http": company_resolution.get("account_fetch_status_code"),
                "details": f"Resolved account: {account.get('name', 'unknown')}",
            }
        )
    else:
        account_summary = None
        checks.append(
            {
                "check": "Account resolution",
                "status": "FAIL",
                "http": company_resolution.get("account_fetch_status_code"),
                "details": "No account resolved from prospects candidates.",
            }
        )
        errors.append("Account resolution failed.")

    person_resolution = resolve_person_tiered(
        client=client,
        account=account,
        person_name=args.person,
        department_hint=args.department,
    )

    person_status = person_resolution.get("status")
    if person_status == "not_requested":
        checks.append(
            {
                "check": "Person lookup",
                "status": "PASS",
                "http": "-",
                "details": "Person not requested; skipped by design.",
            }
        )
    elif person_status == "matched":
        matched = person_resolution.get("matched_person") or {}
        checks.append(
            {
                "check": "Person lookup",
                "status": "PASS",
                "http": "-",
                "details": f"Matched '{matched.get('name', 'unknown')}' via {person_resolution.get('match_source')}",
            }
        )
    else:
        checks.append(
            {
                "check": "Person lookup",
                "status": "WARN",
                "http": "-",
                "details": "Person not found; company context still returned.",
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
            "company": args.company,
            "person": args.person,
            "department": args.department,
            "token_source": token_source,
            "token_preview": redact_token(token),
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

    artifact_path = write_json_artifact(args.output_dir, "proconnect_company_person", payload)

    print("\nProConnect Company/Person Test")
    print("===============================")
    print_check_table(checks)
    for warning in token_health.get("warnings", []):
        print(f"Token warning: {warning}")
    print(f"\nArtifact: {artifact_path}")
    print(f"Overall: {overall_status}")

    return 1 if overall_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
