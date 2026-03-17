"""
Tests for transition validation/review presentation helpers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transition_schemas import (  # type: ignore
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.transition_presenter import build_transition_preflight_review  # type: ignore
from services.transition_prompt_builder import TransitionPromptPackage


def _sample_preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
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
        suggested_research_prompt="Investigate CIO priorities and warm paths at Fannie Mae.",
    )


def test_preflight_review_contains_compact_transition_summary() -> None:
    payload = build_transition_preflight_review(
        _sample_preflight(),
        TransitionPromptPackage(
            industry_key="financial_services",
            system_prompt="SYSTEM",
            user_prompt="Investigate CIO priorities and warm paths at Fannie Mae.",
        ),
    )

    content = payload["content"]
    assert "Jennifer Brady" in content
    assert "Capital One -> Fannie Mae" in content
    assert "Warm path available: Yes" in content
    assert "Industry context: Financial Services" in content


def test_generated_prompt_is_hidden_behind_view_prompt_action() -> None:
    prompt_text = "Investigate CIO priorities and warm paths at Fannie Mae."
    payload = build_transition_preflight_review(
        _sample_preflight(),
        TransitionPromptPackage(
            industry_key="financial_services",
            system_prompt="SYSTEM",
            user_prompt=prompt_text,
        ),
    )

    assert prompt_text not in payload["content"]
    assert payload["view_prompt_action"]["label"] == "View Generated Prompt"
    assert payload["prompt_content"] == prompt_text


def test_primary_actions_are_run_research_edit_prompt_and_adjust_transition() -> None:
    payload = build_transition_preflight_review(
        _sample_preflight(),
        TransitionPromptPackage(
            industry_key="financial_services",
            system_prompt="SYSTEM",
            user_prompt="Investigate CIO priorities and warm paths at Fannie Mae.",
        ),
    )

    labels = [action["label"] for action in payload["actions"]]
    assert labels == ["Run Research", "Edit Prompt", "Adjust Transition"]
