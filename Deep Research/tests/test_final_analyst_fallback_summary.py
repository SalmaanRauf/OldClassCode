"""
Tests for FinalAnalystAgent fallback summary contract.
"""
import json
from datetime import date

import sys
import os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.final_analyst_agent import FinalAnalystAgent
from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    Opportunity,
    CredentialsResponse,
    CredentialMatch,
    PhaseOpportunity,
    SignalEvidence,
)


def test_fallback_report_uses_fixed_three_block_executive_summary():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(
        executive_summary="Detected opportunities in defense market.",
        opportunities=[
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
        ],
        recommended_actions=["Action A", "Action B"],
    )
    credentials = {
        "Opp 1": CredentialsResponse(
            opportunity_title="Opp 1",
            matches=[
                CredentialMatch(
                    title="Credential 1",
                    client_challenge="Challenge",
                    value_provided="Value",
                    url="https://ishare.protiviti.com/cred/1",
                )
            ],
            lookup_status="Matched",
        ),
        "Opp 2": CredentialsResponse(
            opportunity_title="Opp 2",
            matches=[],
            lookup_status="Lookup Failed",
            failure_reason="Auth error",
        ),
    }

    report = agent._fallback_report(trigger, research, credentials)
    summary = report.executive_summary

    assert "Deep Research Findings" in summary
    assert "Credentials Agent Findings" in summary
    assert "Combined Report & Action Items" in summary
    assert "Lookups executed: 2" in summary
    assert "Matched opportunities: 1" in summary
    assert "No-match opportunities: 0" in summary
    assert "Lookup failures: 1" in summary
    assert "Failed lookups: Opp 2" in summary


def test_fallback_summary_for_extraction_failure_skips_no_match_language():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(executive_summary="Narrative opportunities were detected.")

    report = agent._fallback_report(
        trigger,
        research,
        credentials={},
        opportunity_extraction_status="Extraction Failed",
        opportunity_extraction_reason="Opportunity-rich report but parser returned zero opportunities.",
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason="Opportunity-rich report but parser returned zero opportunities.",
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
    )

    summary = report.executive_summary
    assert "lookup skipped due to extraction failure" in summary.lower()
    assert "no-match opportunities" not in summary.lower()
    assert report.confidence_note == "Report generated with fallback logic after extraction gating."


