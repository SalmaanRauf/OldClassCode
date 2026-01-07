"""
Analyst tool wrappers that expose a typed interface over AnalystAgent.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Set

from models.schemas import AnalysisItem, AnalysisEvent, Citation
from agents.analyst_agent import AnalystAgent


async def analyst_synthesis(items: List[AnalysisItem], analyst: AnalystAgent) -> List[AnalysisEvent]:
    wire_items = []
    for it in items:
        wire_items.append(
            {
                "company": it.company,
                "title": it.title,
                "description": it.content,
                "content": it.content,
                "raw_data": it.raw,
                "citations": [c.dict() for c in it.citations],
            }
        )
    results = await analyst.analyze_all_data(wire_items)
    events: List[AnalysisEvent] = []
    for ev in results or []:
        title = ev.get("title") or ev.get("headline") or "Untitled"
        insights = ev.get("insights") or {}
        raw_data = ev.get("raw_data") if isinstance(ev, dict) else {}
        allowed_map: Dict[str, str] = {}

        def _record_allowed(url: Optional[str], title: Optional[str]) -> None:
            if not url or not isinstance(url, str):
                return
            if not url.startswith("http"):
                return
            if url not in allowed_map:
                allowed_map[url] = title or url

        cites_raw = ev.get("citations") or []
        if not cites_raw and isinstance(raw_data, dict):
            md = raw_data.get("citations_md", "")
            cites_raw = _citations_from_md(md)

        for entry in cites_raw or []:
            try:
                if isinstance(entry, Citation):
                    _record_allowed(entry.url, entry.title)
                elif isinstance(entry, dict):
                    _record_allowed(entry.get("url"), entry.get("title"))
            except Exception:
                continue

        citations: List[Citation] = []
        seen_urls: Set[str] = set()
        for url, title in allowed_map.items():
            if url in seen_urls:
                continue
            citations.append(Citation(title=title, url=url))
            seen_urls.add(url)

        if isinstance(insights, dict):
            for url in insights.get("source_urls", []) or []:
                if not isinstance(url, str):
                    continue
                if url not in allowed_map:
                    continue
                if url in seen_urls:
                    continue
                citations.append(Citation(title=allowed_map.get(url, url), url=url))
                seen_urls.add(url)
        meta = {k: v for k, v in ev.items() if k not in {"title", "insights", "citations"}}
        events.append(AnalysisEvent(title=title, insights=insights, citations=citations, meta=meta))
    return events


def _citations_from_md(md: str) -> list[dict]:
    import re
    out: list[dict] = []
    if not md:
        return out
    for line in (md or "").splitlines():
        m = re.match(r"^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)", line.strip())
        if m:
            out.append({"title": m.group("title"), "url": m.group("url")})
    return out
