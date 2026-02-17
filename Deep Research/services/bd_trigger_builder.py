"""
Deterministic BD trigger construction from form/session/query input.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger


_SIGNAL_MAP = {
    "cmmc": "CMMC",
    "iv&v": "IV&V",
    "ivv": "IV&V",
    "independent verification": "IV&V",
    "independent validation": "IV&V",
    "rmf": "RMF",
    "risk": "Risk",
    "m&a": "M&A",
    "merger": "M&A",
    "acquisition": "M&A",
    "leadership": "Leadership",
}

_MONEY_WITH_SUFFIX_PATTERN = re.compile(
    r"(?i)\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)\b"
)
_MONEY_NUMBER_PATTERN = re.compile(
    r"(?i)\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)"
)
_TIME_WINDOW_PATTERN = re.compile(
    r"(?i)(?:past|last|within|over\s+the\s+past)\s+(\d{1,4})\s+days?"
)
_COMPANY_FOR_PATTERN = re.compile(r"(?i)\bfor\s+([^,\n.;:]+)")


def build_bd_trigger(
    sector: str,
    user_query: str,
    session_params: Optional[Dict[str, Any]] = None
) -> BDTrigger:
    """Build a normalized BDTrigger from UI/session parameters and free-form query text."""
    params = session_params or {}
    normalized_sector = _normalize_sector(params.get("sector") or sector)

    signals = _parse_signals(params.get("signals"))
    if not signals:
        signals = _infer_signals(user_query)

    company_focus = (
        _clean_text(params.get("company"))
        or _clean_text(params.get("company_focus"))
        or _infer_company_focus(user_query)
    )
    geography = _normalize_geography(params.get("geography")) or _normalize_geography(user_query)

    time_window_days = (
        _parse_time_window_days(params.get("time_window"))
        or _parse_time_window_days(user_query)
        or 30
    )
    time_window_days = max(1, min(365, time_window_days))

    min_value_usd = (
        _parse_min_value_usd(params.get("min_value"))
        or _parse_min_value_usd(user_query)
    )

    return BDTrigger(
        sector=normalized_sector,
        signals=signals,
        company_focus=company_focus,
        geography=geography,
        time_window_days=time_window_days,
        min_value_usd=min_value_usd,
    )


def _normalize_sector(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "General"
    text = text.replace("_", " ")
    return " ".join(part if part.isupper() else part.capitalize() for part in text.split())


def _parse_signals(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = [str(item).strip() for item in value if str(item).strip()]
    else:
        raw_text = str(value).strip()
        if not raw_text:
            return []
        raw_items = [item.strip() for item in re.split(r"[;,|]", raw_text) if item.strip()]

    normalized: List[str] = []
    seen = set()
    for item in raw_items:
        canonical = _canonical_signal(item)
        if canonical and canonical.lower() not in seen:
            normalized.append(canonical)
            seen.add(canonical.lower())
    return normalized


def _infer_signals(query: str) -> List[str]:
    query_lower = (query or "").lower()
    inferred: List[str] = []
    for hint, canonical in _SIGNAL_MAP.items():
        if hint in query_lower and canonical not in inferred:
            inferred.append(canonical)
    return inferred


def _canonical_signal(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    lowered = raw.lower()
    for hint, canonical in _SIGNAL_MAP.items():
        if hint in lowered:
            return canonical
    return raw


def _infer_company_focus(query: str) -> Optional[str]:
    query_text = query or ""
    match = _COMPANY_FOR_PATTERN.search(query_text)
    if not match:
        return None

    candidate = match.group(1).strip()
    split_tokens = [
        " focusing ",
        " focus ",
        " with ",
        " within ",
        " across ",
        " over ",
        " including ",
        " include ",
        " using ",
        " where ",
        " that ",
    ]
    lowered = f" {candidate.lower()} "
    for token in split_tokens:
        token_idx = lowered.find(token)
        if token_idx > 0:
            candidate = candidate[: token_idx].strip()
            break

    candidate = candidate.strip(" -,:;.")
    if not candidate or candidate.lower() in {"the", "all", "opportunities"}:
        return None
    return candidate


def _normalize_geography(value: Any) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    lowered = text.lower()
    if "conus" in lowered and "oconus" in lowered:
        return "CONUS+OCONUS"
    if "conus" in lowered or "continental united states" in lowered:
        return "CONUS"
    if "oconus" in lowered:
        return "OCONUS"
    if "global" in lowered or "worldwide" in lowered:
        return "Global"
    return text


def _parse_time_window_days(value: Any) -> Optional[int]:
    text = _clean_text(value)
    if not text:
        return None
    match = _TIME_WINDOW_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_min_value_usd(value: Any) -> Optional[int]:
    text = _clean_text(value)
    if not text:
        return None

    suffix_match = _MONEY_WITH_SUFFIX_PATTERN.search(text)
    if suffix_match:
        amount = _to_float(suffix_match.group(1))
        suffix = suffix_match.group(2).lower()
        multiplier = {
            "k": 1_000,
            "thousand": 1_000,
            "m": 1_000_000,
            "million": 1_000_000,
            "b": 1_000_000_000,
            "billion": 1_000_000_000,
        }.get(suffix)
        if multiplier is not None:
            return int(amount * multiplier)

    numeric_only = re.fullmatch(r"\$?\s*\d+(?:,\d{3})*(?:\.\d+)?\s*", text)
    if numeric_only:
        number_match = _MONEY_NUMBER_PATTERN.search(text)
        if number_match:
            return int(_to_float(number_match.group(1)))

    has_money_context = re.search(
        r"(?i)(?:\$|usd|dollar|min(?:imum)?\s+(?:contract\s+)?value|contract\s+value)",
        text,
    )
    if not has_money_context:
        return None

    number_match = _MONEY_NUMBER_PATTERN.search(text)
    if number_match:
        return int(_to_float(number_match.group(1)))
    return None


def _to_float(raw: str) -> float:
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "none", "null"}:
        return None
    return text