def test_parse_report_prefers_source_credentials_and_clears_non_match_stubs():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
        ]
    )
    credentials = {
        "Opp 1": CredentialsResponse(
            opportunity_title="Opp 1",
            matches=[
                CredentialMatch(
                    title="Canonical Credential",
                    client_challenge="Real challenge",
                    approach="Real approach",
                    value_provided="Real value",
                    industry="Defense",
                    technologies_used=["CMMC"],
                    url="https://ishare.protiviti.com/cred/real",
                )
            ],
            lookup_status="Matched",
        ),
        "Opp 2": CredentialsResponse(
            opportunity_title="Opp 2",
            matches=[],
            lookup_status="No Match",
        ),
    }

    response_text = json.dumps(
        {
            "trigger_summary": "Defense research",
            "executive_summary": "Deep Research Findings\n...\nCredentials Agent Findings\n...\nCombined Report & Action Items\n...",
            "top_opportunities": [
                {
                    "title": "Opp 1",
                    "scope": "Scope 1",
                    "validation_status": "Validated",
                    "credentials": [
                        {"title": "Sparse LLM Stub", "url": "https://stub"}
                    ],
                },
                {
                    "title": "Opp 2",
                    "scope": "Scope 2",
                    "validation_status": "Validated",
                    "credentials": [
                        {"title": "LLM No-Match Stub", "url": "https://stub-no-match"}
                    ],
                },
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=2,
        lookups_executed_count=2,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 1, "Lookup Failed": 0},
        credentials_lookup_mode="batched_single_call",
        credentials_batch_diagnostics=None,
    )

    assert report.synthesis_status == "synthesized"
    assert report.synthesis_fallback_reason is None

    opp1 = next(opp for opp in report.top_opportunities if opp.opportunity.title == "Opp 1")
    assert len(opp1.credentials) == 1
    assert opp1.credentials[0].title == "Canonical Credential"
    assert opp1.credentials[0].client_challenge == "Real challenge"
    assert opp1.credentials[0].approach == "Real approach"
    assert opp1.credentials[0].value_provided == "Real value"

    opp2 = next(opp for opp in report.top_opportunities if opp.opportunity.title == "Opp 2")
    assert opp2.credentials == []
    assert opp2.credentials_lookup_status == "No Match"
    assert opp2.validation_status == "No Internal Data"


def test_parse_report_resolves_credentials_by_signal_code_when_title_rewritten():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.REGULATORY.DEADLINE"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(
                title="FS.REGULATORY.DEADLINE: Formal regulatory deliverable timelines create near-term pressure on governance, document control, and evidence traceability.",
                scope="Scope",
                confidence="High",
            )
        ]
    )
    credentials = {
        "FS.REGULATORY.DEADLINE: Formal regulatory deliverable timelines create near-term pressure on governance, document control, and evidence traceability.": CredentialsResponse(
            opportunity_title="FS.REGULATORY.DEADLINE: Formal regulatory deliverable timelines create near-term pressure on governance, document control, and evidence traceability.",
            matches=[
                CredentialMatch(
                    title="Canonical Regulatory Deadline Credential",
                    client_challenge="Challenge",
                    approach="Approach",
                    value_provided="Value",
                    industry="Financial Services",
                    technologies_used=[],
                    url="https://ishare.protiviti.com/cred/deadline",
                )
            ],
            lookup_status="Matched",
        )
    }
    response_text = json.dumps(
        {
            "trigger_summary": "FS research",
            "executive_summary": "Summary",
            "top_opportunities": [
                {
                    "title": "FS.REGULATORY.DEADLINE: Formal regulatory deliverable timelines create near-term pressure on governance, documentation",
                    "scope": "Scope",
                    "validation_status": "No Internal Data",
                    "credentials": [
                        {"title": "LLM Stub", "url": "https://stub.local"}
                    ],
                }
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    opp = report.top_opportunities[0]
    assert opp.credentials_lookup_status == "Matched"
    assert opp.validation_status == "Partial"
    assert len(opp.credentials) == 1
    assert opp.credentials[0].title == "Canonical Regulatory Deadline Credential"


def test_parse_report_does_not_use_llm_stub_credentials_when_canonical_missing():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(title="FS.EXEC.TRANSITION: Executive transition.", scope="Scope", confidence="Medium")
        ]
    )
    response_text = json.dumps(
        {
            "trigger_summary": "FS research",
            "executive_summary": "Summary",
            "top_opportunities": [
                {
                    "title": "FS.EXEC.TRANSITION: Executive transition (rewritten).",
                    "scope": "Scope",
                    "validation_status": "Validated",
                    "credentials": [
                        {"title": "LLM Hallucinated Credential", "url": "https://stub.local"}
                    ],
                }
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "Medium confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 0, "No Match": 1, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    opp = report.top_opportunities[0]
    assert opp.credentials_lookup_status == "No Match"
    assert opp.validation_status == "No Internal Data"
    assert opp.credentials == []


def test_parse_report_injects_credentials_counts_and_top_matches_into_executive_summary():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(
        executive_summary="Research summary text.",
        opportunities=[
            Opportunity(
                title="FS.EXEC.TRANSITION: Executive transition.",
                scope="Scope",
                confidence="High",
            )
        ],
    )
    credentials = {
        "FS.EXEC.TRANSITION: Executive transition.": CredentialsResponse(
            opportunity_title="FS.EXEC.TRANSITION: Executive transition.",
            matches=[
                CredentialMatch(
                    title="ERM & RCSA Advisory",
                    client_challenge="Challenge",
                    approach="Approach",
                    value_provided="Value",
                    industry="Financial Services",
                    technologies_used=[],
                    url="https://ishare.protiviti.com/cred/erm",
                )
            ],
            lookup_status="Matched",
        )
    }
    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": (
                "Deep Research Findings\n"
                "Research summary text.\n\n"
                "Credentials Agent Findings\n"
                "- Narrative without counts.\n\n"
                "Combined Report & Action Items\n"
                "- Action."
            ),
            "top_opportunities": [
                {
                    "title": "FS.EXEC.TRANSITION: Executive transition.",
                    "scope": "Scope",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                }
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 1, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    summary = report.executive_summary
    assert "Credentials Agent Findings" in summary
    assert "- Matched opportunities: 1" in summary
    assert "- No-match opportunities: 0" in summary
    assert "- Lookup failures: 0" in summary
    assert "Top matched credentials by opportunity" in summary
    assert "ERM & RCSA Advisory" in summary


def test_parse_report_deduplicates_credentials_metric_lines():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(executive_summary="Research summary text.")

    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": (
                "Deep Research Findings\n"
                "Research summary text.\n\n"
                "Credentials Agent Findings\n"
                "Lookups executed: 3, Matched: 3, No Match: 0.\n"
                "- Lookups executed: 3\n"
                "- Matched opportunities: 3\n"
                "- No-match opportunities: 0\n"
                "- Top matched credentials by opportunity: Existing line.\n\n"
                "Combined Report & Action Items\n"
                "- Action."
            ),
            "top_opportunities": [],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=3,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 3, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    summary = report.executive_summary
    assert summary.count("- Lookups executed: 3") == 1
    assert summary.count("- Matched opportunities: 3") == 1
    assert summary.count("- No-match opportunities: 0") == 1
    assert summary.count("- Lookup failures: 0") == 1
    assert summary.count("Top matched credentials by opportunity") <= 1


def test_parse_report_demo_profile_suppresses_failure_lines():
    os.environ["BD_RUNTIME_PROFILE"] = "demo"
    os.environ["BD_FAILURE_VISIBILITY"] = "suppressed"
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(executive_summary="Research summary text.")

    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": (
                "Deep Research Findings\n"
                "Research summary text.\n\n"
                "Credentials Agent Findings\n"
                "- Matched opportunities: 1\n"
                "- No-match opportunities: 0\n"
                "- Lookup failures: 1\n"
                "- Failed lookups: FS.EXEC.TRANSITION: Executive transition.\n\n"
                "Combined Report & Action Items\n"
                "- Resolve credentials lookup failures before final MD-ready validation.\n"
                "- Continue targeted outreach."
            ),
            "top_opportunities": [],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason="No opportunities identified for credentials validation.",
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )
    os.environ.pop("BD_RUNTIME_PROFILE", None)
    os.environ.pop("BD_FAILURE_VISIBILITY", None)

    summary = report.executive_summary
    assert "Lookup failures" not in summary
    assert "Failed lookups" not in summary
    assert "Resolve credentials lookup failures before final MD-ready validation." not in summary


def test_parse_report_production_profile_keeps_failure_lines():
    os.environ.pop("BD_RUNTIME_PROFILE", None)
    os.environ.pop("BD_FAILURE_VISIBILITY", None)
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(executive_summary="Research summary text.")
    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": (
                "Deep Research Findings\n"
                "Research summary text.\n\n"
                "Credentials Agent Findings\n"
                "- Matched opportunities: 1\n"
                "- No-match opportunities: 0\n"
                "- Lookup failures: 1\n"
                "- Failed lookups: FS.EXEC.TRANSITION: Executive transition.\n\n"
                "Combined Report & Action Items\n"
                "- Resolve credentials lookup failures before final MD-ready validation.\n"
                "- Continue targeted outreach."
            ),
            "top_opportunities": [],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason="No opportunities identified for credentials validation.",
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 1},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    summary = report.executive_summary
    assert "Lookup failures: 1" in summary
    assert "Failed lookups:" in summary


