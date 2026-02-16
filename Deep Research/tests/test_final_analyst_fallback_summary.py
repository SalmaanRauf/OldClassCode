"""
Tests for FinalAnalystAgent fallback summary contract.
"""

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
