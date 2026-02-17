"""
Citation quality scoring helpers for display-layer source ranking.
"""
from __future__ import annotations

import re
from typing import Dict, List


_LOW_SIGNAL_PATTERNS = (
    "/search",
    "?q=",
    "/login",
    "/signin",
    "/home",
    "return to workspace",
    "/portal",
)
_HIGH_SIGNAL_HINTS = (
    "solicitation",
    "opportunity",
    "notice",
    "contract",
    "award",
    "article",
    "report",
    "announcement",
    "sam.gov",
)


def is_low_signal_url(url: str, title: str = "") -> bool:
    """Identify URLs that are usually low-value for evidence display."""
    lowered_url = (url or "").lower().strip()
    lowered_title = (title or "").lower().strip()
    if not lowered_url:
        return True

    if any(pattern in lowered_url for pattern in _LOW_SIGNAL_PATTERNS):
        return True

    # Root/home pages are low signal unless title clearly indicates a specific artifact.
    if re.match(r"^https?://[^/]+/?$", lowered_url) and not any(
        hint in lowered_title for hint in _HIGH_SIGNAL_HINTS
    ):
        return True

    return False


def rank_citations(citations: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Rank citations deterministically by quality and stability of evidence signal."""
    unique: List[Dict[str, str]] = []
    seen = set()
    for citation in citations:
        url = (citation or {}).get("url", "")
        title = (citation or {}).get("title", url)
        key = (url.strip().lower(), title.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append({"title": title, "url": url})

    def score(citation: Dict[str, str]) -> tuple[int, int, str, str]:
        title = citation.get("title", "")
        url = citation.get("url", "")
        lowered = f"{title} {url}".lower()
        low_signal = is_low_signal_url(url, title)
        high_hint_count = sum(1 for hint in _HIGH_SIGNAL_HINTS if hint in lowered)
        url_depth = len([part for part in (url or "").split("/") if part])
        return (
            0 if low_signal else 1,
            high_hint_count,
            url_depth,
            (title or "").lower(),
        )

    return sorted(unique, key=score, reverse=True)