def test_parse_report_uses_index_fallback_for_canonical_opportunity_titles():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    first_title = "FS.CONSUMER.LITIGATION_SETTLEMENT: Canonical first."
    second_title = "FS.REGULATORY.DEADLINE: Canonical second."
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(title=first_title, scope="Scope A", confidence="High"),
            Opportunity(title=second_title, scope="Scope B", confidence="High"),
        ]
    )
    credentials = {
        first_title: CredentialsResponse(
            opportunity_title=first_title,
            matches=[
                CredentialMatch(
                    title="Credential A",
                    client_challenge="Challenge A",
                    approach="Approach A",
                    value_provided="Value A",
                    url="https://ishare.protiviti.com/cred/a",
                )
            ],
            lookup_status="Matched",
        ),
        second_title: CredentialsResponse(
            opportunity_title=second_title,
            matches=[
                CredentialMatch(
                    title="Credential B",
                    client_challenge="Challenge B",
                    approach="Approach B",
                    value_provided="Value B",
                    url="https://ishare.protiviti.com/cred/b",
                )
            ],
            lookup_status="Matched",
        ),
    }
    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": (
                "Deep Research Findings\n"
                "Summary.\n\n"
                "Credentials Agent Findings\n"
                "- Narrative.\n\n"
                "Combined Report & Action Items\n"
                "- Action."
            ),
            "top_opportunities": [
                {
                    "title": "Rewritten Opportunity Alpha",
                    "scope": "Scope A",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                },
                {
                    "title": "Rewritten Opportunity Beta",
                    "scope": "Scope B",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                },
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=2,
        lookups_executed_count=2,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 2, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    assert report.top_opportunities[0].opportunity.title == first_title
    assert report.top_opportunities[1].opportunity.title == second_title
    assert report.top_opportunities[0].credentials[0].title == "Credential A"
    assert report.top_opportunities[1].credentials[0].title == "Credential B"


def test_parse_report_prefers_stable_opportunity_ids_over_rewritten_titles():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(
                opportunity_id="opp_a",
                title="Canonical First",
                scope="Scope A",
                confidence="High",
            ),
            Opportunity(
                opportunity_id="opp_b",
                title="Canonical Second",
                scope="Scope B",
                confidence="High",
            ),
        ]
    )
    credentials = {
        "opp_a": CredentialsResponse(
            opportunity_id="opp_a",
            opportunity_title="Canonical First",
            matches=[
                CredentialMatch(
                    title="Credential A",
                    client_challenge="Challenge A",
                    approach="Approach A",
                    value_provided="Value A",
                    url="https://ishare.protiviti.com/cred/a",
                )
            ],
            lookup_status="Matched",
        ),
        "opp_b": CredentialsResponse(
            opportunity_id="opp_b",
            opportunity_title="Canonical Second",
            matches=[
                CredentialMatch(
                    title="Credential B",
                    client_challenge="Challenge B",
                    approach="Approach B",
                    value_provided="Value B",
                    url="https://ishare.protiviti.com/cred/b",
                )
            ],
            lookup_status="Matched",
        ),
    }
    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": "Deep Research Findings\nSummary.\n\nCredentials Agent Findings\nNarrative.\n\nCombined Report & Action Items\n- Action.",
            "top_opportunities": [
                {
                    "opportunity_id": "opp_b",
                    "title": "Rewritten Opportunity Beta",
                    "scope": "Scope B",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                },
                {
                    "opportunity_id": "opp_a",
                    "title": "Rewritten Opportunity Alpha",
                    "scope": "Scope A",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                },
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials=credentials,
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=2,
        lookups_executed_count=2,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 2, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    assert report.top_opportunities[0].opportunity.opportunity_id == "opp_b"
    assert report.top_opportunities[1].opportunity.opportunity_id == "opp_a"
    assert report.top_opportunities[0].credentials[0].title == "Credential B"
    assert report.top_opportunities[1].credentials[0].title == "Credential A"


def test_synthesize_returns_fallback_when_kernel_bootstrap_fails(monkeypatch):
    agent = FinalAnalystAgent()
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(executive_summary="Summary")

    async def boom():
        raise RuntimeError("kernel boot failed")

    monkeypatch.setattr(agent, "_ensure_kernel", boom)

    import asyncio

    report = asyncio.run(
        agent.synthesize(
            trigger=trigger,
            research=research,
            credentials={},
            opportunity_extraction_status="Parsed",
            opportunity_extraction_reason=None,
            opportunities_extracted_count=0,
            lookups_executed_count=0,
            lookups_skipped_reason=None,
            credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
            credentials_lookup_mode="serial_per_opportunity",
            credentials_batch_diagnostics=None,
        )
    )

    assert report.synthesis_status == "fallback"
    assert report.synthesis_fallback_reason == "synthesis_error"
    assert "kernel boot failed" in (report.synthesis_error_message or "")


def test_build_prompt_variables_includes_preflight_context_and_opportunity_ids():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(
                opportunity_id="opp_a",
                title="Opportunity A",
                scope="Scope A",
                confidence="High",
            )
        ]
    )

    prompt_vars = agent._build_prompt_variables(
        trigger=trigger,
        research=research,
        credentials={
            "opp_a": CredentialsResponse(
                opportunity_id="opp_a",
                opportunity_title="Opportunity A",
                matches=[],
                lookup_status="No Match",
            )
        },
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=1,
        lookups_executed_count=1,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 0, "No Match": 1, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
        confirmed_signal_evidence=None,
        phase3_candidates=None,
        allowed_sources=None,
        preflight_context={"opportunities": [{"opportunity_id": "opp_a", "title": "Opportunity A"}]},
    )

    assert '"opportunity_id": "opp_a"' in prompt_vars["opportunities_json"]
    assert '"opportunity_id": "opp_a"' in prompt_vars["credentials_json"]
    assert '"opportunities"' in prompt_vars["preflight_context_json"]


