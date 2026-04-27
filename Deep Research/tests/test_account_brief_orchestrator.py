"""
Tests for the account-brief three-stage orchestrator.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.account_brief_synthesizer import (  # noqa: E402
    AccountBriefSynthesisResult,
    SynthesizedSuggestedPlay,
)
from services.account_brief_orchestrator import AccountBriefOrchestrator  # noqa: E402
from services.account_research_input import AccountResearchInput  # noqa: E402


@pytest.mark.asyncio
async def test_account_brief_orchestrator_runs_three_stage_pipeline() -> None:
    call_order = []

    class FakeProConnectService:
        def collect_account_research(self, account_name: str):
            call_order.append(("proconnect", account_name))
            return {
                "account_resolution": {"requested_name": account_name, "resolved_name": "BAE Systems, Inc."},
                "account_status": {"summary": "No known ProConnect work found."},
                "coverage_gaps": ["True 3-level reporting hierarchy is not available."],
            }

    class FakePublicResearchOrchestrator:
        async def run(self, *, company_name: str, focus_hint=None, industry=None, progress_cb=None):
            call_order.append(("public_research", company_name, focus_hint, industry))

            class FakeResult:
                deep_research_response = {
                    "summary": "Public defense contractor overview.",
                    "sections": [{"title": "Why Now", "content": "Modernization pressure is visible."}],
                    "coverage_gaps": ["Public leadership coverage is partial."],
                    "citations": [{"title": "Example", "url": "https://example.com"}],
                }

            return FakeResult()

    class FakeSynthesizer:
        def build_input(self, **kwargs):
            call_order.append(("build_input", kwargs["request_context"]["account_name"]))
            return {
                "request_context": kwargs["request_context"],
                "proconnect_summary": kwargs["proconnect_summary"],
                "deep_research_summary": kwargs["deep_research_summary"],
                "coverage_gaps": kwargs["coverage_gaps"],
            }

        async def synthesize(self, synthesis_input):
            call_order.append(("synthesize", synthesis_input["request_context"]["account_name"]))
            return AccountBriefSynthesisResult(
                account_summary="BAE Systems shows public modernization pressure with limited known internal coverage.",
                signal_summary=["Public defense modernization priorities are visible."],
                opportunity_summary=["Cyber modernization advisory"],
                suggested_plays=[
                    SynthesizedSuggestedPlay(
                        play="Lead with cyber modernization.",
                        why_now="Public modernization signals are already visible.",
                    )
                ],
                takeaway="Use this as an opening account brief.",
            )

    orchestrator = AccountBriefOrchestrator(
        proconnect_service=FakeProConnectService(),
        public_research_orchestrator=FakePublicResearchOrchestrator(),
        synthesizer=FakeSynthesizer(),
    )

    response = await orchestrator.run(
        AccountResearchInput(
            account_name="BAE Systems",
            raw_input="BAE Systems",
            focus_hint="Metro DC",
        )
    )

    assert response["type"] == "account_brief"
    assert response["company"] == "BAE Systems, Inc."
    assert response["synthesis"]["headline"].startswith("BAE Systems shows")
    assert response["proconnect_summary"]["account_status"]["summary"] == "No known ProConnect work found."
    assert response["deep_research_summary"]["summary"] == "Public defense contractor overview."
    assert response["citations"] == [{"title": "Example", "url": "https://example.com"}]
    assert call_order == [
        ("proconnect", "BAE Systems"),
        ("public_research", "BAE Systems, Inc.", "Metro DC", None),
        ("build_input", "BAE Systems, Inc."),
        ("synthesize", "BAE Systems, Inc."),
    ]


@pytest.mark.asyncio
async def test_account_brief_orchestrator_sanitizes_internal_focus_hint_for_public_research() -> None:
    captured_public_focus_hints = []
    captured_synthesis_contexts = []

    class FakeProConnectService:
        def collect_account_research(self, account_name: str):
            return {
                "account_resolution": {"resolved_name": account_name},
                "account_status": {"summary": "No known ProConnect work found."},
                "coverage_gaps": [],
            }

    class FakePublicResearchOrchestrator:
        async def run(self, *, company_name: str, focus_hint=None, industry=None, progress_cb=None):
            captured_public_focus_hints.append(focus_hint)

            class FakeResult:
                deep_research_response = {"coverage_gaps": [], "citations": []}

            return FakeResult()

    class FakeSynthesizer:
        def build_input(self, **kwargs):
            captured_synthesis_contexts.append(kwargs["request_context"])
            return kwargs

        async def synthesize(self, synthesis_input):
            return AccountBriefSynthesisResult(
                account_summary="Brief",
                signal_summary=["Signals"],
                opportunity_summary=["Opportunity"],
                suggested_plays=[],
                takeaway="Takeaway",
            )

    orchestrator = AccountBriefOrchestrator(
        proconnect_service=FakeProConnectService(),
        public_research_orchestrator=FakePublicResearchOrchestrator(),
        synthesizer=FakeSynthesizer(),
    )

    await orchestrator.run(
        AccountResearchInput(
            account_name="Danaher",
            raw_input="Danaher, check PRO/RHI relationship gaps",
            focus_hint="check PRO/RHI relationship gaps",
        )
    )

    assert captured_public_focus_hints == [None]
    assert captured_synthesis_contexts[0]["focus_hint"] == "check PRO/RHI relationship gaps"


@pytest.mark.asyncio
async def test_account_brief_orchestrator_combines_coverage_gaps_from_both_sources() -> None:
    class FakeProConnectService:
        def collect_account_research(self, account_name: str):
            return {
                "coverage_gaps": ["True 3-level reporting hierarchy is not available."],
            }

    class FakePublicResearchOrchestrator:
        async def run(self, **kwargs):
            class FakeResult:
                deep_research_response = {
                    "coverage_gaps": ["Public leadership coverage is partial."],
                    "citations": [],
                }

            return FakeResult()

    class FakeSynthesizer:
        def build_input(self, **kwargs):
            return kwargs

        async def synthesize(self, synthesis_input):
            return AccountBriefSynthesisResult(
                account_summary="Brief",
                signal_summary=["Signals"],
                opportunity_summary=["Opportunity"],
                suggested_plays=[],
                takeaway="Takeaway",
            )

    orchestrator = AccountBriefOrchestrator(
        proconnect_service=FakeProConnectService(),
        public_research_orchestrator=FakePublicResearchOrchestrator(),
        synthesizer=FakeSynthesizer(),
    )

    response = await orchestrator.run(
        AccountResearchInput(account_name="CareFirst", raw_input="CareFirst")
    )

    assert response["coverage_gaps"] == [
        "True 3-level reporting hierarchy is not available.",
        "Public leadership coverage is partial.",
    ]


@pytest.mark.asyncio
async def test_account_brief_orchestrator_emits_progress_events() -> None:
    events = []

    class FakeProConnectService:
        def collect_account_research(self, account_name: str):
            return {"coverage_gaps": []}

    class FakePublicResearchOrchestrator:
        async def run(self, **kwargs):
            class FakeResult:
                deep_research_response = {"coverage_gaps": [], "citations": []}

            return FakeResult()

    class FakeSynthesizer:
        def build_input(self, **kwargs):
            return kwargs

        async def synthesize(self, synthesis_input):
            return AccountBriefSynthesisResult(
                account_summary="Brief",
                signal_summary=["Signals"],
                opportunity_summary=["Opportunity"],
                suggested_plays=[],
                takeaway="Takeaway",
            )

    async def progress_cb(event):
        events.append(event)

    orchestrator = AccountBriefOrchestrator(
        proconnect_service=FakeProConnectService(),
        public_research_orchestrator=FakePublicResearchOrchestrator(),
        synthesizer=FakeSynthesizer(),
    )

    await orchestrator.run(
        AccountResearchInput(account_name="CareFirst", raw_input="CareFirst"),
        progress_cb=progress_cb,
    )

    assert [event["stage"] for event in events] == [
        "resolving_account",
        "collecting_proconnect_context",
        "running_public_research",
        "synthesizing_account_brief",
        "account_brief_complete",
    ]
