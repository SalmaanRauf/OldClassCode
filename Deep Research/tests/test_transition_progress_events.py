"""
Tests for transition progress event enrichment.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import MDReport, MDReportOpportunity, Opportunity
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
        suggested_research_prompt="Investigate CIO priorities and warm paths at Fannie Mae.",
    )


def _sample_md_report() -> MDReport:
    return MDReport(
        trigger_summary="Transition playbook",
        executive_summary="Compact summary",
        generated_at=datetime.now(),
        top_opportunities=[
            MDReportOpportunity(
                opportunity=Opportunity(
                    title="AI governance program",
                    scope="Help build governance around AI initiatives.",
                    confidence="High",
                ),
                validation_status="Validated",
                credentials_lookup_status="Matched",
            ),
            MDReportOpportunity(
                opportunity=Opportunity(
                    title="Technology risk modernization",
                    scope="Modernize control monitoring and risk operations.",
                    confidence="Medium",
                ),
                validation_status="Partial",
                credentials_lookup_status="No Match",
            ),
        ],
        recommended_actions=[
            "Reconnect Bernadette Norrington to frame a CIO-first intro.",
        ],
        lookups_executed_count=2,
        credentials_status_counts={"Matched": 1, "No Match": 1, "Lookup Failed": 0},
    )


@pytest.mark.asyncio
async def test_progress_callback_emits_detail_rich_stage_events() -> None:
    preflight = _sample_preflight()
    events = []

    class FakeProConnectService:
        def load_transition_case(self, request, **kwargs):
            return {"transition_payload": {"stub": True}}

        def build_preflight(self, request, **kwargs):
            return preflight

        def build_actioning_context(self, request, **kwargs):
            return {
                "from_company_context": {
                    "relationship_network": {
                        "connected_colleagues": {"items": [{"name": "Bernadette Norrington"}]},
                    }
                },
                "to_company_context": {
                    "relationship_network": {
                        "protiviti_alumni": {"items": [{"name": "Jane Alum"}]},
                        "connected_colleagues": {"items": [{"name": "Indre Anelauskas"}]},
                        "warm_intro_path_available": True,
                    }
                },
            }

    class FakePromptBuilder:
        def build(self, preflight_obj):
            return TransitionPromptPackage(
                industry_key="financial_services",
                system_prompt="SYSTEM",
                user_prompt="USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        if progress_callback:
            await progress_callback(
                "Found signal",
                {
                    "status": "in_progress",
                    "citation_count": 4,
                    "poll_count": 2,
                    "activity_log": ["Search started", "Opportunity candidate extracted"],
                },
            )
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
            return _sample_md_report()

    async def capture(event):
        events.append(event)

    orchestrator = TransitionPlaybookOrchestrator(
        proconnect_service=FakeProConnectService(),
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
        bd_orchestrator=FakeBDOrchestrator(),
    )

    await orchestrator.run_transition_playbook(_sample_request(), progress_cb=capture)

    relationship_complete = next(
        event for event in events if event["stage"] == "building_relationship_context" and event["status"] == "complete"
    )
    assert relationship_complete["person_match_status"] == "matched"
    assert relationship_complete["warm_intro_path_available"] is True
    assert relationship_complete["source_key_buyer_count"] == 24
    assert relationship_complete["destination_key_buyer_count"] == 14

    deep_research_event = next(
        event
        for event in events
        if event["stage"] == "running_deep_research"
        and event["status"] == "in_progress"
        and event.get("citation_count") == 4
    )
    assert deep_research_event["citation_count"] == 4
    assert deep_research_event["poll_count"] == 2
    assert deep_research_event["activity_log"] == ["Search started", "Opportunity candidate extracted"]

    credentials_complete = next(
        event for event in events if event["stage"] == "validating_credentials" and event["status"] == "complete"
    )
    assert credentials_complete["lookups_executed_count"] == 2
    assert credentials_complete["credentials_status_counts"] == {
        "Matched": 1,
        "No Match": 1,
        "Lookup Failed": 0,
    }

    warm_leads_complete = next(
        event for event in events if event["stage"] == "mapping_warm_leads" and event["status"] == "complete"
    )
    assert warm_leads_complete["destination_alumni_count"] == 1
    assert warm_leads_complete["destination_connected_colleague_count"] == 1
    assert warm_leads_complete["warm_intro_path_available"] is True

    brief_complete = next(
        event for event in events if event["stage"] == "assembling_brief" and event["status"] == "complete"
    )
    assert brief_complete["opportunity_count"] == 2
    assert brief_complete["recommended_action_count"] == 1


@pytest.mark.asyncio
async def test_full_run_uses_prompt_override_when_provided() -> None:
    seen = {}

    class FakeProConnectService:
        def load_transition_case(self, request, **kwargs):
            return {"transition_payload": {"stub": True}}

        def build_preflight(self, request, **kwargs):
            return _sample_preflight()

        def build_actioning_context(self, request, **kwargs):
            return {}

    class FakePromptBuilder:
        def build(self, preflight_obj):
            return TransitionPromptPackage(
                industry_key="financial_services",
                system_prompt="SYSTEM",
                user_prompt="DEFAULT PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        seen["query"] = query
        return {
            "type": "deep_research",
            "summary": "Deep research summary",
            "sections": [],
            "citations": [],
            "metadata": {},
        }

    class FakeBDOrchestrator:
        async def run(self, *args, **kwargs):
            return _sample_md_report()

    orchestrator = TransitionPlaybookOrchestrator(
        proconnect_service=FakeProConnectService(),
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
        bd_orchestrator=FakeBDOrchestrator(),
    )

    await orchestrator.run_transition_playbook(
        _sample_request(),
        prompt_override="OVERRIDDEN PROMPT",
    )

    assert seen["query"] == "OVERRIDDEN PROMPT"