def test_fallback_phase2_footnotes_use_strict_structured_schema():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    signal_evidence = [
        SignalEvidence(
            signal_code="FS.REGULATORY.DEADLINE",
            signal_label="Regulatory Deadline",
            status="Confirmed",
            evidence_quote="OCC required a remediation plan within 120 days.",
            source_url="https://occ.treas.gov/news-issuances/bulletins/2025/bulletin-2025-51.html",
            source_title="OCC Bulletin 2025-51",
            analysis="Confirms a hard regulator deadline for submission.",
        )
    ]

    footnotes = agent._fallback_phase2_footnotes(signal_evidence)

    assert footnotes is not None
    assert len(footnotes) == 1
    first = footnotes[0]
    assert "Verbatim quote:" in first
    assert "Source title:" in first
    assert "Canonical URL:" in first
    assert "Evidentiary linkage:" in first


def test_parse_phase2_footnotes_normalizes_compact_input_to_structured_schema():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    compact = [
        "\"OCC required remediation timeline\" (OCC Bulletin 2025-51, https://occ.treas.gov/news-issuances/bulletins/2025/bulletin-2025-51.html) — confirms deadline."
    ]
    signal_evidence = [
        SignalEvidence(
            signal_code="FS.REGULATORY.DEADLINE",
            signal_label="Regulatory Deadline",
            status="Confirmed",
            evidence_quote="OCC required a remediation plan within 120 days.",
            source_url="https://occ.treas.gov/news-issuances/bulletins/2025/bulletin-2025-51.html",
            source_title="OCC Bulletin 2025-51",
            analysis="Confirms a hard regulator deadline for submission.",
        )
    ]

    parsed = agent._parse_phase2_footnotes(
        raw=compact,
        fallback_signal_evidence=signal_evidence,
    )

    assert parsed is not None
    assert len(parsed) == 1
    first = parsed[0]
    assert first.startswith("Verbatim quote:")
    assert "Source title: OCC Bulletin 2025-51" in first
    assert "Canonical URL: https://occ.treas.gov/news-issuances/bulletins/2025/bulletin-2025-51.html" in first
    assert "Evidentiary linkage:" in first


