"""
Helpers for building BD trigger context from user input and session params.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger


def sanitize_user_prompt_context(user_query: str, max_chars: int = 600) -> Optional[str]:
    text = re.sub(r"\s+", " ", (user_query or "").strip())
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars + 1]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip()


def _parse_signals_from_text(text: str) -> List[str]:
    lowered = (text or "").lower()
    candidates = [
        ("cmmc", "CMMC"),
        ("iv&v", "IV&V"),
        ("rmf", "RMF"),
        ("risk", "Risk"),
        ("m&a", "M&A"),
        ("leadership", "Leadership"),
    ]
    signals: List[str] = []
    for token, label in candidates:
        if token in lowered and label not in signals:
            signals.append(label)
    return signals


def _parse_signals(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n;]", value) if part.strip()]
    return []


def _parse_time_window_days(value: Any, fallback_text: str, default: int = 30) -> int:
    if isinstance(value, (int, float)):
        return max(1, min(365, int(value)))

    candidates = []
    if isinstance(value, str):
        candidates.append(value)
    candidates.append(fallback_text or "")
    for candidate in candidates:
        match = re.search(r"(?:past|last|within)\s+(\d+)\s+days?", candidate, re.IGNORECASE)
        if match:
            return max(1, min(365, int(match.group(1))))
    return default


def _parse_min_value_usd(value: Any, fallback_text: str) -> Optional[int]:
    if isinstance(value, (int, float)):
        parsed_value = int(value)
        return parsed_value if parsed_value >= 0 else None

    def _extract(text: str) -> Optional[int]:
        if not text:
            return None

        patterns = [
            r"(?:minimum|min)\s+(?:contract\s+)?value(?:\s+of)?\s*\$?\s*(\d+(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)\b",
            r"\$\s*(\d+(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)?\b",
            r"\b(\d+(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)\b",
        ]

        match = None
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                break
        if not match:
            return None

        amount = float(match.group(1))
        suffix = (match.group(2) or "").lower()
        if suffix == "":
            return int(amount)

        multiplier = 1
        if suffix in {"k", "thousand"}:
            multiplier = 1_000
        elif suffix in {"m", "million"}:
            multiplier = 1_000_000
        elif suffix in {"b", "billion"}:
            multiplier = 1_000_000_000
        return int(amount * multiplier)

    if isinstance(value, str):
        direct = _extract(value)
        if direct is not None:
            return direct
    return _extract(fallback_text or "")


def _infer_company_focus(user_query: str) -> Optional[str]:
    if not user_query:
        return None
    match = re.search(
        r"\bfor\s+([A-Za-z0-9][A-Za-z0-9&\-\s]{1,79}?)(?:\s+focusing|\s+with|\s+across|\s+within|\s+in\b|$)",
        user_query,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip()


def _infer_geography(user_query: str) -> Optional[str]:
    if not user_query:
        return None
    for token in ("CONUS", "OCONUS", "Global"):
        if re.search(rf"\b{token}\b", user_query, re.IGNORECASE):
            return token
    return None


def build_trigger_for_bd_enrichment(
    sector: str,
    user_query: str,
    session_params: Dict[str, Any],
) -> BDTrigger:
    parsed_signals = _parse_signals(session_params.get("signals"))
    if not parsed_signals:
        parsed_signals = _parse_signals_from_text(user_query)

    company_focus = (session_params.get("company") or "").strip() if isinstance(session_params.get("company"), str) else None
    if not company_focus:
        company_focus = _infer_company_focus(user_query)

    geography = (session_params.get("geography") or "").strip() if isinstance(session_params.get("geography"), str) else None
    if not geography:
        geography = _infer_geography(user_query)

    time_window_days = _parse_time_window_days(
        session_params.get("time_window"),
        user_query,
        default=30,
    )
    min_value_usd = _parse_min_value_usd(session_params.get("min_value"), user_query)

    return BDTrigger(
        sector=sector.replace("_", " ").title() if sector else "General",
        signals=parsed_signals,
        company_focus=company_focus or None,
        user_prompt_context=sanitize_user_prompt_context(user_query, max_chars=600),
        geography=geography or None,
        time_window_days=time_window_days,
        min_value_usd=min_value_usd,
    )
