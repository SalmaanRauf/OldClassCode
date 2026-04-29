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
        "Public research did not expose explicit evidence dates; verify freshness before MD use.",
    ]
    assert normalized["freshness_assessment"]["needs_review"] is True


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

    response = result.deep_research_response
    assert response["type"] == "deep_research"
    assert response["company_name"] == "BAE Systems"
    assert response["focus_hint"] == ""
    assert response["industry_key"] == "general"
    assert response["summary"] == "Plain public summary"
    assert response["sections"] == []
    assert response["citations"] == []
    assert response["public_people_targets"] == []
    assert response["freshness_assessment"]["needs_review"] is True


@pytest.mark.asyncio
async def test_orchestrator_extracts_people_first_sections_from_markdown_summary() -> None:
    class FakePromptBuilder:
        def build(self, *, company_name, focus_hint=None, industry=None):
            return PublicAccountPromptPackage(
                industry_key="general",
                system_prompt="PUBLIC SYSTEM PROMPT",
                user_prompt="PUBLIC USER PROMPT",
            )

    async def fake_deep_research_runner(query, industry="general", progress_callback=None, **kwargs):
        return {
            "summary": """
## Executive Pursuit Thesis
BAE Systems has current 2026 pursuit triggers.

## Company Snapshot
BAE Systems is a global defense contractor with public sector end-market exposure.

## Strategy, Priorities, and Operating Pressure
- 2026 defense modernization demand | program execution and cyber pressure

## Filings, Financials, and Risk Signals
| Source/date | Signal | Why it matters | Pursuit implication |
| --- | --- | --- | --- |
| 2026 annual report | Cyber and program execution risk | Risk leaders may need support | Risk/compliance lane |

## Competitive and Market Context
- Competes in defense electronics and systems integration where modernization and delivery performance matter.

## Customer, Contract, and Procurement Signals
- 2026 contract activity | government customer demand | procurement and program delivery lane

## Likely Needs / White-Space Hypotheses
| Need or hypothesis | Evidence | Likely buyer lane | Confidence | Analyst validation step |
| --- | --- | --- | --- | --- |
| Cyber compliance support | defense modernization and risk disclosure | CISO/risk | Medium | Validate active programs |

## People to Pursue
| Person | Current role | Buyer lane | Why this person matters now | Evidence date/source |
| --- | --- | --- | --- | --- |
| Jane Doe | CIO | Technology | Owns modernization | 2026 company source |

## Recent People Moves
- John Smith | Appointed CFO | 2026 | Finance transformation trigger | Company release

## Buying Committee Map
- Economic buyer | CFO office | 2026 proxy | Budget and risk | Confirm reporting line

## Why Now / Current Triggers
- 2026 modernization announcement | technology advisory relevance | CIO lane

## Recommended MD Actions This Week
- Ask analyst to validate CIO direct reports and recent procurement.
""",
            "citations": [{"title": "Company release", "url": "https://example.com/release"}],
        }

    orchestrator = PublicAccountResearchOrchestrator(
        prompt_builder=FakePromptBuilder(),
        deep_research_runner=fake_deep_research_runner,
    )

    result = await orchestrator.run(company_name="BAE Systems")
    response = result.deep_research_response

    assert response["summary"] == "BAE Systems has current 2026 pursuit triggers."
    assert response["public_company_snapshot"] == "BAE Systems is a global defense contractor with public sector end-market exposure."
    assert response["public_strategy_priorities"] == [
        "2026 defense modernization demand | program execution and cyber pressure"
    ]
    assert response["public_filing_financial_signals"] == [
        "2026 annual report | Cyber and program execution risk | Risk leaders may need support | Risk/compliance lane"
    ]
    assert response["public_competitive_context"][0].startswith("Competes in defense electronics")
    assert response["public_customer_contract_signals"][0].startswith("2026 contract activity")
    assert response["public_likely_needs"] == [
        "Cyber compliance support | defense modernization and risk disclosure | CISO/risk | Medium | Validate active programs"
    ]
    assert response["public_people_targets"] == [
        "Jane Doe | CIO | Technology | Owns modernization | 2026 company source"
    ]
    assert response["public_people_moves"][0].startswith("John Smith | Appointed CFO")
    assert response["public_buyer_map"][0].startswith("Economic buyer | CFO office")
    assert response["public_buying_triggers"][0].startswith("2026 modernization announcement")
    assert response["public_recommended_actions"] == [
        "Ask analyst to validate CIO direct reports and recent procurement."
    ]
    assert response["freshness_assessment"]["stale_only"] is False
