"""
Centralized question classifier for routing and tool orchestration.

This module is the single source of truth for:
- Label extraction from free text (multi-label via classify_topics, primary via classify_primary)
- Whether a question needs analyst synthesis (needs_analyst)
- Which GWBS scopes to run for a given label (scopes_for_label)

Labels supported: risk, financial, competitive, regulatory, strategic, timeline, general
"""
from __future__ import annotations
from typing import List
import re

# Compiled regex patterns for label detection (order doesn't imply priority)
_PATTERNS = {
    "risk": [
        re.compile(r"\b(risk|downside|exposure|threat|vulnerab)", re.I),
        re.compile(r"\b(credit risk|regulatory risk|operational risk|cyber|lawsuit|fine)\b", re.I),
    ],
    "financial": [
        re.compile(r"\b(revenue|earnings?|profit|loss|margin|guidance|forecast)\b", re.I),
        re.compile(r"\b(financial impact|capex|opex|cash flow)\b", re.I),
    ],
    "competitive": [
        re.compile(r"\b(competitor|competitive|market share|position|moat|benchmark|vs|versus)\b", re.I),
    ],
    "regulatory": [
        re.compile(r"\b(regulatory|regulation|compliance|legal|SEC|DOJ|FTC|antitrust)\b", re.I),
        re.compile(r"\b(filing|10-?K|10-?Q|8-?K|consent decree|settlement)\b", re.I),
    ],
    "strategic": [
        re.compile(r"\b(strategy|strategic|roadmap|future|plan|initiative|priorit(?:y|ies))\b", re.I),
        re.compile(r"\b(product|launch|expansion|hiring|acquisition|divestiture)\b", re.I),
    ],
    "timeline": [
        re.compile(r"\b(when|timeline|by when|deadline|date)\b", re.I),
    ],
}

# Canonical scopes to use per label for GWBS queries
_SCOPES = {
    "financial": ["news", "sec_filings"],
    "risk": ["news", "sec_filings"],
    "competitive": ["news", "industry_context"],
    "regulatory": ["sec_filings", "news"],
    "strategic": ["news", "industry_context"],
    "timeline": ["news", "sec_filings"],
    # For general asks, include both news and industry context to broaden coverage
    "general": ["news", "industry_context"],
}

_PRIMARY_PRIORITY = [
    # Slight preference ordering for a single primary label
    "regulatory",
    "financial",
    "risk",
    "strategic",
    "competitive",
    "timeline",
]

_SYNTHESIS_HINT = re.compile(r"\b(why|impact|angle|priority|prioritize|timeline|how)\b", re.I)


def classify_topics(text: str) -> List[str]:
    """Return zero or more labels detected in the text."""
    if not text:
        return []
    out: List[str] = []
    for label, regs in _PATTERNS.items():
        if any(r.search(text) for r in regs):
            out.append(label)
    return out


def classify_primary(text: str) -> str:
    """Return the single best label, or 'general' if none found."""
    topics = set(classify_topics(text))
    if not topics:
        return "general"
    for label in _PRIMARY_PRIORITY:
        if label in topics:
            return label
    # fallback to the first detected
    return next(iter(topics))


def needs_analyst(label: str, text: str) -> bool:
    """Return True if the question implies synthesis (why/how/impact/angle/priority/timeline)."""
    if label in {"risk", "financial", "regulatory", "strategic", "timeline"}:
        return True
    if _SYNTHESIS_HINT.search(text or ""):
        return True
    return False


def scopes_for_label(label: str) -> List[str]:
    """Return the canonical GWBS scopes for a label."""
    return _SCOPES.get(label, _SCOPES["general"])

