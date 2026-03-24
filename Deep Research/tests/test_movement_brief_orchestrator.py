"""
Tests for the named-move People Movement Brief orchestrator.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import (  # noqa: E402
    CredentialsResponse,
    Opportunity,
    SignalEvidence,
)
from models.movement_schemas import (  # noqa: E402
    MovementAction,
    MovementBrief,
    MovementBriefRequest,
    MovementCredentialsProof,
    MovementEvidence,
    MovementRecord,
)
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_brief_orchestrator import MovementBriefOrchestrator  # noqa: E402
from services.movement_prompt_builder import MovementPromptPackage  # noqa: E402


def _request() -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        lookback_days=180,
        synthetic_scenario=True,
        geography="United States",
        industry_override="financial_services",
        additional_context="POC demo scenario",
    )


def _preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
            industry_override="financial_services",
            additional_context="POC demo scenario",
        ),
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
        opportunity_hypotheses=[
            OpportunityHypothesis(
                title="AI governance program",
                rationale="CIO transition increases pressure around AI oversight.",
                confidence="High",
            )
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate executive and buyer movement at Fannie Mae over the last 180 days.",
    )


def _movement(index: int) -> MovementRecord:
    return MovementRecord(
        person_name=f"Person {index}",
        target_company="Fannie Mae",
        previous_role=f"Role {index}",
        new_role=f"New Role {index}",
        movement_type="Promoted",
        category="BUYER" if index % 2 == 0 else "EXEC",
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"Person {index} moved into a new role.",
            source_url=f"https://example.com/{index}",
            source_title=f"Source {index}",
        ),
    )


@pytest.mark.asyncio
async def test_orchestrator_builds_preflight_and_prompt_review_context():
    preflight = _preflight()

    class FakeTransitionService:
        def build_preflight(self, request, *, transition_case=None):
            assert request.person_name == "Jennifer Brady"
            return preflight

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            assert request.lookback_days == 180
            assert preflight_arg is preflight
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="FS prompt + overlay",
                user_prompt="Generated move prompt.",
            )

    orchestrator = MovementBriefOrchestrator(
        transition_service=FakeTransitionService(),
        prompt_builder=FakePromptBuilder(),
    )

    result = await orchestrator.build_preflight(_request())

    assert result.preflight is preflight
    assert result.prompt_package.user_prompt == "Generated move prompt."


@pytest.mark.asyncio
async def test_orchestrator_runs_pipeline_and_reuses_real_credentials_boundary():
    call_order = []
    preflight = _preflight()

    class FakeTransitionService:
        def build_preflight(self, request, *, transition_case=None):
            call_order.append("preflight")
            return preflight

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            call_order.append("prompt_builder")
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="FS prompt + overlay",
                user_prompt="Generated move prompt.",
            )

    class FakeFSSignalDigestor:
        async def digest(self, **kwargs):
            call_order.append("signal_digest")
            return (
                [
                    SignalEvidence(
                        signal_code="FS.EXEC.TRANSITION",
                        signal_label="Executive Movement",
                        status="Confirmed",
                        evidence_quote="Leadership is shifting.",
                        source_url="https://example.com/exec",
                        source_title="Exec Source",
                        analysis="Executive movement supports governance reset.",
                    )
                ],
                {"status": "Succeeded"},
                ["https://example.com/exec"],
            )

    class FakeMovementDigestor:
        async def digest(self, **kwargs):
            call_order.append("movement_digest")
            return (
                [_movement(index) for index in range(12)],
                {"status": "Succeeded", "movements_returned": 12},
            )

    class FakeProConnectService:
        def light_enrich_movements(self, movement_rows):
            call_order.append("light_enrich")
            return [
                {
                    "movement": row,
                    "known": index < 5,
                    "worked_with": index < 3,
                    "project_count": index,
                    "win_count": 1 if index == 0 else 0,
                    "relationship_owner": "Ben L" if index < 4 else None,
                    "person_match_status": "matched" if index < 5 else "no_match",
                }
                for index, row in enumerate(movement_rows)
            ]

        def deep_enrich_movements(self, movement_rows, *, max_rows=10):
            call_order.append("deep_enrich")
            return [{"movement": row, "person_detail": {"name": row.person_name}} for row in movement_rows[:max_rows]]

    class FakeRanker:
        def rank(self, enriched_rows, max_rows=10):
            call_order.append("rank")
            ranked = [
                {
                    **item,
                    "rank_score": 100 - index,
                    "action_posture": "Immediate Re-engagement" if index == 0 else "Expansion Opportunity",
                }
                for index, item in enumerate(enriched_rows)
            ]
            return ranked[:max_rows]

    class FakeOpportunityDeriver:
        def derive(self, *, request, preflight, signal_evidence, ranked_rows, max_opportunities=3):
            call_order.append("derive_opportunities")
            return [
                SimpleNamespace(
                    opportunity_id=f"mov_{index}",
                    person_name=row["movement"].person_name,
                    opportunity=Opportunity(
                        opportunity_id=f"mov_{index}",
                        title=f"{row['movement'].person_name} Play",
                        agency=request.to_company,
                        scope="Derived scope",
                        confidence="High",
                    ),
                )
                for index, row in enumerate(ranked_rows[:max_opportunities], 1)
            ]

    class FakeCredentialsLookupRunner:
        async def run(self, opportunities, *, sector, max_opportunities=3):
            call_order.append("credentials_lookup")
            return SimpleNamespace(
                results={
                    (opportunity.opportunity_id or opportunity.title): CredentialsResponse(
                        opportunity_id=opportunity.opportunity_id or opportunity.title,
                        opportunity_title=opportunity.title,
                        matches=[],
                        lookup_status="Matched" if opportunity.title.startswith("Person 0") else "No Match",
                    )
                    for opportunity in opportunities[:max_opportunities]
                },
                diagnostics={},
                batch_diagnostics=None,
                status_counts={"Matched": 1, "No Match": 2, "Lookup Failed": 0},
                lookups_executed_count=min(len(opportunities), max_opportunities),
            )

    class FakeMovementCredentialsService:
        def build_proof_packets(self, derived_opportunities, lookup_results):
            call_order.append("proof_packets")
            return {
                item.opportunity_id: MovementCredentialsProof(
                    lookup_status=lookup_results[item.opportunity_id].lookup_status,
                    summary=f"Proof for {item.person_name}",
                    matched_credentials=[],
                )
                for item in derived_opportunities
            }

    assembled = {}

    class CapturingAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            assembled.update(kwargs)
            rows = kwargs["movement_rows"][:10]
            actions = [
                MovementAction(
                    action_posture="Immediate Re-engagement",
                    person_name=row.person_name,
                    likely_play=f"Play for {row.person_name}",
                    why_now=row.evidence.evidence_quote,
                    relationship_owner=(row.leverage.relationship_owner if row.leverage else None),
                )
                for row in rows[:3]
            ]
            return MovementBrief(
                executive_summary="Move summary text.",
                signal_summary=["Confirmed signals: Executive Movement"],
                movement_rows=rows,
                where_to_act=actions,
                takeaway="Stay focused on mover leverage.",
            )

    orchestrator = MovementBriefOrchestrator(
        transition_service=FakeTransitionService(),
        prompt_builder=FakePromptBuilder(),
        fs_signal_evidence_digestor=FakeFSSignalDigestor(),
        movement_digestor=FakeMovementDigestor(),
        proconnect_service=FakeProConnectService(),
        ranker=FakeRanker(),
        opportunity_deriver=FakeOpportunityDeriver(),
        credentials_lookup_runner=FakeCredentialsLookupRunner(),
        credentials_service=FakeMovementCredentialsService(),
        assembler=CapturingAssembler(),
    )

    result = await orchestrator.run(_request(), deep_research_output="### Executive Summary\nMovement notes here.")

    assert call_order == [
        "preflight",
        "prompt_builder",
        "signal_digest",
        "movement_digest",
        "light_enrich",
        "rank",
        "deep_enrich",
        "derive_opportunities",
        "credentials_lookup",
        "proof_packets",
        "assemble",
    ]
    assert result.preflight is preflight
    assert result.prompt_package.user_prompt == "Generated move prompt."
    assert len(result.deep_enriched_rows) == 10
    assert len(result.movement_brief.movement_rows) == 10
    assert result.deep_research_markdown.startswith("### Executive Summary")
    assert result.credentials_lookup.status_counts["Matched"] == 1
    assert assembled["preflight"] is preflight
    assert assembled["derived_opportunities"][0].person_name == "Person 0"
    assert assembled["derived_opportunities"][0].opportunity_id.startswith("mov_")
    assert assembled["ranked_rows"][0]["opportunity_id"] == assembled["derived_opportunities"][0].opportunity_id
    top_id = assembled["derived_opportunities"][0].opportunity_id
    assert assembled["credential_packets"][top_id].lookup_status == assembled["credentials_lookup"].results[top_id].lookup_status


@pytest.mark.asyncio
async def test_orchestrator_wraps_deep_research_progress_metadata():
    call_order = []
    progress_events = []
    preflight = _preflight()

    class FakeTransitionService:
        def build_preflight(self, request, *, transition_case=None):
            call_order.append("preflight")
            return preflight

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            call_order.append("prompt_builder")
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="FS prompt + overlay",
                user_prompt="Generated move prompt.",
            )

    class FakeFSSignalDigestor:
        async def digest(self, **kwargs):
            call_order.append("signal_digest")
            return ([], {"status": "Succeeded"}, [])

    class FakeMovementDigestor:
        async def digest(self, **kwargs):
            call_order.append("movement_digest")
            return ([_movement(index) for index in range(2)], {"status": "Succeeded", "movements_returned": 2})

    class FakeProConnectService:
        def light_enrich_movements(self, movement_rows):
            call_order.append("light_enrich")
            return [{"movement": row} for row in movement_rows]

        def deep_enrich_movements(self, movement_rows, *, max_rows=10):
            call_order.append("deep_enrich")
            return [{"movement": row} for row in movement_rows[:max_rows]]

    class FakeRanker:
        def rank(self, enriched_rows, max_rows=10):
            call_order.append("rank")
            return enriched_rows[:max_rows]

    class FakeOpportunityDeriver:
        def derive(self, *, request, preflight, signal_evidence, ranked_rows, max_opportunities=3):
            call_order.append("derive_opportunities")
            return []

    class FakeCredentialsLookupRunner:
        async def run(self, opportunities, *, sector, max_opportunities=3):
            call_order.append("credentials_lookup")
            return SimpleNamespace(
                results={},
                diagnostics={},
                batch_diagnostics=None,
                status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
                lookups_executed_count=0,
            )

    class FakeMovementCredentialsService:
        def build_proof_packets(self, derived_opportunities, lookup_results):
            call_order.append("proof_packets")
            return {}

    class FakeAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            rows = kwargs["movement_rows"][:2]
            return MovementBrief(
                executive_summary="Move summary text.",
                signal_summary=[],
                movement_rows=rows,
                where_to_act=[
                    MovementAction(
                        action_posture="Immediate Re-engagement",
                        person_name=row.person_name,
                        likely_play="Play",
                        why_now="Why now",
                        relationship_owner=None,
                    )
                    for row in rows
                ],
                takeaway="Takeaway",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        call_order.append(("deep_research_runner", query, industry))
        assert callable(progress_callback)
        await progress_callback(
            "Polling for source updates",
            {
                "status": "in_progress",
                "citation_count": 3,
                "poll_count": 4,
                "activity_log": ["Poll started", "Found 1 citation"],
                "latest_text": "Polling for source updates",
                "source_hint": "preserved",
            },
        )
        return {
            "type": "deep_research",
            "summary": "Movement summary from Deep Research",
            "sections": [],
            "citations": [],
            "metadata": {},
        }

    async def capture(event):
        progress_events.append(event)

    orchestrator = MovementBriefOrchestrator(
        transition_service=FakeTransitionService(),
        prompt_builder=FakePromptBuilder(),
        fs_signal_evidence_digestor=FakeFSSignalDigestor(),
        movement_digestor=FakeMovementDigestor(),
        proconnect_service=FakeProConnectService(),
        ranker=FakeRanker(),
        opportunity_deriver=FakeOpportunityDeriver(),
        credentials_lookup_runner=FakeCredentialsLookupRunner(),
        credentials_service=FakeMovementCredentialsService(),
        assembler=FakeAssembler(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run(_request(), progress_cb=capture)

    assert call_order[0] == "preflight"
    assert call_order[1] == "prompt_builder"
    assert call_order[2][0] == "deep_research_runner"
    deep_research_event = next(
        event
        for event in progress_events
        if isinstance(event, dict) and event.get("stage") == "running_deep_research"
    )
    assert deep_research_event["stage"] == "running_deep_research"
    assert deep_research_event["status"] == "in_progress"
    assert deep_research_event["citation_count"] == 3
    assert deep_research_event["poll_count"] == 4
    assert deep_research_event["activity_log"] == ["Poll started", "Found 1 citation"]
    assert deep_research_event["metadata"]["source_hint"] == "preserved"
    assert "Movement summary from Deep Research" in result.deep_research_markdown


def test_orchestrator_builds_token_backed_transition_and_movement_proconnect_services(monkeypatch):
    created = []

    class FakeClient:
        def __init__(self, base_url: str, bearer_token: str):
            created.append(
                {
                    "base_url": base_url,
                    "bearer_token": bearer_token,
                }
            )

    monkeypatch.setattr(
        "services.movement_brief_orchestrator.AppConfig",
        SimpleNamespace(
            PROCONNECT_TOKEN_FILE="/tmp/test-token.txt",
            PROCONNECT_BASE_URL="https://example.proconnect",
        ),
    )
    monkeypatch.setattr(
        "services.movement_brief_orchestrator.resolve_runtime_bearer_token",
        lambda **kwargs: ("Bearer fake-token", f"file:{kwargs.get('token_file')}"),
    )
    monkeypatch.setattr("services.movement_brief_orchestrator.ProConnectClient", FakeClient)

    orchestrator = MovementBriefOrchestrator(
        fs_signal_evidence_digestor=object(),
        movement_digestor=object(),
        ranker=object(),
        assembler=object(),
    )

    transition_service = orchestrator._get_transition_service()
    movement_service = orchestrator._get_proconnect_service()

    assert created == [
        {
            "base_url": "https://example.proconnect",
            "bearer_token": "Bearer fake-token",
        },
        {
            "base_url": "https://example.proconnect",
            "bearer_token": "Bearer fake-token",
        },
    ]
    assert transition_service.client is not None
    assert movement_service.client is not None


def test_target_company_aliases_scope_to_destination_account_only():
    aliases = MovementBriefOrchestrator._target_company_aliases(_request(), _preflight())

    assert "Fannie Mae" in aliases
    assert "Federal National Mortgage Association (Fannie Mae)" in aliases
    assert "Capital One" not in aliases
    assert "Capital One Financial Corporation" not in aliases


@pytest.mark.asyncio
async def test_reviewed_movement_context_is_executed_without_rebuilding_preflight():
    call_order = []
    preflight = _preflight()

    class FakeTransitionService:
        def build_preflight(self, request, *, transition_case=None):
            call_order.append("preflight")
            return preflight

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            call_order.append("prompt_builder")
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="REVIEWED SYSTEM PROMPT",
                user_prompt="REVIEWED USER PROMPT",
            )

    class FakeFSSignalDigestor:
        async def digest(self, **kwargs):
            call_order.append("signal_digest")
            return ([], {"status": "Succeeded"}, [])

    class FakeMovementDigestor:
        async def digest(self, **kwargs):
            call_order.append("movement_digest")
            return ([_movement(0)], {"status": "Succeeded"})

    class FakeProConnectService:
        def light_enrich_movements(self, movement_rows, **kwargs):
            call_order.append("light_enrich")
            return [{"movement": movement_rows[0], "known": True, "worked_with": True, "project_count": 1, "win_count": 1, "relationship_owner": "Ben L", "person_match_status": "matched"}]

        def deep_enrich_movements(self, movement_rows, *, max_rows=10, **kwargs):
            call_order.append("deep_enrich")
            return [{"movement": movement_rows[0], "person_detail": {"name": movement_rows[0].person_name}}]

    class FakeRanker:
        def rank(self, enriched_rows, max_rows=10):
            call_order.append("rank")
            return [{**enriched_rows[0], "rank_score": 100, "action_posture": "Immediate Re-engagement"}]

    class FakeOpportunityDeriver:
        def derive(self, **kwargs):
            call_order.append("derive_opportunities")
            return []

    class FakeCredentialsLookupRunner:
        async def run(self, *args, **kwargs):
            call_order.append("credentials_lookup")
            return SimpleNamespace(results={}, diagnostics={}, batch_diagnostics=None, status_counts={}, lookups_executed_count=0)

    class FakeMovementCredentialsService:
        def build_proof_packets(self, derived_opportunities, lookup_results):
            call_order.append("proof_packets")
            return {}

    class FakeAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            return MovementBrief(
                executive_summary="Move summary text.",
                signal_summary=[],
                movement_rows=kwargs["movement_rows"][:1],
                where_to_act=[],
                takeaway="Sparse movement coverage.",
            )

    async def fake_deep_research_runner(query, **kwargs):
        call_order.append("run_deep_research")
        assert query == "REVIEWED USER PROMPT"
        assert kwargs["instructions_override"] == "REVIEWED SYSTEM PROMPT"
        return {"summary": "Deep research summary"}

    orchestrator = MovementBriefOrchestrator(
        transition_service=FakeTransitionService(),
        prompt_builder=FakePromptBuilder(),
        fs_signal_evidence_digestor=FakeFSSignalDigestor(),
        movement_digestor=FakeMovementDigestor(),
        proconnect_service=FakeProConnectService(),
        ranker=FakeRanker(),
        opportunity_deriver=FakeOpportunityDeriver(),
        credentials_lookup_runner=FakeCredentialsLookupRunner(),
        credentials_service=FakeMovementCredentialsService(),
        assembler=FakeAssembler(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run_from_reviewed_context(
        request=_request(),
        preflight=preflight,
        prompt_package=MovementPromptPackage(
            industry_key="financial_services",
            system_prompt="REVIEWED SYSTEM PROMPT",
            user_prompt="REVIEWED USER PROMPT",
        ),
        run_id="run-123",
    )

    assert "preflight" not in call_order
    assert call_order == [
        "run_deep_research",
        "signal_digest",
        "movement_digest",
        "light_enrich",
        "rank",
        "deep_enrich",
        "derive_opportunities",
        "credentials_lookup",
        "proof_packets",
        "assemble",
    ]
    assert result.preflight is preflight
