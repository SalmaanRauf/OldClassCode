#!/usr/bin/env python3
"""Run stakeholder-aligned ProConnect payload extraction locally."""

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
from proconnect_stakeholder_payload import load_research_inputs, run_stakeholder_case


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ProConnect stakeholder payload extraction.")
    parser.add_argument("--company", required=True, help="Target company name.")
    parser.add_argument("--person", required=True, help="Exact person name to resolve.")
    parser.add_argument("--department", default=None, help="Optional department hint.")
    parser.add_argument("--account-id", default=None, help="Optional direct account-id override.")
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
    parser.add_argument(
        "--research-inputs-file",
        default=None,
        help="Optional JSON file for workflow-only fields (provided name/role/service needs/simulated datapoint).",
    )
    return parser.parse_args()


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
        research_inputs = load_research_inputs(args.research_inputs_file)
    except Exception as exc:
        print(f"Failed to load research inputs: {exc}")
        return 1

    client = ProConnectClient(
        base_url=args.base_url,
        bearer_token=token,
        timeout_seconds=args.timeout,
        extra_headers=extra_headers,
    )

    result = run_stakeholder_case(
        client=client,
        company=args.company,
        person=args.person,
        department_hint=args.department,
        account_id_override=args.account_id,
        research_inputs=research_inputs,
        enable_probes=True,
    )

    checks: List[Dict[str, Any]] = result.get("checks", [])
    warnings: List[str] = result.get("warnings", [])
    errors: List[str] = result.get("errors", [])
    overall_status = result.get("status", "FAIL")

    run_id = make_run_id()
    payload = {
        "run_id": run_id,
        "timestamp_utc": utc_timestamp(),
        "inputs_redacted": {
            "base_url": args.base_url,
            "company": args.company,
            "person": args.person,
            "department": args.department,
            "account_id": args.account_id,
            "token_source": token_source,
            "token_preview": redact_token(token),
            "token_file": args.token_file,
            "research_inputs_file": args.research_inputs_file,
            "extra_header_keys": sorted(extra_headers.keys()),
            "timeout_seconds": args.timeout,
        },
        "http_calls": client.http_calls,
        "stakeholder_payload": result.get("stakeholder_payload"),
        "warnings": warnings,
        "errors": errors,
        "pass_fail": {
            "status": overall_status,
            "checks": checks,
            "token_health": token_health,
        },
        "company_resolution": result.get("company_resolution"),
        "person_resolution": result.get("person_resolution"),
        "account_summary": result.get("account_summary"),
    }

    artifact_path = write_json_artifact(args.output_dir, "proconnect_stakeholder", payload)

    print("\nProConnect Stakeholder Test")
    print("===========================")
    print_check_table(checks)
    for warning in token_health.get("warnings", []):
        print(f"Token warning: {warning}")
    for warning in warnings:
        print(f"Warning: {warning}")
    print(f"\nArtifact: {artifact_path}")
    print(f"Overall: {overall_status}")

    return 1 if overall_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
