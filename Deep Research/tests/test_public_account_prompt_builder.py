"""
Tests for public-account Deep Research prompt composition.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.prompt_loader import PromptLoader  # noqa: E402
from services.public_account_prompt_builder import PublicAccountPromptBuilder  # noqa: E402


def _write_prompt_fixture(root: Path) -> PromptLoader:
    industries_dir = root / "industries"
    industries_dir.mkdir(parents=True, exist_ok=True)
    (industries_dir / "general.md").write_text("GENERAL BASE PROMPT", encoding="utf-8")
    (industries_dir / "financial_services.md").write_text("FINANCIAL SERVICES BASE PROMPT", encoding="utf-8")
    metadata = {
        "prompts": {
            "financial_services": {
                "version": "1.0",
                "last_updated": "2026-04-23",
                "display_name": "Financial Services",
                "description": "Banking and lending",
                "file": "industries/financial_services.md",
            },
            "general": {
                "version": "1.0",
                "last_updated": "2026-04-23",
                "display_name": "General",
                "description": "General research",
                "file": "industries/general.md",
            },
        }
    }
    (root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return PromptLoader(prompts_dir=root)


def test_builder_uses_prompt_loader_and_appends_public_overlay(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = PublicAccountPromptBuilder(prompt_loader=loader)

    package = builder.build(
        company_name="Fannie Mae",
        focus_hint="Focus on payments modernization and enterprise risk priorities.",
        industry="financial_services",
    )

    assert package.industry_key == "financial_services"
    assert "Public Account Pursuit Research" in package.system_prompt
    assert "Industry Source Guidance" in package.system_prompt
    assert "Financial Services" in package.system_prompt
    assert "financial" in package.system_prompt.lower()


def test_builder_generates_deterministic_public_only_prompt(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = PublicAccountPromptBuilder(prompt_loader=loader)

    package_a = builder.build(
        company_name="Fannie Mae",
        focus_hint="Focus on payments modernization and enterprise risk priorities.",
        industry="financial_services",
    )
    package_b = builder.build(
        company_name="Fannie Mae",
        focus_hint="Focus on payments modernization and enterprise risk priorities.",
        industry="financial_services",
    )

    assert package_a.user_prompt == package_b.user_prompt
    assert "Fannie Mae" in package_a.user_prompt
    assert "payments modernization" in package_a.user_prompt
    assert "Financial Services" in package_a.user_prompt

    combined_prompt = f"{package_a.system_prompt}\n{package_a.user_prompt}".lower()
    banned_terms = [
        "proconnect",
        "account_id",
        "warm intro",
        "relationship owner",
        "internal",
        "msa",
        "pipeline",
        "prior delivery",
        "buyer ownership",
        "account ownership",
        "salesforce",
        "protiviti",
        "robert half",
        "rhi",
    ]
    for banned in banned_terms:
        assert banned not in combined_prompt


def test_builder_forces_current_pursuit_research_window(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = PublicAccountPromptBuilder(prompt_loader=loader)

    package = builder.build(
        company_name="BAE Systems",
        focus_hint="Find active pursuit triggers for managing directors.",
        industry="general",
        as_of_date="2026-04-27",
    )

    combined_prompt = f"{package.system_prompt}\n{package.user_prompt}"
    assert "Current as of: 2026-04-27" in package.user_prompt
    assert "last 180 days" in combined_prompt
    assert "last 30-90 days" in combined_prompt
    assert "Do not rely on stale 2024-only material" in combined_prompt
    assert "upcoming pursuit" in combined_prompt.lower()
    assert "## People to Pursue" in combined_prompt
    assert "## Company Snapshot" in combined_prompt
    assert "## Filings, Financials, and Risk Signals" in combined_prompt
    assert "10-K" in combined_prompt
    assert "8-K" in combined_prompt
    assert "## Competitive and Market Context" in combined_prompt
    assert "## Likely Needs / White-Space Hypotheses" in combined_prompt
    assert "## Recent People Moves" in combined_prompt
    assert "## Buying Committee Map" in combined_prompt
    assert "## Recommended MD Actions This Week" in combined_prompt


def test_builder_omits_industry_line_when_no_explicit_industry_is_provided(tmp_path) -> None:
    loader = _write_prompt_fixture(tmp_path)
    builder = PublicAccountPromptBuilder(prompt_loader=loader)

    package = builder.build(
        company_name="BAE Systems",
        focus_hint=None,
        industry=None,
    )

    assert package.industry_key == "general"
    assert "Industry:" not in package.user_prompt
