"""
Markdown formatting helpers for the ProConnect + Deep Research account brief.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


def format_account_brief_markdown(
    *,
    company_name: str,
    synthesis: Dict[str, Any],
    proconnect_summary: Dict[str, Any],
    deep_research_summary: Dict[str, Any],
) -> str:
    lines: List[str] = [f"# {company_name}", ""]

    headline = _text(synthesis.get("headline"))
    if headline:
        lines.extend([headline, ""])

    _append_section(lines, "Account Status", _text(synthesis.get("account_status_summary")))
    _append_section(lines, "Why Now", _text(synthesis.get("why_now")))
    _append_section(lines, "Relationship Posture", _text(synthesis.get("relationship_posture")))
    _append_section(lines, "Buyer Posture", _text(synthesis.get("buyer_posture")))
    _append_section(
        lines,
        "Leadership Coverage",
        _text(synthesis.get("leadership_coverage_summary")),
    )

    team = (proconnect_summary or {}).get("known_protiviti_team") or {}
    team_bits = []
    for key in ("account_executive", "account_pmo", "account_mdd"):
        item = team.get(key) if isinstance(team, dict) else None
        if isinstance(item, dict) and item.get("name"):
            team_bits.append(f"{key.replace('_', ' ').title()}: {item['name']}")
    if team_bits:
        _append_bullets(lines, "Known Protiviti Team", team_bits)

    _append_bullets(lines, "Top Openings", synthesis.get("top_openings") or [])
    _append_bullets(lines, "Suggested Plays", synthesis.get("suggested_plays") or [])
    _append_bullets(lines, "Key Gaps", synthesis.get("key_gaps") or [])

    takeaway = _text(synthesis.get("takeaway"))
    if takeaway:
        lines.extend(["## Takeaway", takeaway, ""])

    citations = _normalized_citations((deep_research_summary or {}).get("citations") or [])
    if citations:
        lines.append("## Sources")
        for citation in citations:
            lines.append(f"- [{citation['title']}]({citation['url']})")
        lines.append("")

    return "\n".join(lines).strip()


def _append_section(lines: List[str], title: str, text: str) -> None:
    if not text:
        return
    lines.extend([f"## {title}", text, ""])


def _append_bullets(lines: List[str], title: str, items: Iterable[Any]) -> None:
    rendered = [_text(item) for item in list(items or [])]
    rendered = [item for item in rendered if item]
    if not rendered:
        return
    lines.append(f"## {title}")
    for item in rendered:
        lines.append(f"- {item}")
    lines.append("")


def _normalized_citations(items: Iterable[Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    seen = set()
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append({"title": _text(item.get("title")) or url, "url": url})
    return rows


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
