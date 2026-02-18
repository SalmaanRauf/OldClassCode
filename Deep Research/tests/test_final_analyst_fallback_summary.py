"""
Tests for FinalAnalystAgent fallback summary contract.
"""
import json
from datetime import date

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.final_analyst_agent import FinalAnalystAgent
from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    Opportunity,
    CredentialsResponse,
    CredentialMatch,
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
    assert "Lookup failures: 1" in summary


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


def test_fallback_report_defaults_to_serial_lookup_mode():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    trigger = BDTrigger(sector="Defense", signals=["CMMC"])
    research = DeepResearchOutput(executive_summary="Summary")

    report = agent._fallback_report(trigger, research, credentials={})
    assert report.credentials_lookup_mode == "serial_per_opportunity"


def test_sanitize_recommended_actions_rewrites_stale_year_range():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = ["Initiate capture planning (Q2-Q3 2024)"]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 2, 18))

    assert sanitized == ["Initiate capture planning (within the next 30-90 days)"]


def test_sanitize_recommended_actions_rewrites_stale_quarter_same_year():
    agent = FinalAnalystAgent(kernel=object(), exec_settings=object())
    actions = ["Coordinate proposal sprint by Q1 2026"]

    sanitized = agent._sanitize_recommended_actions(actions, today=date(2026, 8, 1))

    assert sanitized == ["Coordinate proposal sprint by within the next 30-90 days"]


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
    )

    assert len(prompt_vars["user_prompt_context"]) <= 600
    assert "\n" not in prompt_vars["user_prompt_context"]