def test_fallback_report_defaults_to_serial_lookup_mode():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(executive_summary="Summary")

    report = agent._fallback_report(trigger, research, credentials={})
    assert report.credentials_lookup_mode == "serial_per_opportunity"
    assert report.synthesis_status == "fallback"
    assert report.synthesis_fallback_reason in {"synthesis_error", "extraction_skip"}


def test_sanitize_recommended_actions_rewrites_stale_year_range():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = ["Initiate capture planning (Q2-Q3 2024)"]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 2, 18))

    assert sanitized == ["Initiate capture planning (within the next 30-90 days)"]


def test_sanitize_recommended_actions_rewrites_stale_quarter_same_year():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = ["Coordinate proposal sprint by Q1 2026"]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 8, 1))

    assert sanitized == ["Coordinate proposal sprint within the next 30-90 days"]


def test_sanitize_recommended_actions_keeps_current_or_future_quarter():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = [
        "Prepare submission in Q1 2026",
        "Engage partners in Q3 2026",
    ]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 2, 18))

    assert sanitized == actions


def test_fallback_report_sanitizes_stale_recommended_actions():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(
        executive_summary="Summary",
        recommended_actions=["Build proposal library (Q2-Q3 2024)"],
    )

    report = agent._fallback_report(trigger, research, credentials={})

    assert report.recommended_actions == ["Build proposal library (within the next 30-90 days)"]
    assert "Q2-Q3 2024" not in report.executive_summary


