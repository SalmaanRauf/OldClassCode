"""
Tests for the public-account Deep Research orchestrator.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.public_account_prompt_builder import PublicAccountPromptPackage  # noqa: E402
from services.public_account_research_orchestrator import PublicAccountResearchOrchestrator  # noqa: E402


@pytest.mark.asyncio
async def test_orchestrator_runs_public_research_and_normalizes_output() -> None:
    class FakePromptBuilder:
        def build(self, *, company_name, focus_hint=None, industry=None):
            assert company_name == "Fannie Mae"
            assert focus_hint == "Focus on payments modernization and enterprise risk priorities."
            assert industry == "financial_services"
            return PublicAccountPromptPackage(
                industry_key="financial_services",
                system_prompt="PUBLIC SYSTEM PROMPT",
                user_prompt="PUBLIC USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        assert query == "PUBLIC USER PROMPT"
        assert industry == "financial_services"
        assert kwargs["instructions_override"] == "PUBLIC SYSTEM PROMPT"
        assert progress_callback is None
        return {
            "type": "deep_research",
            "executive_summary": "Public company summary",
            "sections": [
                {
                    "heading": "Why Now",
                    "body": "Public signals point to platform modernization pressure.",
                    "sources": [
                        "https://example.com/a",
                        {"title": "Banking Dive", "url": "https://example.com/b"},
                    ],
                },
                {
                    "title": "Coverage Gaps",
                    "content": "- Limited disclosure on buyer owners\n- No public budget timing",
                },
            ],
            "citations": [
                "https://example.com/a",
                {"title": "Duplicate Primary", "url": "https://EXAMPLE.com/A"},
                {"title": "Press Release", "url": "https://example.com/c"},
            ],
            "key_gaps": [
                {"text": "Sparse detail on operating model"},
                "Limited disclosure on buyer owners",
            ],
            "metadata": {
                "display_sources": ["https://example.com/d"],
                "source_urls": ["https://example.com/c", "https://example.com/e"],
                "coverage_gaps": ["No verified budget detail"],
            },
        }

    orchestrator = PublicAccountResearchOrchestrator(
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run(
        company_name="Fannie Mae",
        focus_hint="Focus on payments modernization and enterprise risk priorities.",
        industry="financial_services",
    )

    normalized = result.deep_research_response

    assert result.prompt_package.industry_key == "financial_services"
    assert normalized["company_name"] == "Fannie Mae"
    assert normalized["focus_hint"] == "Focus on payments modernization and enterprise risk priorities."
    assert normalized["industry_key"] == "financial_services"
    assert normalized["summary"] == "Public company summary"
    assert normalized["sections"][0]["title"] == "Why Now"
    assert normalized["sections"][0]["content"] == "Public signals point to platform modernization pressure."
    assert normalized["sections"][0]["citations"] == [
        {"title": "https://example.com/a", "url": "https://example.com/a"},
        {"title": "Banking Dive", "url": "https://example.com/b"},
    ]
    assert [citation["url"] for citation in normalized["citations"]] == [
        "https://example.com/a",
        "https://example.com/c",
        "https://example.com/b",
        "https://example.com/d",
        "https://example.com/e",
    ]
    assert normalized["coverage_gaps"] == [
        "Sparse detail on operating model",
        "Limited disclosure on buyer owners",
        "No public budget timing",
        "No verified budget detail",
    ]


@pytest.mark.asyncio
async def test_orchestrator_wraps_string_responses_into_public_shape() -> None:
    class FakePromptBuilder:
        def build(self, *, company_name, focus_hint=None, industry=None):
            return PublicAccountPromptPackage(
                industry_key="general",
                system_prompt="PUBLIC SYSTEM PROMPT",
                user_prompt="PUBLIC USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        return "Plain public summary"

    orchestrator = PublicAccountResearchOrchestrator(
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run(company_name="BAE Systems")

    assert result.deep_research_response == {
        "type": "deep_research",
        "company_name": "BAE Systems",
        "focus_hint": "",
        "industry_key": "general",
        "summary": "Plain public summary",
        "sections": [],
        "citations": [],
        "coverage_gaps": [],
        "metadata": {},
    }
