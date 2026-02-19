"""
Helpers for converting Deep Research response payloads to markdown.
"""
from __future__ import annotations

from typing import Any, Dict, List


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

