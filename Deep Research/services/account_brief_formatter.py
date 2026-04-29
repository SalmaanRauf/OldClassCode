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
    _append_section(lines, "Company Overview", _text(synthesis.get("company_overview")))
    _append_bullets(lines, "Strategy / Operating Pressure", synthesis.get("strategic_priorities") or [])
    _append_bullets(lines, "Filings / Financial / Risk Signals", synthesis.get("financial_filing_signals") or [])
    _append_bullets(lines, "Competitive / Market Context", synthesis.get("competitive_context") or [])
    _append_bullets(lines, "Customer / Contract / Procurement Signals", synthesis.get("customer_contract_signals") or [])
    _append_bullets(lines, "Likely Needs / White Space", synthesis.get("likely_needs") or [])
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

    _append_bullets(lines, "People To Pursue", synthesis.get("people_to_prioritize") or [])
    _append_bullets(lines, "Recent People Moves", synthesis.get("recent_people_moves") or [])
    _append_bullets(lines, "Buying Committee / Org Map", synthesis.get("buying_committee_map") or [])
    _append_bullets(lines, "Buying Triggers", synthesis.get("buying_triggers") or [])
    _append_bullets(lines, "Public Relationship Hooks", synthesis.get("relationship_hooks") or [])
    _append_bullets(lines, "Recommended MD Actions", synthesis.get("recommended_asks") or [])
    _append_bullets(lines, "Analyst Follow-Ups", synthesis.get("analyst_follow_ups") or [])
    _append_internal_evidence(lines, proconnect_summary)
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


def _append_internal_evidence(lines: List[str], proconnect_summary: Dict[str, Any]) -> None:
    if not isinstance(proconnect_summary, dict):
        return

    buyers = []
    for buyer in list(proconnect_summary.get("known_buyers") or [])[:5]:
        if not isinstance(buyer, dict):
            continue
        name = _text(buyer.get("name"))
        if not name:
            continue
        title = _text(buyer.get("title") or buyer.get("function"))
        wins = buyer.get("wins_5y")
        last_win = _text(buyer.get("last_opportunity_won_date"))
        buyers.append(
            f"{name}{f' | {title}' if title else ''}"
            f"{f' | wins 5y: {wins}' if wins not in (None, '') else ''}"
            f"{f' | last win: {last_win}' if last_win else ''}"
        )
    _append_bullets(lines, "Known Buyers From ProConnect", buyers)

    relationships = proconnect_summary.get("known_relationships") or {}
    relationship_rows = []
    if isinstance(relationships, dict):
        routes = relationships.get("relationship_routes") or []
        if routes:
            relationship_rows.append(f"Relationship routes surfaced: {', '.join(str(route) for route in routes)}")
        for label, key in (
            ("Protiviti alumni", "protiviti_alumni"),
            ("Connected colleagues", "connected_colleagues"),
        ):
            for item in list(((relationships.get(key) or {}).get("items") or []))[:5]:
                if not isinstance(item, dict):
                    continue
                name = _text(item.get("name"))
                title = _text(item.get("title"))
                employer = _text(item.get("employer"))
                if name:
                    relationship_rows.append(
                        f"{label}: {name}{f' | {title}' if title else ''}{f' | {employer}' if employer else ''}"
                    )
    _append_bullets(lines, "Known Account Relationships", relationship_rows)

    opportunities = []
    for opp in list(proconnect_summary.get("open_opportunities") or [])[:5]:
        if not isinstance(opp, dict):
            continue
        name = _text(opp.get("opportunity") or opp.get("solution") or opp.get("service_name"))
        if not name:
            continue
        stage = _text(opp.get("stage"))
        buyer = _text(opp.get("primary_key_buyer"))
        opportunities.append(
            f"{name}{f' | {stage}' if stage else ''}{f' | buyer: {buyer}' if buyer else ''}"
        )
    _append_bullets(lines, "Open ProConnect Opportunities", opportunities)


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
