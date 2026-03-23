"""
Tests for the shared credentials lookup runner.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.credentials_agent import CredentialsAgent  # noqa: E402
from models.bd_schemas import (  # noqa: E402
    CredentialMatch,
    CredentialsBatchDiagnostics,
    CredentialsLookupDiagnostics,
    CredentialsResponse,
    Opportunity,
)
from services.credentials_lookup_runner import CredentialsLookupRunner  # noqa: E402


def _opportunity(title: str) -> Opportunity:
    return Opportunity(
        title=title,
        scope=f"{title} scope",
        confidence="High",
    )


def _diagnostics(title: str, lookup_status: str, *, match_count: int = 0, error_message: str = ""):
    return CredentialsLookupDiagnostics(
        opportunity_title=title,
        sector="Financial Services",
        query_text=f"Query for {title}",
        raw_response_text="{}",
        parse_outcome="json_parsed_with_matches" if lookup_status == "Matched" else "diagnostics_missing",
        lookup_status=lookup_status,  # type: ignore[arg-type]
        error_message=error_message or None,
        duration_ms=12.5,
        match_count=match_count,
    )


def _matched_response(title: str, *, diagnostics: bool = True) -> CredentialsResponse:
    payload = {
        "opportunity_title": title,
        "matches": [
            CredentialMatch(
                title=f"{title} Credential",
                client_challenge="Problem statement",
                value_provided="Delivered value",
                url="https://ishare.protiviti.com/cred/123",
            )
        ],
        "no_matches_found": False,
        "lookup_status": "Matched",
    }
    if diagnostics:
        payload["diagnostics"] = _diagnostics(title, "Matched", match_count=1)
    return CredentialsResponse(**payload)


def _no_match_response(title: str, *, diagnostics: bool = True) -> CredentialsResponse:
    payload = {
        "opportunity_title": title,
        "matches": [],
        "no_matches_found": True,
        "lookup_status": "No Match",
    }
    if diagnostics:
        payload["diagnostics"] = _diagnostics(title, "No Match", match_count=0)
    return CredentialsResponse(**payload)


@pytest.mark.asyncio
async def test_runner_serial_lookup_retries_timeout_failures_and_collects_diagnostics():
    agent = MagicMock(spec=CredentialsAgent)
    agent.find_credentials = AsyncMock(
        side_effect=[
            CredentialsResponse(
                opportunity_title="CMMC Program",
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Request timed out",
                diagnostics=_diagnostics(
                    "CMMC Program",
                    "Lookup Failed",
                    error_message="Request timed out",
                ),
            ),
            _matched_response("CMMC Program"),
            _no_match_response("Model Risk"),
        ]
    )
    agent.find_credentials_batch = AsyncMock()

    runner = CredentialsLookupRunner(credentials_agent=agent)
    result = await runner.run([
        _opportunity("CMMC Program"),
        _opportunity("Model Risk"),
    ], sector="Financial Services")

    assert agent.find_credentials.await_count == 3
    assert agent.find_credentials_batch.await_count == 0
    assert result.batch_diagnostics is None
    assert result.lookups_executed_count == 2
    assert result.status_counts == {"Matched": 1, "No Match": 1, "Lookup Failed": 0}
    assert result.results["CMMC Program"].lookup_status == "Matched"
    assert result.results["Model Risk"].lookup_status == "No Match"
    assert result.diagnostics["CMMC Program"].lookup_status == "Matched"
    assert result.diagnostics["CMMC Program"].match_count == 1
    assert result.diagnostics["Model Risk"].lookup_status == "No Match"


@pytest.mark.asyncio
async def test_runner_batched_lookup_uses_batch_mode_and_backfills_missing_diagnostics():
    agent = MagicMock(spec=CredentialsAgent)
    agent.find_credentials = AsyncMock()
    agent.find_credentials_batch = AsyncMock(
        return_value=(
            {
                "AI Governance": _matched_response("AI Governance", diagnostics=False),
                "Controls Uplift": _no_match_response("Controls Uplift", diagnostics=False),
            },
            CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=2,
                lookup_count_returned=2,
                duration_ms=33.0,
                query_text="batch query",
                raw_response_text='{"results":[...]}' ,
                parse_outcome="batch_json_parsed",
            ),
        )
    )

    runner = CredentialsLookupRunner(
        credentials_agent=agent,
        lookup_mode="batched_single_call",
    )
    result = await runner.run([
        _opportunity("AI Governance"),
        _opportunity("Controls Uplift"),
    ], sector="Financial Services")

    assert agent.find_credentials.await_count == 0
    assert agent.find_credentials_batch.await_count == 1
    assert result.batch_diagnostics is not None
    assert result.batch_diagnostics.invoked is True
    assert result.lookups_executed_count == 2
    assert result.status_counts == {"Matched": 1, "No Match": 1, "Lookup Failed": 0}
    assert result.diagnostics["AI Governance"].parse_outcome == "diagnostics_missing"
    assert result.diagnostics["AI Governance"].match_count == 1
    assert result.diagnostics["Controls Uplift"].lookup_status == "No Match"


@pytest.mark.asyncio
async def test_runner_skips_lookup_when_no_opportunities_are_provided():
    agent = MagicMock(spec=CredentialsAgent)
    agent.find_credentials = AsyncMock()
    agent.find_credentials_batch = AsyncMock()

    runner = CredentialsLookupRunner(credentials_agent=agent)
    result = await runner.run([], sector="Financial Services")

    assert agent.find_credentials.await_count == 0
    assert agent.find_credentials_batch.await_count == 0
    assert result.results == {}
    assert result.diagnostics == {}
    assert result.batch_diagnostics is None
    assert result.status_counts == {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
    assert result.lookups_executed_count == 0
