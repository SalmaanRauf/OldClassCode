"""
Tests for the transition workflow orchestrator.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import MDReport
from models.transition_schemas import (
    AccountResolution,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.transition_playbook_orchestrator import TransitionPlaybookOrchestrator
from services.transition_prompt_builder import TransitionPromptPackage


def _sample_request() -> TransitionRequest:
    return TransitionRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        synthetic_scenario=True,
    )


def _sample_preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=_sample_request(),
        person_resolution=TransitionPersonResolution(
            requested_name="Jennifer Brady",
            match_status="matched",
            matched_name="Jennifer Brady",
            matched_title="Senior Director of Technology Risk",
            match_source="from_key_buyers",
            direct_person_evidence=True,
        ),
        from_account=AccountResolution(
            company_name="Capital One Financial Corporation",
            resolved=True,
            account_id="00130000000BYU2AAO",
        ),
        to_account=AccountResolution(
            company_name="Federal National Mortgage Association (Fannie Mae)",
            resolved=True,
            account_id="00130000000BYUIAA4",
        ),
        quick_indicators=QuickRelationshipIndicators(
            warm_intro_path_available=True,
            source_worked_before=True,
            destination_worked_before=True,
            source_key_buyer_count=24,
            destination_key_buyer_count=14,
            source_connected_colleague_count=5,
            destination_connected_colleague_count=1,
        ),
        inferred_industry="financial_services",
        suggested_research_prompt="Research likely CIO opportunities at Fannie Mae.",
    )


@pytest.mark.asyncio
async def test_build_preflight_returns_transition_preflight() -> None:
    preflight = _sample_preflight()

    class FakeProConnectService:
        def build_preflight(self, request, **kwargs):
            assert request.person_name == "Jennifer Brady"
            return preflight

    orchestrator = TransitionPlaybookOrchestrator(
        proconnect_service=FakeProConnectService(),
        prompt_builder=None,
        deep_research_runner=None,
        bd_orchestrator=None,
    )

    result = await orchestrator.build_preflight(_sample_request())

    assert result is preflight
    assert result.person_resolution.match_status == "matched"
    assert result.to_account.account_id == "00130000000BYUIAA4"


@pytest.mark.asyncio
async def test_full_run_executes_preflight_research_bd_and_actioning_in_order() -> None:
    call_order: list[str] = []
    preflight = _sample_preflight()

    class FakeProConnectService:
        def load_transition_case(self, request, **kwargs):
            call_order.append("load_transition_case")
            return {"transition_payload": {"stub": True}}

        def build_preflight(self, request, **kwargs):
            call_order.append("build_preflight")
            return preflight

        def build_actioning_context(self, request, **kwargs):
            call_order.append("build_actioning_context")
            return {"warm_paths": ["Bernadette Norrington"]}

    class FakePromptBuilder:
        def build(self, preflight_obj):
            call_order.append("build_prompt")
            assert preflight_obj is preflight
            return TransitionPromptPackage(
                industry_key="financial_services",
                system_prompt="SYSTEM",
                user_prompt="USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        call_order.append("run_deep_research")
        assert query == "USER PROMPT"
        assert industry == "financial_services"
        assert kwargs["instructions_override"] == "SYSTEM"
        if progress_callback:
            await progress_callback("Found signal", {"status": "in_progress", "citation_count": 3})
        return {
            "type": "deep_research",
            "summary": "Deep research summary",
            "sections": [
                {
                    "title": "Opportunity Scan",
                    "content": "Potential opportunities identified.",
                    "citations": [{"title": "Source", "url": "https://example.com"}],
                }
            ],
            "citations": [{"title": "Source", "url": "https://example.com"}],
            "metadata": {},
        }

    class FakeBDOrchestrator:
        async def run(
            self,
            trigger,
            deep_research_output=None,
            structured_source_urls=None,
            structured_evidence_map=None,
            progress_cb=None,
        ):
            call_order.append("run_bd")
            assert trigger.sector == "Financial Services"
            assert "Deep research summary" in deep_research_output
            assert structured_source_urls == ["https://example.com"]
            assert "section_source_map" in structured_evidence_map
            if progress_cb:
                await progress_cb("Validating with Credentials Agent...")
                await progress_cb("Synthesizing MD Report...")
            return MDReport(
                trigger_summary="Transition playbook",
                executive_summary="Compact summary",
                generated_at=datetime.now(),
            )

    orchestrator = TransitionPlaybookOrchestrator(
        proconnect_service=FakeProConnectService(),
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
        bd_orchestrator=FakeBDOrchestrator(),
    )

    result = await orchestrator.run_transition_playbook(_sample_request())

    assert call_order == [
        "load_transition_case",
        "build_preflight",
        "build_prompt",
        "run_deep_research",
        "run_bd",
        "build_actioning_context",
    ]
    assert result.preflight is preflight
    assert result.prompt_package.industry_key == "financial_services"
    assert result.deep_research_response["summary"] == "Deep research summary"
    assert result.actioning_context["warm_paths"] == ["Bernadette Norrington"]


@pytest.mark.asyncio
async def test_progress_callback_emits_ordered_stage_events() -> None:
    preflight = _sample_preflight()
    events = []

    class FakeProConnectService:
        def load_transition_case(self, request, **kwargs):
            return {"transition_payload": {"stub": True}}

        def build_preflight(self, request, **kwargs):
            return preflight

        def build_actioning_context(self, request, **kwargs):
            return {"warm_paths": ["Bernadette Norrington"]}

    class FakePromptBuilder:
        def build(self, preflight_obj):
            return TransitionPromptPackage(
                industry_key="financial_services",
                system_prompt="SYSTEM",
                user_prompt="USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        if progress_callback:
            await progress_callback("Found signal", {"status": "in_progress", "citation_count": 3})
        return {
            "type": "deep_research",
            "summary": "Deep research summary",
            "sections": [],
            "citations": [],
            "metadata": {},
        }

    class FakeBDOrchestrator:
        async def run(self, *args, progress_cb=None, **kwargs):
            if progress_cb:
                await progress_cb("Validating with Credentials Agent...")
                await progress_cb("Synthesizing MD Report...")
            return MDReport(
                trigger_summary="Transition playbook",
                executive_summary="Compact summary",
                generated_at=datetime.now(),
            )

    async def capture(event):
        events.append(event)

    orchestrator = TransitionPlaybookOrchestrator(
        proconnect_service=FakeProConnectService(),
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
        bd_orchestrator=FakeBDOrchestrator(),
    )

    await orchestrator.run_transition_playbook(_sample_request(), progress_cb=capture)

    stages = [event["stage"] for event in events]

    assert stages[0] == "resolving_transition"
    assert "building_relationship_context" in stages
    assert stages.index("generating_research_plan") > stages.index("building_relationship_context")
    assert stages.index("running_deep_research") > stages.index("generating_research_plan")
    assert "validating_credentials" in stages
    assert "mapping_warm_leads" in stages
    assert stages[-1] == "assembling_brief"
