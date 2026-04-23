"""
Tests for bounded account-brief synthesis.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import (  # noqa: E402
    BDTrigger,
    CredentialMatch,
    CredentialsResponse,
    DeepResearchOutput,
    Opportunity,
    PhaseOpportunity,
    SignalEvidence,
)
from services.account_brief_synthesizer import (  # noqa: E402
    AccountBriefSynthesizer,
    AccountBriefSynthesisResult,
    SynthesizedSuggestedPlay,
)


def test_build_input_creates_structured_account_evidence_pack():
    synthesizer = AccountBriefSynthesizer()
    trigger = BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"],
        company_focus="Capital One",
        user_prompt_context="Summarize the account and recommend plays.",
        geography="US",
        time_window_days=180,
    )
    research = DeepResearchOutput(
        executive_summary="Final Report: Capital One is under governance pressure. Sources: 1. Example",
        signals_detected=["Executive movement accelerated.", "Operating model pressure increased."],
        opportunities=[
            Opportunity(
                opportunity_id="opp-1",
                title="AI governance program",
                agency="Capital One",
                scope="Stand up an enterprise AI governance model.",
                estimated_value="$2M",
                timeline="Q3",
                confidence="High",
            ),
            Opportunity(
                opportunity_id="opp-2",
                title="Risk transformation",
                agency="Capital One",
                scope="Refresh enterprise risk operating model.",
                confidence="Medium",
            ),
            Opportunity(
                opportunity_id="opp-3",
                title="Controls rationalization",
                agency="Capital One",
                scope="Rationalize first-line and second-line controls.",
                confidence="Medium",
            ),
            Opportunity(
                opportunity_id="opp-4",
                title="Should be trimmed",
                agency="Capital One",
                scope="This should not appear in the payload.",
                confidence="Low",
            ),
        ],
        recommended_actions=["Lead with AI governance.", "Coordinate with account team."],
    )
    credentials = {
        "opp-1": CredentialsResponse(
            opportunity_id="opp-1",
            opportunity_title="AI governance program",
            matches=[
                CredentialMatch(
                    title="AI Governance Transformation",
                    client_challenge="Needed enterprise AI controls.",
                    value_provided="Built governance model and controls.",
                    url="https://example.com/cred-1",
                )
            ],
            lookup_status="Matched",
        ),
        "opp-2": CredentialsResponse(
            opportunity_id="opp-2",
            opportunity_title="Risk transformation",
            matches=[],
            lookup_status="No Match",
        ),
    }
    confirmed_signal_evidence = [
        SignalEvidence(
            signal_code="FS.EXEC.TRANSITION",
            signal_label="Executive Movement",
            status="Confirmed",
            evidence_quote="A senior executive entered the account.",
            source_url="https://example.com/source-1",
            source_title="Source 1",
            analysis="Leadership turnover is active.",
        ),
        SignalEvidence(
            signal_code="FS.BUYER.MOVEMENT",
            signal_label="Buyer Movement",
            status="Insufficient",
            evidence_quote="",
            source_url="",
            source_title=None,
            analysis="",
        ),
    ]
    phase3_candidates = [
        PhaseOpportunity(
            derived_from_signal="FS.EXEC.TRANSITION",
            overview="AI governance program should be framed as an early executive priority.",
            technical_explanation="The control model needs refresh.",
            layman_explanation="Leadership change creates a reset window.",
            relevant_service_lines=["Risk", "Technology"],
            credentials_summary="AI Governance Transformation aligns.",
            recommended_actions=["Map the first 90-day agenda."],
            sources=["https://example.com/source-1"],
        )
    ]

    payload = synthesizer.build_input(
        run_id="run-123",
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=4,
        lookups_executed_count=2,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 1, "Lookup Failed": 0},
        confirmed_signal_evidence=confirmed_signal_evidence,
        phase3_candidates=phase3_candidates,
        allowed_sources=["https://example.com/source-1"],
        preflight_context={"warm_intro_path_available": True},
    )

    assert payload["run_id"] == "run-123"
    assert payload["trigger_context"]["company_focus"] == "Capital One"
    assert payload["account_context"]["research_summary"] == "Capital One is under governance pressure."
    assert len(payload["top_opportunities"]) == 3
    assert payload["top_opportunities"][0]["opportunity_id"] == "opp-1"
    assert payload["top_opportunities"][0]["credentials_lookup_status"] == "Matched"
    assert payload["top_opportunities"][0]["credentials"][0]["title"] == "AI Governance Transformation"
    assert len(payload["confirmed_signals"]) == 1
    assert payload["confirmed_signals"][0]["signal_code"] == "FS.EXEC.TRANSITION"
    assert payload["phase3_candidates"][0]["recommended_actions"] == ["Map the first 90-day agenda."]
    assert payload["credential_summary"] == {
        "lookups_executed_count": 2,
        "status_counts": {"Matched": 1, "No Match": 1, "Lookup Failed": 0},
    }
    assert payload["synthesis_rules"]["no_retrieval"] is True


def test_build_input_accepts_account_brief_contract_without_retrieval_dependencies():
    synthesizer = AccountBriefSynthesizer()

    payload = synthesizer.build_input(
        request_context={
            "account_name": "BAE Systems",
            "raw_input": "BAE Systems",
            "focus_hint": "Metro DC",
        },
        proconnect_summary={
            "account_status": {"summary": "No known ProConnect work found."},
            "known_buyers": [{"name": "Kathy Memenza"}],
        },
        deep_research_summary={
            "summary": "Public signals point to defense modernization pressure.",
            "sections": [{"title": "Why Now", "content": "Platform modernization pressure is visible."}],
            "citations": [{"title": "Example", "url": "https://example.com"}],
        },
        source_boundary_rules={
            "no_public_as_internal": True,
            "no_internal_as_public": True,
        },
        coverage_gaps=[
            "True 3-level reporting hierarchy is not available.",
            "RHI account-level work coverage is not available.",
        ],
        synthesis_rules={
            "short_brief": True,
            "light_inference": True,
        },
    )

    assert payload["request_context"]["account_name"] == "BAE Systems"
    assert payload["proconnect_summary"]["account_status"]["summary"] == "No known ProConnect work found."
    assert payload["deep_research_summary"]["summary"] == "Public signals point to defense modernization pressure."
    assert payload["coverage_gaps"] == [
        "True 3-level reporting hierarchy is not available.",
        "RHI account-level work coverage is not available.",
    ]
    assert payload["synthesis_rules"]["short_brief"] is True


def test_coerce_result_treats_string_sections_as_single_bullets_and_filters_invalid_plays():
    synthesizer = AccountBriefSynthesizer()

    result = synthesizer._coerce_result(  # noqa: SLF001
        {
            "account_summary": "Capital One has multiple current pressure points.",
            "signal_summary": "Executive movement and governance pressure are confirmed.",
            "opportunity_summary": "AI governance is the clearest near-term opening.",
            "takeaway": "Lead with the highest-confidence opening and current credential proof.",
            "suggested_plays": [
                {
                    "play": "Lead with AI governance and controls modernization.",
                    "why_now": "Leadership transition and governance pressure are both present.",
                },
                {
                    "play": "Invalid play missing why now.",
                },
            ],
        }
    )

    assert result == AccountBriefSynthesisResult(
        account_summary="Capital One has multiple current pressure points.",
        signal_summary=["Executive movement and governance pressure are confirmed."],
        opportunity_summary=["AI governance is the clearest near-term opening."],
        takeaway="Lead with the highest-confidence opening and current credential proof.",
        suggested_plays=[
            SynthesizedSuggestedPlay(
                play="Lead with AI governance and controls modernization.",
                why_now="Leadership transition and governance pressure are both present.",
            )
        ],
    )


def test_coerce_result_extracts_json_from_markdown_wrappers():
    synthesizer = AccountBriefSynthesizer()

    result = synthesizer._coerce_result(  # noqa: SLF001
        """
        Analyst draft
        ```json
        {
          "account_summary": "Capital One is in an active transition window.",
          "signal_summary": ["Executive movement is confirmed."],
          "opportunity_summary": ["AI governance remains the strongest opening."],
          "takeaway": "Stay anchored to sourced openings.",
          "suggested_plays": []
        }
        ```
        """
    )

    assert result == AccountBriefSynthesisResult(
        account_summary="Capital One is in an active transition window.",
        signal_summary=["Executive movement is confirmed."],
        opportunity_summary=["AI governance remains the strongest opening."],
        takeaway="Stay anchored to sourced openings.",
        suggested_plays=[],
    )


def test_coerce_result_requires_full_output_contract():
    synthesizer = AccountBriefSynthesizer()

    result = synthesizer._coerce_result(  # noqa: SLF001
        {
            "account_summary": "Capital One is in motion.",
            "signal_summary": ["Executive movement is confirmed."],
            "opportunity_summary": ["AI governance remains the strongest opening."],
        }
    )

    assert result is None
