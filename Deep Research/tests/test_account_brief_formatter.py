"""
Tests for account brief markdown formatting.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.account_brief_formatter import format_account_brief_markdown  # noqa: E402


def test_format_account_brief_markdown_renders_expected_sections() -> None:
    markdown = format_account_brief_markdown(
        company_name="BAE Systems",
        synthesis={
            "headline": "BAE Systems shows public modernization pressure with limited known internal coverage.",
            "account_status_summary": "No known ProConnect work found. MSA not found in ProConnect payload.",
            "why_now": "Public signals point to defense modernization, cyber pressure, and operational transformation demand.",
            "relationship_posture": "Known relationships are limited; warm-path coverage appears sparse.",
            "buyer_posture": "Known buyer coverage is concentrated in finance and technology.",
            "leadership_coverage_summary": "Public and ProConnect coverage surfaces leadership across executive, finance, technology, and operations lanes.",
            "top_openings": [
                "Cyber and technology modernization advisory",
                "Operational transformation and PMO support",
            ],
            "suggested_plays": [
                "Lead with a cyber and technology-risk modernization discussion tied to defense transformation pressure.",
                "Map finance and operations buyers to specific pursuit owners before outreach.",
            ],
            "key_gaps": [
                "True 3-level reporting hierarchy is not available.",
                "RHI account-level work coverage is not available.",
            ],
            "takeaway": "Treat this as a target-account opening brief, not a complete relationship map.",
        },
        proconnect_summary={"known_protiviti_team": {"account_executive": {"name": "Jane Doe"}}},
        deep_research_summary={"citations": [{"title": "Example", "url": "https://example.com"}]},
    )

    assert "# BAE Systems" in markdown
    assert "## Account Status" in markdown
    assert "## Why Now" in markdown
    assert "## Suggested Plays" in markdown
    assert "## Key Gaps" in markdown
    assert "Treat this as a target-account opening brief" in markdown
    assert "[Example](https://example.com)" in markdown
