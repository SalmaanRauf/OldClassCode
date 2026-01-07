"""
GWBS (Grounding with Bing Search) tool wrappers.
"""
from __future__ import annotations
from typing import Dict

from models.schemas import CompanyRef, Citation, GWBSSection, FullGWBS, ScopeLiteral
from services.cache import TTLCache, cache_key
from agents.bing_data_extraction_agent import BingDataExtractionAgent

_gwbs_cache = TTLCache(maxsize=256, ttl_seconds=1800)

def _to_citations_md_list(md: str) -> list[Citation]:
    import re
    out: list[Citation] = []
    if not md:
        return out
    for line in (md or "").splitlines():
        m = re.match(r"^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)", line.strip())
        if m:
            out.append(Citation(title=m.group("title"), url=m.group("url")))
    return out

def gwbs_search(scope: ScopeLiteral, company: CompanyRef, agent: BingDataExtractionAgent) -> GWBSSection:
    """
    Execute a GWBS search for a single scope for the given company.

    Returns a typed `GWBSSection` containing summary text, parsed citations,
    and any optional audit info available from the underlying agent.
    Results are cached in-memory for a short TTL to reduce duplicate work.
    """
    ckey = cache_key("gwbs_search", scope, company.name, company.ticker)
    cached = _gwbs_cache.get(ckey)
    if cached:
        return cached
    if scope == "sec_filings":
        raw = agent.search_sec_filings(company.name)
    elif scope == "news":
        raw = agent.search_news(company.name)
    elif scope == "procurement":
        raw = agent.search_procurement(company.name)
    elif scope == "earnings":
        raw = agent.search_earnings(company.name)
    elif scope == "industry_context":
        raw = agent.search_industry_context(company.name)
    elif scope == "competitors":
        # Use a public agent method for competitor research to avoid relying on private APIs
        raw = agent.search_competitors(company.name)
    else:
        raise ValueError(f"Unknown GWBS scope: {scope}")
    section = GWBSSection(
        scope=scope,
        summary=(raw or {}).get("summary", ""),
        citations=_to_citations_md_list((raw or {}).get("citations_md", "")),
        audit=(raw or {}).get("audit", {}),
    )
    _gwbs_cache.set(ckey, section)
    return section

def gwbs_full(company: CompanyRef, agent: BingDataExtractionAgent) -> FullGWBS:
    scopes = ["sec_filings", "news", "procurement", "earnings", "industry_context"]
    sections: Dict[str, GWBSSection] = {}
    for s in scopes:
        sections[s] = gwbs_search(s, company, agent)
    return FullGWBS(company=company, sections=sections)