"""
Helpers for converting Deep Research response payloads to markdown.
"""
from __future__ import annotations

from typing import Any, Dict, List

FS_SIGNAL_KEYWORDS: Dict[str, List[str]] = {
    "FS.CONSUMER.LITIGATION_SETTLEMENT": [
        "settlement",
        "class-action",
        "class action",
        "consent order",
        "enforcement",
        "civil money penalty",
        "restitution",
        "lawsuit",
    ],
    "FS.MODEL_RISK.FINDINGS": [
        "model risk",
        "sr 11-7",
        "model validation",
        "model governance",
        "occ 2011-12",
    ],
    "FS.EXEC.TRANSITION": [
        "appointed",
        "named",
        "joined",
        "rejoined",
        "promoted",
        "chief risk officer",
        "cfo",
        "cco",
        "board",
        "committee",
        "people move",
    ],
    "FS.STRESS_TEST.ISSUES": [
        "stress test",
        "ccar",
        "dfast",
        "stress capital buffer",
        "scb",
    ],
    "FS.REGULATORY.DEADLINE": [
        "deadline",
        "due by",
        "effective",
        "implementation date",
        "within 120 days",
        "submission",
    ],
    "FS.AML.BSA_FINDINGS": [
        "aml",
        "bsa",
        "fincen",
        "kyc",
        "cdd",
        "sanctions",
        "suspicious activity",
    ],
    "FS.CECL.IMPLEMENTATION": [
        "cecl",
        "asc 326",
        "expected credit loss",
        "allowance",
    ],
}


def build_section_source_map(response: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map each section title to its citation URLs."""
    section_source_map: Dict[str, List[str]] = {}
    for index, section in enumerate(response.get("sections", []) or [], 1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or f"Section {index}").strip() or f"Section {index}"
        urls: List[str] = []
        seen = set()
        for citation in section.get("citations", []) or []:
            if not isinstance(citation, dict):
                continue
            url = str(citation.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            urls.append(url)
        if urls:
            section_source_map[title] = urls
    return section_source_map


def build_signal_source_candidates(
    response: Dict[str, Any],
    section_source_map: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """Build coarse signal-to-source candidates from section content + heading keywords."""
    signal_source_candidates: Dict[str, List[str]] = {}
    for signal_code in FS_SIGNAL_KEYWORDS:
        signal_source_candidates[signal_code] = []

    for index, section in enumerate(response.get("sections", []) or [], 1):
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or f"Section {index}").strip() or f"Section {index}"
        content = str(section.get("content") or "")
        text_blob = f"{title}\n{content}".lower()
        urls = section_source_map.get(title, [])
        if not urls:
            continue

        for signal_code, keywords in FS_SIGNAL_KEYWORDS.items():
            if not any(keyword in text_blob for keyword in keywords):
                continue
            existing = {url.lower() for url in signal_source_candidates[signal_code]}
            for url in urls:
                if url.lower() not in existing:
                    signal_source_candidates[signal_code].append(url)
                    existing.add(url.lower())

    # If summary strongly references a signal but no section mapping matched, allow fallback to global citations.
    summary = str(response.get("summary") or "").lower()
    global_urls: List[str] = []
    seen_global = set()
    for citation in response.get("citations", []) or []:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = url.lower()
        if key in seen_global:
            continue
        seen_global.add(key)
        global_urls.append(url)

    for signal_code, keywords in FS_SIGNAL_KEYWORDS.items():
        if signal_source_candidates[signal_code]:
            continue
        if not summary or not any(keyword in summary for keyword in keywords):
            continue
        signal_source_candidates[signal_code] = list(global_urls[:6])

    return signal_source_candidates


def build_structured_evidence_map(response: Dict[str, Any]) -> Dict[str, Any]:
    """Build non-breaking normalization metadata from structured DR response."""
    section_source_map = build_section_source_map(response)
    signal_source_candidates = build_signal_source_candidates(response, section_source_map)
    return {
        "section_source_map": section_source_map,
        "signal_source_candidates": signal_source_candidates,
    }


def format_deep_research_response_as_markdown(response: Dict[str, Any]) -> str:
    """Convert a Deep Research response dict into markdown for BD orchestration."""
    lines: List[str] = []

    summary = response.get("summary", "")
    if summary:
        lines.append("# Executive Summary")
        lines.append(summary)
        lines.append("")

    for section in response.get("sections", []):
        title = section.get("title", "Findings")
        content = section.get("content", "")
        if content:
            lines.append(f"## {title}")
            lines.append(content)
            section_citations = section.get("citations", []) or []
            if section_citations:
                lines.append("")
                lines.append("### Section Sources")
                seen = set()
                for cite in section_citations:
                    if not isinstance(cite, dict):
                        continue
                    url = str(cite.get("url") or "").strip()
                    label = str(cite.get("title") or url).strip() or url
                    if not url or not url.startswith(("http://", "https://")):
                        continue
                    key = url.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(f"• {label}: {url}")
            lines.append("")

    citations = response.get("citations", [])
    if citations:
        lines.append("## Sources")
        for cite in citations:
            url = cite.get("url", "")
            title = cite.get("title", url)
            if url:
                lines.append(f"• {title}: {url}")
        lines.append("")

    return "\n".join(lines)
