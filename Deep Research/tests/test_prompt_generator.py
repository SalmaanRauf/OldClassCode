"""
Tests for research prompt generation guardrails.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.prompt_generator import PromptGenerator, ResearchParameters


def test_prompt_generator_fallback_includes_company_scope_guardrail():
    generator = PromptGenerator()
    params = ResearchParameters(
        sector="financial_services",
        company="Capital One",
        signals="All relevant signals",
        geography="CONUS",
        time_window="180 days",
    )

    prompt = generator._fallback_template(params)

    assert (
        "Anchor findings to Capital One and directly related entities; exclude unrelated peer-company noise unless needed for comparison."
        in prompt
    )


def test_prompt_generator_fallback_includes_scope_guardrail_for_non_fs_sector():
    generator = PromptGenerator()
    params = ResearchParameters(
        sector="defense",
        company="Hanwha",
        signals="CMMC",
        geography="CONUS",
        time_window="90 days",
    )

    prompt = generator._fallback_template(params)

    assert (
        "Anchor findings to Hanwha and directly related entities; exclude unrelated peer-company noise unless needed for comparison."
        in prompt
    )
