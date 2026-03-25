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
            match_scope="from",
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
    case_payload = {"transition_payload": {"stub": True}}
    captured = {}

    class FakeTransitionService:
        def load_transition_case(self, request, **kwargs):
            captured["load_request"] = request.person_name
            return case_payload

        def build_preflight(self, request, *, transition_case=None):
            assert request.person_name == "Jennifer Brady"
            assert transition_case is case_payload
            return preflight

        def build_actioning_context(self, request, *, transition_case=None):
            assert transition_case is case_payload
            return {
                "person_profile": {
                    "match_status": "matched",
                    "relationship_owner": "Ben L",
                    "project_count": 4,
                    "win_count": 2,
                }
            }

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
    assert result.actioning_context["person_profile"]["relationship_owner"] == "Ben L"


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


@pytest.mark.asyncio
async def test_orchestrator_reuses_named_mover_scope_for_row_leverage() -> None:
    preflight = _preflight()
    assembled = {}
    case_payload = {"transition_payload": {"stub": True}}

    class FakeTransitionService:
        def load_transition_case(self, request, **kwargs):
            return case_payload

        def build_preflight(self, request, *, transition_case=None):
            assert transition_case is case_payload
            return preflight

        def build_actioning_context(self, request, *, transition_case=None):
            assert transition_case is case_payload
            return {
                "person_profile": {
                    "match_status": "matched",
                    "matched_person": {
                        "name": "Jennifer Brady",
                        "title": "Senior Director of Technology Risk",
                    },
                    "relationship_owner": "Bernadette Norrington",
                    "project_count": 3,
                    "win_count": 2,
                    "claim_policy_note": "Direct person-level evidence found in ProConnect; person-level claim allowed.",
                    "direct_person_evidence": True,
                },
                "from_company_context": {
                    "account_team": {
                        "account_executive": {"name": "Bernadette Norrington", "title": "Managing Director"},
                    },
                    "relationship_network": {
                        "connected_colleagues": {"items": [{"name": "Bernadette Norrington"}]},
                        "protiviti_alumni": {"items": []},
                    },
                },
                "to_company_context": {
                    "relationship_network": {
                        "connected_colleagues": {"items": []},
                        "protiviti_alumni": {"items": []},
                    },
                },
            }

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="FS prompt + overlay",
                user_prompt="Generated move prompt.",
            )

    class FakeFSSignalDigestor:
        async def digest(self, **kwargs):
            return ([], {"status": "Succeeded"}, [])

    class FakeMovementDigestor:
        async def digest(self, **kwargs):
            return (
                [
                    MovementRecord(
                        person_name="Jennifer Brady",
                        target_company="Fannie Mae",
                        previous_role="Senior Executive, Capital One",
                        new_role="Chief Information Officer",
                        movement_type="External Hire",
                        category="EXEC",
                        company_context="inbound",
                        evidence=MovementEvidence(
                            evidence_quote="Jennifer Brady joined as CIO.",
                            source_url="https://example.com/jennifer",
                            source_title="Leadership update",
                        ),
                    )
                ],
                {"status": "Succeeded", "movements_returned": 1},
            )

    class FakeProConnectService:
        def light_enrich_movements(self, movement_rows):
            return [
                {
                    "movement": movement_rows[0],
                    "known": False,
                    "worked_with": False,
                    "project_count": 0,
                    "win_count": 0,
                    "relationship_owner": None,
                    "person_match_status": "no_match",
                }
            ]

        def deep_enrich_movements(self, movement_rows, *, max_rows=10):
            return [
                {
                    "movement": movement_rows[0],
                    "known": False,
                    "worked_with": False,
                    "project_count": 0,
                    "win_count": 0,
                    "relationship_owner": None,
                    "person_match_status": "no_match",
                    "person_detail": {},
                }
            ]

        def enrich_movement(self, row, *, company_hint=None, include_person_detail=False):
            assert company_hint == "Capital One Financial Corporation"
            return {
                "movement": row,
                "known": True,
                "worked_with": True,
                "project_count": 2,
                "win_count": 1,
                "relationship_owner": "Ben L",
                "person_match_status": "matched",
                "person_detail": {"name": row.person_name} if include_person_detail else {},
            }

    class FakeRanker:
        def rank(self, enriched_rows, max_rows=10):
            return [{**enriched_rows[0], "rank_score": 99, "action_posture": "Immediate Re-engagement"}]

    class FakeOpportunityDeriver:
        def derive(self, **kwargs):
            return []

    class FakeCredentialsLookupRunner:
        async def run(self, opportunities, *, sector, max_opportunities=3):
            return SimpleNamespace(
                results={},
                diagnostics={},
                batch_diagnostics=None,
                status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
                lookups_executed_count=0,
            )

    class FakeMovementCredentialsService:
        def build_proof_packets(self, derived_opportunities, lookup_results):
            return {}

    class CapturingAssembler:
        def assemble(self, **kwargs):
            assembled.update(kwargs)
            return MovementBrief(
                executive_summary="Move summary text.",
                signal_summary=[],
                movement_rows=kwargs["movement_rows"],
                where_to_act=[],
                takeaway="Takeaway",
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

    await orchestrator.run(_request(), deep_research_output="### Executive Summary\nMovement notes here.")

    assert assembled["ranked_rows"][0]["known"] is True
    assert assembled["ranked_rows"][0]["worked_with"] is True
    assert assembled["ranked_rows"][0]["project_count"] == 3
    assert assembled["ranked_rows"][0]["win_count"] == 2
    assert assembled["ranked_rows"][0]["relationship_owner"] == "Bernadette Norrington"
    assert assembled["deep_enriched_rows"][0]["person_match_status"] == "matched"
    assert assembled["deep_enriched_rows"][0]["person_detail"]["match_scope"] == "from"
    assert assembled["deep_enriched_rows"][0]["person_detail"]["relationship_owner"] == "Bernadette Norrington"


@pytest.mark.asyncio
async def test_orchestrator_applies_bounded_brief_synthesis_to_cover_fields() -> None:
    preflight = _preflight()

    class FakeTransitionService:
        def build_preflight(self, request, *, transition_case=None):
            return preflight

    class FakePromptBuilder:
        def build(self, request, preflight_arg):
            return MovementPromptPackage(
                industry_key="financial_services",
                system_prompt="FS prompt + overlay",
                user_prompt="Generated move prompt.",
            )

    class FakeFSSignalDigestor:
        async def digest(self, **kwargs):
            return (
                [
                    SignalEvidence(
                        signal_code="FS.EXEC.TRANSITION",
                        signal_label="Executive Movement",
                        status="Confirmed",
                        evidence_quote="Leadership changed.",
                        source_url="https://example.com/exec",
                        source_title="Exec Source",
                        analysis="Leadership movement is active.",
                    )
                ],
                {"status": "Succeeded"},
                [],
            )

    class FakeMovementDigestor:
        async def digest(self, **kwargs):
            return (
                [_movement(0), _movement(1)],
                {"status": "Succeeded", "movements_returned": 2},
            )

    class FakeProConnectService:
        def light_enrich_movements(self, movement_rows):
            return [{"movement": row} for row in movement_rows]

        def deep_enrich_movements(self, movement_rows, *, max_rows=10):
            return [{"movement": row} for row in movement_rows[:max_rows]]

        def enrich_movement(self, row, *, company_hint=None, include_person_detail=False):
            return {"movement": row, "person_match_status": "no_match", "person_detail": {}}

    class FakeRanker:
        def rank(self, enriched_rows, max_rows=10):
            return [
                {**row, "rank_score": 20 - index, "action_posture": "Monitor"}
                for index, row in enumerate(enriched_rows[:max_rows])
            ]

    class FakeOpportunityDeriver:
        def derive(self, **kwargs):
            return []

    class FakeCredentialsLookupRunner:
        async def run(self, opportunities, *, sector, max_opportunities=3):
            return SimpleNamespace(
                results={},
                diagnostics={},
                batch_diagnostics=None,
                status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
                lookups_executed_count=0,
            )

    class FakeMovementCredentialsService:
        def build_proof_packets(self, derived_opportunities, lookup_results):
            return {}

    class FakeAssembler:
        def assemble(self, **kwargs):
            rows = kwargs["movement_rows"][:2]
            return MovementBrief(
                executive_summary="Deterministic move summary.",
                signal_summary=["Deterministic signal summary."],
                movement_rows=rows,
                where_to_act=[
                    MovementAction(
                        action_posture="Monitor",
                        person_name=row.person_name,
                        likely_play=f"Play for {row.person_name}",
                        why_now=row.evidence.evidence_quote,
                        relationship_owner=None,
                    )
                    for row in rows
                ],
                takeaway="Deterministic takeaway.",
            )

    class FakeBriefSynthesizer:
        def build_input(self, **kwargs):
            return {"built": True, "row_count": len(kwargs["brief"].movement_rows)}

        async def synthesize(self, synthesis_input):
            assert synthesis_input["built"] is True
            assert synthesis_input["row_count"] == 2
            return SimpleNamespace(
                move_summary="LLM move summary.",
                signal_summary=["LLM signal summary 1.", "LLM signal summary 2."],
                takeaway="LLM takeaway.",
                action_narratives=[],
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
        assembler=FakeAssembler(),
        brief_synthesizer=FakeBriefSynthesizer(),
    )

    result = await orchestrator.run(_request(), deep_research_output="### Executive Summary\nMovement notes here.")

    assert result.movement_brief.executive_summary == "LLM move summary."
    assert result.movement_brief.signal_summary == ["LLM signal summary 1.", "LLM signal summary 2."]
    assert result.movement_brief.takeaway == "LLM takeaway."
    assert len(result.movement_brief.movement_rows) == 2
    assert result.movement_brief.where_to_act[0].likely_play == "Play for Person 0"


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
        actioning_context={},
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
