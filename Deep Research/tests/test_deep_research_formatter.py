"""
Unit tests for Deep Research formatter structured evidence helpers.
"""

from services.deep_research_formatter import (
    build_section_source_map,
    build_signal_source_candidates,
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)


def _sample_response():
    return {
        "summary": "Capital One announced leadership updates and a regulatory deadline.",
        "sections": [
            {
                "title": "Leadership Changes",
                "content": "Capital One appointed a Business Chief Risk Officer.",
                "citations": [
                    {
                        "title": "People Move",
                        "url": "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
                    }
                ],
            },
            {
                "title": "Regulatory Deadline",
                "content": "The OCC required submission within 120 days.",
                "citations": [
                    {
                        "title": "OCC Release",
                        "url": "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html",
                    }
                ],
            },
        ],
        "citations": [
            {
                "title": "Global Source",
                "url": "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html",
            }
        ],
    }


def test_build_section_source_map_uses_section_citations():
    response = _sample_response()
    section_map = build_section_source_map(response)

    assert "Leadership Changes" in section_map
    assert "Regulatory Deadline" in section_map
    assert section_map["Leadership Changes"] == [
        "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly"
    ]


def test_build_signal_source_candidates_maps_section_content_to_signals():
    response = _sample_response()
    section_map = build_section_source_map(response)
    signal_candidates = build_signal_source_candidates(response, section_map)

    assert signal_candidates["FS.EXEC.TRANSITION"]
    assert signal_candidates["FS.REGULATORY.DEADLINE"]
    assert "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly" in signal_candidates["FS.EXEC.TRANSITION"]
    assert "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html" in signal_candidates["FS.REGULATORY.DEADLINE"]


def test_build_structured_evidence_map_contains_required_keys():
    response = _sample_response()
    evidence_map = build_structured_evidence_map(response)

    assert "section_source_map" in evidence_map
    assert "signal_source_candidates" in evidence_map
    assert evidence_map["section_source_map"]["Leadership Changes"]


def test_markdown_formatter_preserves_section_source_blocks():
    response = _sample_response()
    markdown = format_deep_research_response_as_markdown(response)

    assert "### Section Sources" in markdown
    assert "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly" in markdown
    assert "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html" in markdown
