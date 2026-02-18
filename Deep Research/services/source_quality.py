"""
Source quality filtering and ranking helpers for citation display.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse, urlunparse


LOW_SIGNAL_TITLE_PATTERNS = (
    "home",
    "login",
    "log in",
    "sign in",
    "search",
    "results",
    "archive",
)

LOW_SIGNAL_PATH_PATTERNS = (
    "/",
    "/home",
    "/index",
    "/index.html",
    "/login",
    "/signin",
    "/sign-in",
    "/search",
    "/results",
    "/archives",
    "/archive",
)

LOW_SIGNAL_QUERY_KEYS = {"q", "query", "search", "term", "s"}

DOMAIN_SCORE_HINTS = {
    ".gov": 8,
    ".mil": 8,
    "sam.gov": 8,
    "federalregister.gov": 7,
    "gao.gov": 7,
    "defense.gov": 6,
    "army.mil": 6,
    "navy.mil": 6,
    "af.mil": 6,
    "spaceforce.mil": 6,
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def is_valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_low_signal_source(title: str, url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "/").lower()
    title_l = title.lower()

    if path in LOW_SIGNAL_PATH_PATTERNS:
        return True
    if any(token in title_l for token in LOW_SIGNAL_TITLE_PATTERNS):
        return True

    query = parse_qs(parsed.query or "")
    if any(key.lower() in LOW_SIGNAL_QUERY_KEYS for key in query.keys()):
        return True

    # Generic landing pages that often provide little value as evidence.
    if path.count("/") <= 1 and not parsed.query:
        return True

    return False


def _source_score(title: str, url: str) -> int:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    score = 0

    for hint, weight in DOMAIN_SCORE_HINTS.items():
        if hint.startswith("."):
            if host.endswith(hint):
                score += weight
        elif hint in host:
            score += weight

    title_l = title.lower()
    if any(token in title_l for token in ("solicitation", "sources sought", "rfp", "sam.gov", "federal")):
        score += 2

    # Slightly prefer deeper content pages over generic paths.
    path_depth = len([segment for segment in (parsed.path or "").split("/") if segment])
    score += min(path_depth, 3)

    if is_low_signal_source(title, url):
        score -= 10

    return score


def rank_and_filter_citations(
    citations: List[Dict[str, Any]],
    limit: int = 20,
) -> List[Dict[str, str]]:
    """
    Filter low-signal citations and rank remaining sources by quality.
    """
    normalized: Dict[str, Dict[str, Any]] = {}
    low_signal_pool: List[Dict[str, Any]] = []

    for citation in citations or []:
        title = _as_text(citation.get("title") if isinstance(citation, dict) else getattr(citation, "title", ""))
        url = _as_text(citation.get("url") if isinstance(citation, dict) else getattr(citation, "url", ""))
        if not url or not is_valid_http_url(url):
            continue

        canonical_url = normalize_url(url)
        if canonical_url in normalized:
            continue

        item = {
            "title": title or canonical_url,
            "url": canonical_url,
            "score": _source_score(title or canonical_url, canonical_url),
        }

        if is_low_signal_source(item["title"], canonical_url):
            low_signal_pool.append(item)
        else:
            normalized[canonical_url] = item

    selected = list(normalized.values())
    if not selected and low_signal_pool:
        # Avoid empty source display when all sources are low-signal.
        selected = low_signal_pool

    selected.sort(key=lambda item: item["score"], reverse=True)
    trimmed = selected[: max(1, limit)]
    return [{"title": item["title"], "url": item["url"]} for item in trimmed]
