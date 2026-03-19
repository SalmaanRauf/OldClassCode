"""
Tests for the people movement brief orchestrator.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import BDTrigger, SignalEvidence  # noqa: E402
from models.movement_schemas import MovementCredentialsProof, MovementEvidence, MovementRecord  # noqa: E402
from services.movement_brief_orchestrator import MovementBriefOrchestrator  # noqa: E402


def _trigger() -> BDTrigger:
    return BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"],
        company_focus="Capital One",
        user_prompt_context="Find people movement at Capital One.",
    )


def _movement(index: int) -> MovementRecord:
    return MovementRecord(
        person_name=f"Person {index}",
        target_company="Capital One",
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
async def test_orchestrator_runs_pipeline_and_returns_movement_brief():
    call_order = []

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

    class FakeCredentialsService:
        def build_proof_packets(self, ranked_rows):
            call_order.append("credentials")
            packets = {}
            for row in ranked_rows:
                movement = row["movement"]
                packets[movement.person_name] = MovementCredentialsProof(
                    lookup_status="Matched" if movement.person_name == "Person 0" else "No Match",
                    summary=f"Proof for {movement.person_name}",
                    matched_credentials=[],
                )
            return packets

    class FakeAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            ranked_rows = kwargs["ranked_rows"]
            return kwargs["movement_rows"][0].__class__.__mro__[0]  # pragma: no cover

    # Replace the fake assembler return with an actual brief after we observe the inputs.
    assembled = {}

    class CapturingAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            assembled.update(kwargs)
            from models.movement_schemas import MovementAction, MovementBrief

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
                executive_summary="Deep Research Findings\n- summary\n\nCredentials Agent Findings\n- summary\n\nCombined Report & Action Items\n- summary",
                signal_summary=["Confirmed signals: Executive Movement"],
                movement_rows=rows,
                where_to_act=actions,
                takeaway="Stay focused on mover leverage.",
            )

    orchestrator = MovementBriefOrchestrator(
        fs_signal_evidence_digestor=FakeFSSignalDigestor(),
        movement_digestor=FakeMovementDigestor(),
        proconnect_service=FakeProConnectService(),
        ranker=FakeRanker(),
        credentials_service=FakeCredentialsService(),
        assembler=CapturingAssembler(),
        deep_research_runner=None,
    )

    result = await orchestrator.run(_trigger(), deep_research_output="### Executive Summary\nMovement notes here.")

    assert call_order == [
        "signal_digest",
        "movement_digest",
        "light_enrich",
        "rank",
        "deep_enrich",
        "credentials",
        "assemble",
    ]
    assert len(result.deep_enriched_rows) == 10
    assert result.movement_brief.where_to_act[0].person_name == "Person 0"
    assert len(result.movement_brief.movement_rows) == 10
    assert result.deep_research_markdown.startswith("### Executive Summary")
    assert assembled["signal_evidence"][0].signal_code == "FS.EXEC.TRANSITION"


@pytest.mark.asyncio
async def test_orchestrator_wraps_deep_research_progress_metadata():
    call_order = []
    progress_events = []

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

    class FakeCredentialsService:
        def build_proof_packets(self, ranked_rows):
            call_order.append("credentials")
            return {
                row["movement"].person_name: MovementCredentialsProof(
                    lookup_status="Matched",
                    summary="Proof",
                    matched_credentials=[],
                )
                for row in ranked_rows
            }

    class FakeAssembler:
        def assemble(self, **kwargs):
            call_order.append("assemble")
            from models.movement_schemas import MovementAction, MovementBrief

            rows = kwargs["movement_rows"][:2]
            return MovementBrief(
                executive_summary="Summary",
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
        fs_signal_evidence_digestor=FakeFSSignalDigestor(),
        movement_digestor=FakeMovementDigestor(),
        proconnect_service=FakeProConnectService(),
        ranker=FakeRanker(),
        credentials_service=FakeCredentialsService(),
        assembler=FakeAssembler(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run(_trigger(), progress_cb=capture)

    assert call_order[0][0] == "deep_research_runner"
    assert "signal_digest" in call_order
    assert progress_events[0] == "Running Deep Research..."

    deep_research_event = next(event for event in progress_events if isinstance(event, dict))
    assert deep_research_event["stage"] == "running_deep_research"
    assert deep_research_event["status"] == "in_progress"
    assert deep_research_event["citation_count"] == 3
    assert deep_research_event["poll_count"] == 4
    assert deep_research_event["activity_log"] == ["Poll started", "Found 1 citation"]
    assert deep_research_event["metadata"]["source_hint"] == "preserved"
    assert "Normalizing financial-services signal evidence..." in progress_events
    assert "Movement summary from Deep Research" in result.deep_research_markdown


def test_orchestrator_builds_token_backed_proconnect_service(monkeypatch):
    created = {}

    class FakeClient:
        def __init__(self, base_url: str, bearer_token: str):
            created["client"] = {
                "base_url": base_url,
                "bearer_token": bearer_token,
            }

    monkeypatch.setattr(
        "services.movement_brief_orchestrator.AppConfig",
        SimpleNamespace(
            PROCONNECT_TOKEN_FILE="/tmp/test-token.txt",
            PROCONNECT_BASE_URL="https://example.proconnect",
        ),
    )
    monkeypatch.setattr(
        "services.movement_brief_orchestrator.resolve_bearer_token",
        lambda _cli, token_file: ("Bearer fake-token", f"file:{token_file}"),
    )
    monkeypatch.setattr("services.movement_brief_orchestrator.ProConnectClient", FakeClient)

    orchestrator = MovementBriefOrchestrator(
        fs_signal_evidence_digestor=object(),
        movement_digestor=object(),
        ranker=object(),
        assembler=object(),
    )

    service = orchestrator._get_proconnect_service()

    assert created["client"] == {
        "base_url": "https://example.proconnect",
        "bearer_token": "Bearer fake-token",
    }
    assert service.client is not None
