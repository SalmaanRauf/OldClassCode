"""
Unit tests for DeepResearchClient citation extraction fallbacks.
"""
from types import SimpleNamespace

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.deep_research_client import DeepResearchClient


def _client() -> DeepResearchClient:
    # Bypass __init__ because these tests only exercise pure parsing helpers.
    return DeepResearchClient.__new__(DeepResearchClient)


def _text_block(value: str, annotations=None, name: str = ""):
    return SimpleNamespace(
        type="text",
        name=name,
        text=SimpleNamespace(value=value, annotations=annotations or []),
    )


def _url_annotation(url: str, title: str = ""):
    return SimpleNamespace(
        url_citation=SimpleNamespace(url=url, title=title or url),
    )


def test_parse_message_captures_plain_text_urls_when_annotations_missing():
    client = _client()
    message = SimpleNamespace(
        content=[
            _text_block(
                "Summary includes https://example.com/source-a and supporting context.",
                annotations=[],
            )
        ],
        url_citation_annotations=[],
        text="",
    )

    report = client._parse_message(message)

    urls = {citation.url for citation in report.citations}
    assert "https://example.com/source-a" in urls


def test_parse_message_dedupes_mixed_annotation_and_plain_text_urls():
    client = _client()
    duplicate_url = "https://example.com/source-a"
    unique_url = "https://example.com/source-b"
    message = SimpleNamespace(
        content=[
            _text_block(
                f"Summary includes {duplicate_url} and {unique_url}.",
                annotations=[_url_annotation(duplicate_url, "Source A")],
            )
        ],
        url_citation_annotations=[
            _url_annotation(duplicate_url, "Source A"),
        ],
        text="",
    )

    report = client._parse_message(message)

    urls = [citation.url for citation in report.citations]
    assert urls.count(duplicate_url) == 1
    assert urls.count(unique_url) == 1
    assert len(urls) == 2
