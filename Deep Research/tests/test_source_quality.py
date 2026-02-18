"""
Tests for source quality filtering and ranking.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.source_quality import rank_and_filter_citations


def test_rank_and_filter_citations_drops_generic_pages():
    citations = [
        {"title": "SAM.gov | Home", "url": "https://sam.gov/"},
        {"title": "Bid Banana Login", "url": "https://bidbanana.com/login"},
        {"title": "WS-26-0001 - SAM.gov", "url": "https://sam.gov/opp/abc123/view"},
    ]

    filtered = rank_and_filter_citations(citations, limit=10)

    assert len(filtered) == 1
    assert filtered[0]["url"] == "https://sam.gov/opp/abc123/view"


def test_rank_and_filter_citations_falls_back_when_all_low_signal():
    citations = [
        {"title": "SAM.gov | Home", "url": "https://sam.gov/"},
        {"title": "Search", "url": "https://example.com/search?q=cmmc"},
    ]

    filtered = rank_and_filter_citations(citations, limit=10)

    assert len(filtered) >= 1
    assert filtered[0]["url"].startswith("https://")
