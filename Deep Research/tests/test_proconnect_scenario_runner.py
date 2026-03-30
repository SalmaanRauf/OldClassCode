"""
Tests for ProConnect scenario-runner evidence assertions.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import scripts.proconnect_scenario_runner as scenario_runner  # noqa: E402


def test_execute_scenario_fails_when_stakeholder_evidence_expectations_are_missed(monkeypatch) -> None:
    monkeypatch.setattr(
        scenario_runner,
        "run_stakeholder_case",
        lambda **_: {
            "status": "WARN",
            "checks": [
                {
                    "check": "Exact person match",
                    "status": "PASS",
                    "http": "-",
                    "details": "Matched via from_key_buyers",
                }
            ],
            "warnings": [],
            "errors": [],
            "person_resolution": {
                "status": "matched",
                "match_source": "from_key_buyers",
                "matched_person": {
                    "name": "Jennifer Brady",
                    "project_count": 0,
                    "win_count": 1,
                },
            },
            "transition_payload": {
                "person_profile": {
                    "match_status": "matched",
                    "matched_person": {
                        "name": "Jennifer Brady",
                        "project_count": 0,
                        "win_count": 1,
                    },
                    "project_count": 0,
                    "win_count": 1,
                },
                "to_company_context": {
                    "org_chart": {
                        "items": [
                            {"executive_name": "One"},
                            {"executive_name": "Two"},
                            {"executive_name": "Three"},
                            {"executive_name": "Four"},
                            {"executive_name": "Five"},
                        ]
                    }
                },
            },
            "to_company_resolution": {},
            "from_company_resolution": {},
            "to_account_summary": {},
            "from_account_summary": {},
        },
    )

    result = scenario_runner.execute_scenario(
        scenario={
            "name": "jennifer_regression_guard",
            "payload_type": "stakeholder",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "person": "Jennifer Brady",
            "expected_status": "WARN",
            "expected_org_chart_min": 10,
            "expected_project_count_min": 1,
            "expected_win_count_min": 1,
            "expected_match_source_in": ["from_key_buyers", "person_search"],
            "expected_matched_name": "Jennifer Brady",
            "forbid_matched_names": ["Jennifer A Brady"],
        },
        base_url="https://proconnect.protiviti.com",
        base_token="Bearer test-token",
        timeout_seconds=30,
        extra_headers={},
        default_payload_type="stakeholder",
    )

    assert result["status"] == "FAIL"
    assert result["status_match"] is False
    assert any(check["check"] == "Evidence expectations" and check["status"] == "FAIL" for check in result["checks"])
    assert any("expected_org_chart_min" in error for error in result["errors"])
    assert any("expected_project_count_min" in error for error in result["errors"])