def test_sanitize_recommended_actions_rewrites_year_range_with_prefix():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = ["Develop compliance roadmap in late 2025–2026"]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 2, 18))

    assert sanitized == ["Develop compliance roadmap within the next 30-90 days"]


def test_build_prompt_variables_includes_current_date_and_prompt_context():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(
        sector="Defense",
        signals=["CMMC"],
        user_prompt_context="  Research\nHanwha  opportunities   with CMMC   ",
    )
    research = DeepResearchOutput(executive_summary="Summary")

    prompt_vars = agent._build_prompt_variables(
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
        confirmed_signal_evidence=None,
        phase3_candidates=None,
        allowed_sources=None,
        preflight_context=None,
    )

    assert prompt_vars["current_date_iso"] == date.today().isoformat()
    assert prompt_vars["user_prompt_context"] == "Research Hanwha opportunities with CMMC"


def test_build_prompt_variables_truncates_prompt_context():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(
        sector="Defense",
        user_prompt_context=("A " * 500).strip(),
    )
    research = DeepResearchOutput(executive_summary="Summary")

    prompt_vars = agent._build_prompt_variables(
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
        confirmed_signal_evidence=None,
        phase3_candidates=None,
        allowed_sources=None,
        preflight_context=None,
    )

    assert len(prompt_vars["user_prompt_context"]) <= 600
    assert "\n" not in prompt_vars["user_prompt_context"]


def test_parse_phase_sources_merges_fallback_and_model_sources():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())

    merged = agent._parse_phase_sources(
        raw=["https://example.com/model-a", "https://example.com/shared"],
        fallback=["https://example.com/fallback-a", "https://example.com/shared"],
    )

    assert merged == [
        "https://example.com/fallback-a",
        "https://example.com/shared",
        "https://example.com/model-a",
    ]


