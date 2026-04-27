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
    assert "FINANCIAL SERVICES BASE PROMPT" in package.system_prompt
    assert "Public Account Overlay" in package.system_prompt
    assert "public-account brief" in package.system_prompt.lower()


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
    ]
    for banned in banned_terms:
        assert banned not in combined_prompt


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
