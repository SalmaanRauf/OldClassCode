"""
Tests for transition prompt composition.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transition_schemas import (  # type: ignore
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.prompt_loader import PromptLoader
from services.transition_prompt_builder import TransitionPromptBuilder


def _write_prompt_fixture(root: Path) -> PromptLoader:
    industries_dir = root / "industries"
    industries_dir.mkdir(parents=True, exist_ok=True)
    (industries_dir / "general.md").write_text("GENERAL BASE PROMPT", encoding="utf-8")
    (industries_dir / "financial_services.md").write_text("FINANCIAL SERVICES BASE PROMPT", encoding="utf-8")
    metadata = {
        "prompts": {
            "financial_services": {
                "version": "1.0",
                "last_updated": "2026-03-17",
                "display_name": "Financial Services",
                "description": "Banking and lending",
                "file": "industries/financial_services.md",
            },
            "general": {
                "version": "1.0",
                "last_updated": "2026-03-17",
                "display_name": "General",
                "description": "General research",
                "file": "industries/general.md",
            },
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return PromptLoader(prompts_dir=root)


def _sample_preflight(*, industry_override=None, inferred_industry="financial_services", synthetic=True):
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=synthetic,
            industry_override=industry_override,
            additional_context="MD demo scenario",
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
            ),
            OpportunityHypothesis(
                title="Technology risk operating model",
                rationale="Prior source-account work suggests adjacency and relevance.",
                confidence="Medium",
            ),
        ],
        inferred_industry=inferred_industry,
        suggested_research_prompt="Investigate CIO priorities and Protiviti-suited opportunities at Fannie Mae.",
    )


def test_builder_uses_explicit_override_then_inferred_then_general(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = TransitionPromptBuilder(prompt_loader=loader)

    explicit = builder.build(_sample_preflight(industry_override="general"))
    inferred = builder.build(_sample_preflight(industry_override=None, inferred_industry="financial_services"))
    fallback = builder.build(_sample_preflight(industry_override=None, inferred_industry="unknown_industry"))

    assert explicit.industry_key == "general"
    assert inferred.industry_key == "financial_services"
    assert fallback.industry_key == "general"


def test_builder_appends_transition_overlay_to_industry_prompt(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = TransitionPromptBuilder(prompt_loader=loader)

    package = builder.build(_sample_preflight())

    assert "FINANCIAL SERVICES BASE PROMPT" in package.system_prompt
    assert "Transition Playbook Overlay" in package.system_prompt
    assert "executive transition" in package.system_prompt.lower()


def test_builder_labels_synthetic_scenarios_as_hypothetical_and_includes_hypotheses(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = TransitionPromptBuilder(prompt_loader=loader)

    package = builder.build(_sample_preflight(synthetic=True))

    assert "hypothetical planning scenario" in package.user_prompt.lower()
    assert "Jennifer Brady" in package.user_prompt
    assert "Capital One" in package.user_prompt
    assert "Fannie Mae" in package.user_prompt
    assert "AI governance program" in package.user_prompt
    assert "Technology risk operating model" in package.user_prompt