def test_parse_report_sanitizes_stale_phase3_recommended_actions():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(opportunities=[])

    response_text = json.dumps(
        {
            "trigger_summary": "FS run",
            "executive_summary": "Summary",
            "top_opportunities": [],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
            "phase3_opportunities": [
                {
                    "derived_from_signal": "FS.EXEC.TRANSITION",
                    "overview": "Overview",
                    "technical_explanation": "Technical",
                    "layman_explanation": "Layman",
                    "relevant_service_lines": ["Risk governance advisory"],
                    "credentials_summary": "No materially aligned credentials identified.",
                    "recommended_actions": ["Deploy governance controls by April 2025."],
                    "sources": ["https://example.com/source-a"],
                }
            ],
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=0,
        lookups_executed_count=0,
        lookups_skipped_reason="No opportunities identified for credentials validation.",
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
        confirmed_signal_evidence=None,
        phase3_candidates=None,
        allowed_sources=None,
    )

    assert report.phase3_opportunities is not None
    assert report.phase3_opportunities[0].recommended_actions == [
        "Deploy governance controls within the next 30-90 days."
    ]


def test_fallback_report_sanitizes_stale_phase3_candidate_actions():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Financial Services", signals=["FS.EXEC.TRANSITION"])
    research = DeepResearchOutput(executive_summary="Summary")

    report = agent._fallback_report(
        trigger=trigger,
        research=research,
        credentials={},
        phase3_candidates=[
            PhaseOpportunity(
                derived_from_signal="FS.EXEC.TRANSITION",
                overview="Overview",
                technical_explanation="Technical",
                layman_explanation="Layman",
                relevant_service_lines=["Risk governance advisory"],
                credentials_summary="No materially aligned credentials identified.",
                recommended_actions=["Start delivery before September 2025."],
                sources=["https://example.com/source-a"],
            )
        ],
    )

    assert report.phase3_opportunities is not None
    assert report.phase3_opportunities[0].recommended_actions == [
        "Start delivery within the next 30-90 days."
    ]


def test_canonical_opportunities_merge_ids_from_preflight_context():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
        ]
    )

    canonical = agent._canonical_opportunities(
        research,
        preflight_context={
            "opportunities": [
                {"opportunity_id": "opp_a", "title": "Opp 1", "scope": "Scope 1"},
                {"opportunity_id": "opp_b", "title": "Opp 2", "scope": "Scope 2"},
            ]
        },
    )

    assert canonical[0].opportunity_id == "opp_a"
    assert canonical[1].opportunity_id == "opp_b"


def test_parse_report_does_not_positionally_rebind_unknown_reported_opportunity_id():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(
        opportunities=[
            Opportunity(opportunity_id="opp_a", title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(opportunity_id="opp_b", title="Opp 2", scope="Scope 2", confidence="Medium"),
        ]
    )

    response_text = json.dumps(
        {
            "trigger_summary": "Defense research",
            "executive_summary": "Deep Research Findings\n...\nCredentials Agent Findings\n...\nCombined Report & Action Items\n...",
            "top_opportunities": [
                {
                    "opportunity_id": "unknown_opp",
                    "title": "Completely rewritten title",
                    "scope": "Rewritten scope",
                    "validation_status": "No Internal Data",
                    "credentials": [],
                }
            ],
            "signals_detected": [],
            "recommended_actions": [],
            "confidence_note": "High confidence",
        }
    )

    report = agent._parse_report(
        response_text=response_text,
        trigger=trigger,
        research=research,
        credentials={},
        opportunity_extraction_status="Parsed",
        opportunity_extraction_reason=None,
        opportunities_extracted_count=2,
        lookups_executed_count=0,
        lookups_skipped_reason=None,
        credentials_status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        credentials_lookup_mode="serial_per_opportunity",
        credentials_batch_diagnostics=None,
    )

    opp = report.top_opportunities[0]
    assert opp.opportunity.opportunity_id == "unknown_opp"
    assert opp.opportunity.title == "Completely rewritten title"
