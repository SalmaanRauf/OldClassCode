"""
Tests for response formatter citation quality handling.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.response_formatter import ResponseFormatter
from models.schemas import Citation


def test_format_citations_filters_low_signal_and_dedupes():
    formatter = ResponseFormatter()
    citations = [
        Citation(title="SAM.gov | Home", url="https://sam.gov/"),
        Citation(title="Search", url="https://example.com/search?q=cmmc"),
        Citation(title="WS-26-0001", url="https://sam.gov/opp/abc123/view"),
        Citation(title="WS-26-0001 Duplicate", url="https://sam.gov/opp/abc123/view#section"),
    ]

    formatted = formatter._format_citations(citations)

    assert len(formatted) == 1
    assert formatted[0]["url"] == "https://sam.gov/opp/abc123/view"
