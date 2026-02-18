"""
Unit tests for deterministic financial-services opportunity derivation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import BDTrigger, SignalEvidence
from services.fs_opportunity_deriver import FSOpportunityDeriver


def test_confirmed_exec_transition_creates_governance_opportunity():
    deriver = FSOpportunityDeriver()
    trigger = BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION"],
        company_focus="Capital One",
    )
    evidence = [
        SignalEvidence(
            signal_code="FS.EXEC.TRANSITION",
            signal_label="Executive Transition",
            status="Confirmed",
            evidence_quote="Capital One appointed ... Business Chief Risk Officer ...",
            source_url="https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro",
            source_title="FinTech Magazine",
            analysis="Risk leadership aligned to strategic payments initiative.",
        )
    ]

    opportunities = deriver.derive(trigger, evidence)

    assert len(opportunities) == 1
    assert opportunities[0].derived_from_signal == "FS.EXEC.TRANSITION"
    assert "governance" in opportunities[0].overview.lower()


def test_single_signal_without_confirmation_returns_explicit_non_confirmed_statement():
    deriver = FSOpportunityDeriver()
    trigger = BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION"],
        company_focus="Capital One",
    )
    evidence = [
        SignalEvidence(
            signal_code="FS.EXEC.TRANSITION",
            signal_label="Executive Transition",
            status="Insufficient",
            evidence_quote="",
            source_url="",
            source_title=None,
            analysis="Insufficient verification.",
        )
    ]

    opportunities = deriver.derive(trigger, evidence)

    assert len(opportunities) == 1
    assert opportunities[0].derived_from_signal == "FS.EXEC.TRANSITION"
    assert "did not meet confirmed evidence threshold" in opportunities[0].overview.lower()


def test_all_signals_mode_returns_top_three_by_priority():
    deriver = FSOpportunityDeriver()
    trigger = BDTrigger(
        sector="Financial Services",
        signals=[
            "FS.CONSUMER.LITIGATION_SETTLEMENT",
            "FS.REGULATORY.DEADLINE",
            "FS.EXEC.TRANSITION",
            "FS.CECL.IMPLEMENTATION",
        ],
        user_prompt_context="Research all signals for Capital One.",
    )
    evidence = [
        SignalEvidence(
            signal_code="FS.CECL.IMPLEMENTATION",
            signal_label="CECL",
            status="Confirmed",
            evidence_quote="...",
            source_url="https://example.com/cecl",
            source_title="CECL Source",
            analysis="",
        ),
        SignalEvidence(
            signal_code="FS.REGULATORY.DEADLINE",
            signal_label="Reg Deadline",
            status="Confirmed",
            evidence_quote="...",
            source_url="https://example.com/reg",
            source_title="Reg Source",
            analysis="",
        ),
        SignalEvidence(
            signal_code="FS.EXEC.TRANSITION",
            signal_label="Exec Transition",
            status="Confirmed",
            evidence_quote="...",
            source_url="https://example.com/exec",
            source_title="Exec Source",
            analysis="",
        ),
        SignalEvidence(
            signal_code="FS.CONSUMER.LITIGATION_SETTLEMENT",
            signal_label="Consumer Settlement",
            status="Confirmed",
            evidence_quote="...",
            source_url="https://example.com/consumer",
            source_title="Consumer Source",
            analysis="",
        ),
    ]

    opportunities = deriver.derive(trigger, evidence, max_opportunities=3)

    assert len(opportunities) == 3
    assert opportunities[0].derived_from_signal == "FS.CONSUMER.LITIGATION_SETTLEMENT"
    assert opportunities[1].derived_from_signal == "FS.REGULATORY.DEADLINE"
    assert opportunities[2].derived_from_signal == "FS.EXEC.TRANSITION"
