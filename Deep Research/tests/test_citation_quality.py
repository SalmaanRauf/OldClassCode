"""
Tests for citation quality ranking and filtering.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.citation_quality import is_low_signal_url, rank_citations


def test_low_signal_url_detection():
    assert is_low_signal_url("https://sam.gov/search")
    assert is_low_signal_url("https://example.com/login")
    assert is_low_signal_url("https://sam.gov/")
    assert not is_low_signal_url(
        "https://sam.gov/opp/abc123/view",
        "Contract Opportunity Notice",
    )


def test_rank_citations_prefers_direct_notice_urls():
    citations = [
        {"title": "SAM.gov | Home", "url": "https://sam.gov/"},
        {"title": "Contract Opportunity", "url": "https://sam.gov/opp/abc123/view"},
        {"title": "Search Results", "url": "https://sam.gov/search?q=cmmc"},
    ]

    ranked = rank_citations(citations)

    assert ranked[0]["url"] == "https://sam.gov/opp/abc123/view"
    assert ranked[-1]["url"] in {"https://sam.gov/", "https://sam.gov/search?q=cmmc"}


def test_rank_citations_is_stable_and_deduplicates():
    citations = [
        {"title": "Contract Opportunity", "url": "https://sam.gov/opp/abc123/view"},
        {"title": "Contract Opportunity", "url": "https://sam.gov/opp/abc123/view"},
        {"title": "Article", "url": "https://example.com/article/cmmc-update"},
    ]

    ranked_once = rank_citations(citations)
    ranked_twice = rank_citations(citations)

    assert ranked_once == ranked_twice
    assert len(ranked_once) == 2

