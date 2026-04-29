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
            "company_overview": "BAE Systems is a defense contractor with public-sector customer exposure.",
            "strategic_priorities": ["Modernization and program execution pressure | public signal"],
            "financial_filing_signals": ["2026 filing | cyber and contract execution risk | risk lane"],
            "competitive_context": ["Defense systems competition creates delivery and differentiation pressure."],
            "customer_contract_signals": ["2026 contract activity | government customer demand"],
            "likely_needs": ["Cyber compliance support | risk signal | CISO/risk | Medium"],
            "relationship_posture": "Known relationships are limited; warm-path coverage appears sparse.",
            "buyer_posture": "Known buyer coverage is concentrated in finance and technology.",
            "leadership_coverage_summary": "Public and ProConnect coverage surfaces leadership across executive, finance, technology, and operations lanes.",
            "top_openings": [
                "Cyber and technology modernization advisory",
                "Operational transformation and PMO support",
            ],
            "people_to_prioritize": ["Jane Doe | CIO | Technology modernization owner"],
            "recent_people_moves": ["John Smith | Appointed CFO | 2026"],
            "buying_committee_map": ["Economic buyer | CFO office | Confirm budget owner"],
            "buying_triggers": ["2026 modernization announcement | CIO lane"],
            "relationship_hooks": ["Board overlap hypothesis | public source"],
            "recommended_asks": ["Ask for CIO intro path."],
            "analyst_follow_ups": ["Validate direct reports."],
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
    assert "## Company Overview" in markdown
    assert "BAE Systems is a defense contractor" in markdown
    assert "## Filings / Financial / Risk Signals" in markdown
    assert "## Competitive / Market Context" in markdown
    assert "## Likely Needs / White Space" in markdown
    assert "## People To Pursue" in markdown
    assert "Jane Doe | CIO" in markdown
    assert "## Buying Committee / Org Map" in markdown
    assert "## Recommended MD Actions" in markdown
    assert "## Suggested Plays" in markdown
    assert "## Key Gaps" in markdown
    assert "Treat this as a target-account opening brief" in markdown
    assert "[Example](https://example.com)" in markdown
