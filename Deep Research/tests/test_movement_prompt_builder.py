"""
Tests for named-move prompt composition in the People Movement workflow.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import MovementBriefRequest  # noqa: E402
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_prompt_builder import MovementPromptBuilder  # noqa: E402
from services.prompt_loader import PromptLoader  # noqa: E402


def _write_prompt_fixture(root: Path) -> PromptLoader:
    industries_dir = root / "industries"
    industries_dir.mkdir(parents=True, exist_ok=True)
    (industries_dir / "general.md").write_text("GENERAL BASE PROMPT", encoding="utf-8")
    (industries_dir / "financial_services.md").write_text("FINANCIAL SERVICES BASE PROMPT", encoding="utf-8")
    metadata = {
        "prompts": {
            "financial_services": {
                "version": "1.0",
                "last_updated": "2026-03-23",
                "display_name": "Financial Services",
                "description": "Banking and lending",
                "file": "industries/financial_services.md",
            },
            "general": {
                "version": "1.0",
                "last_updated": "2026-03-23",
                "display_name": "General",
                "description": "General research",
                "file": "industries/general.md",
            },
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return PromptLoader(prompts_dir=root)


def _request(*, synthetic: bool = True, industry_override: str | None = None) -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        lookback_days=180,
        synthetic_scenario=synthetic,
        geography="United States",
        industry_override=industry_override,
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
            ),
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate executive and buyer movement at Fannie Mae over the last 180 days.",
    )


def test_builder_uses_explicit_override_then_inferred_then_general(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = MovementPromptBuilder(prompt_loader=loader)

    explicit = builder.build(_request(industry_override="general"), _preflight())
    inferred = builder.build(_request(industry_override=None), _preflight())
    fallback_preflight = _preflight()
    fallback_preflight.inferred_industry = "unknown_industry"
    fallback = builder.build(_request(industry_override=None), fallback_preflight)

    assert explicit.industry_key == "general"
    assert inferred.industry_key == "financial_services"
    assert fallback.industry_key == "general"


def test_builder_appends_named_move_overlay_to_industry_prompt(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = MovementPromptBuilder(prompt_loader=loader)

    package = builder.build(_request(), _preflight())

    assert "FINANCIAL SERVICES BASE PROMPT" in package.system_prompt
    assert "People Movement Account Overlay" in package.system_prompt
    assert "buyer movement" in package.system_prompt.lower()
    assert "destination account" in package.system_prompt.lower()
    assert "broad inventory of materially supported executive and buyer movers" in package.system_prompt.lower()
    assert "audit, finance, risk, compliance, legal, technology, security, data/ai" in package.system_prompt.lower()
    assert "executive movement inventory" in package.system_prompt.lower()
    assert "buyer movement inventory" in package.system_prompt.lower()
    assert "roughly 15-18 total movers" in package.system_prompt.lower()
    assert "general counsel, deputy general counsel, corporate secretary" in package.system_prompt.lower()
    assert "chief operating officer" in package.system_prompt.lower()
    assert "co-coo" in package.system_prompt.lower()
    assert "chief control office" in package.system_prompt.lower()
    assert "enterprise operations leaders" in package.system_prompt.lower()
    assert "head of enterprise operations" in package.system_prompt.lower()
    assert "legal name and common alias" in package.system_prompt.lower()
    assert "coverage checklist across the buyer centers and major executive lanes" in package.system_prompt.lower()
    assert "prefer recall over conservative pruning" in package.system_prompt.lower()
    assert "medium-confidence movers with explicit role-and-employer support" in package.system_prompt.lower()
    assert "downstream workflow ranks and prioritizes later" in package.system_prompt.lower()
    assert "do not compress multiple movers into prose" in package.system_prompt.lower()
    assert "never include companies, partnerships, products, programs, or transactions as movers" in package.system_prompt.lower()


def test_builder_generates_reviewable_move_led_user_prompt(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = MovementPromptBuilder(prompt_loader=loader)

    package = builder.build(_request(synthetic=True), _preflight())

    assert package.user_prompt.startswith(
        "Research Federal National Mortgage Association (Fannie Mae) across all relevant Financial Services signals."
    )
    assert "180 days" in package.user_prompt
    assert "executive movement" in package.user_prompt.lower()
    assert "buyer movement" in package.user_prompt.lower()
    assert "why the account matters now" in package.user_prompt.lower()
    assert "source-backed movement evidence" in package.user_prompt.lower()
    assert "broad inventory of materially supported executive and buyer movers" in package.user_prompt.lower()
    assert "do not stop after finding only a few obvious names" in package.user_prompt.lower()
    assert "roughly 15-18 total movers" in package.user_prompt.lower()
    assert "general counsel, deputy general counsel, corporate secretary" in package.user_prompt.lower()
    assert "chief operating officer" in package.user_prompt.lower()
    assert "coo" in package.user_prompt.lower()
    assert "co-coo" in package.user_prompt.lower()
    assert "chief control office" in package.user_prompt.lower()
    assert "enterprise operations leaders" in package.user_prompt.lower()
    assert "head of enterprise operations" in package.user_prompt.lower()
    assert "legal name and common alias" in package.user_prompt.lower()
    assert "\"Federal National Mortgage Association (Fannie Mae)\"" in package.user_prompt
    assert "\"Fannie Mae\"" in package.user_prompt
    assert "coverage checklist across buyer centers and major executive lanes" in package.user_prompt.lower()
    assert "prefer recall over conservative pruning" in package.user_prompt.lower()
    assert "medium-confidence movers with explicit role-and-employer support" in package.user_prompt.lower()
    assert "downstream workflow ranks movers later" in package.user_prompt.lower()
    assert "do not compress movers into narrative-only prose" in package.user_prompt.lower()
    assert "never include companies, partnerships, products, programs, or transactions as movers" in package.user_prompt.lower()
    assert "Jennifer Brady" not in package.user_prompt
    assert "Capital One" not in package.user_prompt
    assert "Chief Information Officer" not in package.user_prompt
    assert "hypothetical planning scenario" not in package.user_prompt.lower()
    assert "AI governance program" not in package.user_prompt
    assert "Resolved source account ID" not in package.user_prompt
    assert "Warm intro path available" not in package.user_prompt
