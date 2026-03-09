"""
Unit tests for DeepResearchClient citation extraction fallbacks.
"""
from types import SimpleNamespace

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.deep_research_client import DeepResearchClient, DeepResearchCitation, DeepResearchReport


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


def test_merge_streamed_citations_adds_urls_not_in_final_message():
    client = _client()
    report = DeepResearchReport(
        summary="summary",
        sections=[],
        citations=[DeepResearchCitation(title="A", url="https://example.com/a")],
        metadata={},
    )

    merged = client._merge_streamed_citations(
        report=report,
        streamed_urls={"https://example.com/a", "https://example.com/b"},
    )

    urls = {citation.url for citation in merged.citations}
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls
    assert len(urls) == 2


def test_merge_streamed_citations_filters_bing_search_wrapper_urls():
    client = _client()
    report = DeepResearchReport(
        summary="summary",
        sections=[],
        citations=[],
        metadata={},
    )

    merged = client._merge_streamed_citations(
        report=report,
        streamed_urls={
            "https://www.bing.com/search?q=capital+one+people+moves",
            "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
        },
    )

    urls = {citation.url for citation in merged.citations}
    assert "https://www.bing.com/search?q=capital+one+people+moves" not in urls
    assert "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly" in urls


def test_dedupe_citations_populates_origin_type():
    client = _client()
    citations = [
        DeepResearchCitation(
            title="SEC source",
            url="https://www.sec.gov/Archives/edgar/data/123/abc.htm",
        ),
        DeepResearchCitation(
            title="Issuer source",
            url="https://investor.examplebank.com/news-release",
        ),
        DeepResearchCitation(
            title="Media source",
            url="https://www.reuters.com/world/us/example-story/",
        ),
        DeepResearchCitation(
            title="Social source",
            url="https://www.linkedin.com/posts/example_exec_post",
        ),
    ]

    deduped = client._dedupe_citations(citations)
    origin_by_url = {item.url: item.origin_type for item in deduped}

    assert origin_by_url["https://www.sec.gov/Archives/edgar/data/123/abc.htm"] == "regulatory"
    assert origin_by_url["https://investor.examplebank.com/news-release"] == "issuer"
    assert origin_by_url["https://www.reuters.com/world/us/example-story/"] == "media"
    assert origin_by_url["https://www.linkedin.com/posts/example_exec_post"] == "social"


def test_canonicalize_url_removes_tracking_query_parameters():
    client = _client()
    canonical = client._canonicalize_url(
        "https://example.com/path?utm_source=foo&id=123&fbclid=abc"
    )

    assert canonical == "https://example.com/path?id=123"


def test_build_source_provenance_counts():
    client = _client()
    counts = client._build_source_provenance_counts(
        [
            DeepResearchCitation(title="a", url="https://sec.gov/a", origin_type="regulatory"),
            DeepResearchCitation(title="b", url="https://issuer.example.com/b", origin_type="issuer"),
            DeepResearchCitation(title="c", url="https://linkedin.com/c", origin_type="social"),
            DeepResearchCitation(title="d", url="https://media.example.com/d", origin_type="media"),
        ]
    )

    assert counts["regulatory"] == 1
    assert counts["issuer"] == 1
    assert counts["social"] == 1
    assert counts["media"] == 1
