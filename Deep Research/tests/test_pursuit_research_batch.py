"""
Tests for stakeholder pursuit-research batch runs.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pursuit_research_batch import (  # noqa: E402
    PursuitAccount,
    PursuitResearchBatchRunner,
    default_stakeholder_pursuit_accounts,
)


@pytest.mark.asyncio
async def test_batch_runner_writes_markdown_and_json_and_respects_proconnect_skip(tmp_path) -> None:
    calls = []

    class FakeOrchestrator:
        async def run(
            self,
            request,
            *,
            industry_key=None,
            progress_cb=None,
            use_proconnect=True,
            proconnect_skip_reason=None,
        ):
            calls.append(
                {
                    "account_name": request.account_name,
                    "focus_hint": request.focus_hint,
                    "industry_key": industry_key,
                    "use_proconnect": use_proconnect,
                    "proconnect_skip_reason": proconnect_skip_reason,
                }
            )
            return {
                "company": request.account_name,
                "proconnect_summary": {
                    "diagnostics": {"proconnect_skipped": not use_proconnect},
                    "known_protiviti_team": {},
                },
                "deep_research_summary": {
                    "summary": f"Fresh signals for {request.account_name}",
                    "citations": [{"title": "Source", "url": "https://example.com"}],
                },
                "synthesis": {
                    "headline": f"{request.account_name} pursuit brief",
                    "account_status_summary": "Public-only account run.",
                    "why_now": "Recent public signal.",
                    "relationship_posture": "ProConnect skipped.",
                    "buyer_posture": "Public buyer research required.",
                    "leadership_coverage_summary": "Public leadership coverage.",
                    "top_openings": ["Opening"],
                    "suggested_plays": ["Play"],
                    "key_gaps": [],
                    "takeaway": "Takeaway",
                },
                "coverage_gaps": [],
                "citations": [],
            }

    runner = PursuitResearchBatchRunner(
        output_dir=tmp_path,
        orchestrator_factory=lambda: FakeOrchestrator(),
        concurrency=1,
    )
    accounts = [
        PursuitAccount(
            account_name="BAE Systems",
            campaign="Metro DC Target Accounts",
            focus_hint="Fresh pursuit triggers.",
            use_proconnect=False,
            proconnect_skip_reason="Stakeholder identified no known work / no MSA.",
        ),
        PursuitAccount(
            account_name="Danaher",
            campaign="Enterprise Revenue Acceleration",
            focus_hint="Fresh pursuit triggers.",
            use_proconnect=True,
        ),
    ]

    summary = await runner.run(accounts)

    assert len(summary["results"]) == 2
    assert calls[0]["use_proconnect"] is False
    assert calls[0]["proconnect_skip_reason"] == "Stakeholder identified no known work / no MSA."
    assert calls[1]["use_proconnect"] is True

    for item in summary["results"]:
        assert item["status"] == "success"
        assert os.path.exists(item["json_path"])
        assert os.path.exists(item["markdown_path"])
        payload = json.loads(open(item["json_path"], encoding="utf-8").read())
        assert payload["company"] in {"BAE Systems", "Danaher"}
        assert "pursuit brief" in open(item["markdown_path"], encoding="utf-8").read()


def test_default_stakeholder_accounts_encode_known_proconnect_strategy() -> None:
    accounts = default_stakeholder_pursuit_accounts()
    by_name = {account.account_name: account for account in accounts}

    assert by_name["BAE Systems"].use_proconnect is False
    assert "no known work" in (by_name["BAE Systems"].proconnect_skip_reason or "").lower()
    assert by_name["Danaher"].use_proconnect is True
    assert "last 180 days" in by_name["BAE Systems"].focus_hint
    assert len(accounts) >= 15


@pytest.mark.asyncio
async def test_batch_runner_downgrades_mixed_industry_batches_to_sequential(tmp_path) -> None:
    class FakeOrchestrator:
        async def run(self, request, **kwargs):
            return {
                "company": request.account_name,
                "proconnect_summary": {"known_protiviti_team": {}, "diagnostics": {}},
                "deep_research_summary": {},
                "synthesis": {"headline": request.account_name},
            }

    runner = PursuitResearchBatchRunner(
        output_dir=tmp_path,
        orchestrator_factory=lambda: FakeOrchestrator(),
        concurrency=2,
    )
    summary = await runner.run(
        [
            PursuitAccount("BAE Systems", "Campaign", "Fresh", industry_key="defense"),
            PursuitAccount("Danaher", "Campaign", "Fresh", industry_key="general"),
        ]
    )

    assert summary["requested_concurrency"] == 2
    assert summary["concurrency"] == 1
