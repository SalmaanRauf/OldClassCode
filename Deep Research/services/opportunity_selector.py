"""
Deterministic opportunity selection for credentials lookup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from models.bd_schemas import BDTrigger, Opportunity, OpportunitySelectionDiagnostics


_LOW_SIGNAL_URL_HINTS = (
    "/search",
    "/login",
    "/signin",
    "/home",
    "return to workspace",
)
_CONUS_MISMATCH_HINTS = (
    "oconus",
    "outside continental united states",
    "global",
    "worldwide",
    "japan",
    "korea",
    "germany",
    "united kingdom",
    "uk ",
    "europe",
    "australia",
    "canada",
    "middle east",
    "africa",
)
_DATE_PATTERNS_WITH_DAY = (
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(
        r"(?i)\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2}),\s*(20\d{2})\b"
    ),
)
_DATE_PATTERN_MONTH_YEAR = re.compile(
    r"(?i)\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
    r")\s+(20\d{2})\b"
)
_MONEY_WITH_SUFFIX_PATTERN = re.compile(
    r"(?i)\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(k|m|b|thousand|million|billion)\b"
)
_MONEY_NUMBER_PATTERN = re.compile(r"(?i)\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)")


@dataclass
class _Candidate:
    opportunity: Opportunity
    extracted_date: Optional[date]
    has_exact_date: bool
    cmmc_relevant: bool
    min_value_compliant: bool
    confidence_score: int
    source_quality_score: int


def select_top_opportunities(
    opportunities: List[Opportunity],
    trigger: BDTrigger,
    reference_date: date | datetime,
    top_n: int = 3
) -> Tuple[List[Opportunity], OpportunitySelectionDiagnostics]:
    """Select top opportunities using strict constraints + deterministic ranking."""
    today = reference_date.date() if isinstance(reference_date, datetime) else reference_date
    cutoff = today - timedelta(days=max(1, min(365, trigger.time_window_days)))
    cmmc_required = any("cmmc" in signal.lower() for signal in trigger.signals)

    rejection_counts: Dict[str, int] = {
        "geography_mismatch": 0,
        "below_min_value": 0,
        "out_of_window": 0,
    }
    candidates: List[_Candidate] = []

    for opportunity in opportunities:
        combined_text = _combined_text(opportunity)
        if _is_geography_mismatch(trigger.geography, combined_text):
            rejection_counts["geography_mismatch"] += 1
            continue

        value_usd = _parse_value_usd(opportunity.estimated_value)
        if trigger.min_value_usd is not None and value_usd is not None and value_usd < trigger.min_value_usd:
            rejection_counts["below_min_value"] += 1
            continue

        extracted_date, has_exact_date = _extract_date(opportunity.timeline or "")
        if has_exact_date and extracted_date and extracted_date < cutoff:
            rejection_counts["out_of_window"] += 1
            continue

        candidates.append(
            _Candidate(
                opportunity=opportunity,
                extracted_date=extracted_date,
                has_exact_date=has_exact_date,
                cmmc_relevant=_is_cmmc_relevant(opportunity),
                min_value_compliant=(
                    True
                    if trigger.min_value_usd is None
                    else (value_usd is not None and value_usd >= trigger.min_value_usd)
                ),
                confidence_score=_confidence_score(opportunity.confidence),
                source_quality_score=_source_quality_score(opportunity.citations),
            )
        )

    in_window_exact = [
        candidate for candidate in candidates
        if candidate.has_exact_date and candidate.extracted_date and candidate.extracted_date >= cutoff
    ]
    other_candidates = [
        candidate for candidate in candidates
        if candidate not in in_window_exact
    ]

    ranked_exact = _rank_candidates(in_window_exact, cmmc_required)
    ranked_other = _rank_candidates(other_candidates, cmmc_required)

    selected: List[Opportunity] = [candidate.opportunity for candidate in ranked_exact[:top_n]]
    fallback_used = False
    if len(selected) < top_n and ranked_other:
        fallback_used = True
        needed = top_n - len(selected)
        selected.extend(candidate.opportunity for candidate in ranked_other[:needed])

    diagnostics = OpportunitySelectionDiagnostics(
        invoked=True,
        opportunities_input_count=len(opportunities),
        opportunities_after_hard_filters=len(candidates),
        opportunities_selected_count=len(selected),
        selection_policy="strict_with_unknown_date_fallback",
        cmmc_required=cmmc_required,
        time_window_days=trigger.time_window_days,
        min_value_usd=trigger.min_value_usd,
        geography=trigger.geography,
        rejection_counts=rejection_counts,
        fallback_used=fallback_used,
        selected_titles=[opportunity.title for opportunity in selected],
    )
    return selected, diagnostics


def _rank_candidates(candidates: List[_Candidate], cmmc_required: bool) -> List[_Candidate]:
    def sort_key(candidate: _Candidate) -> Tuple[int, int, int, int, int, str]:
        cmmc_score = 1 if candidate.cmmc_relevant else 0
        if cmmc_required and not candidate.cmmc_relevant:
            cmmc_score = -1
        date_score = candidate.extracted_date.toordinal() if candidate.extracted_date else 0
        return (
            cmmc_score,
            1 if candidate.min_value_compliant else 0,
            candidate.confidence_score,
            candidate.source_quality_score,
            date_score,
            candidate.opportunity.title.lower(),
        )

    return sorted(candidates, key=sort_key, reverse=True)


def _combined_text(opportunity: Opportunity) -> str:
    return " ".join(
        part for part in [
            opportunity.title,
            opportunity.scope,
            opportunity.timeline or "",
            opportunity.agency or "",
        ] if part
    ).lower()


def _is_geography_mismatch(geography: Optional[str], text: str) -> bool:
    if not geography:
        return False
    target = geography.lower()
    if target == "conus":
        return any(hint in text for hint in _CONUS_MISMATCH_HINTS)
    if target == "oconus":
        return "conus" in text and "oconus" not in text
    return False


def _parse_value_usd(value_text: Optional[str]) -> Optional[int]:
    if not value_text:
        return None
    text = value_text.strip()
    suffix_match = _MONEY_WITH_SUFFIX_PATTERN.search(text)
    if suffix_match:
        amount = _parse_number(suffix_match.group(1))
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

    number_match = _MONEY_NUMBER_PATTERN.search(text)
    if number_match:
        return int(_parse_number(number_match.group(1)))
    return None


def _parse_number(raw: str) -> float:
    try:
        return float(raw.replace(",", "").strip())
    except ValueError:
        return 0.0


def _extract_date(text: str) -> Tuple[Optional[date], bool]:
    if not text:
        return None, False

    for pattern in _DATE_PATTERNS_WITH_DAY:
        match = pattern.search(text)
        if not match:
            continue
        try:
            if len(match.groups()) == 3 and "-" in match.group(0):
                year, month, day = [int(part) for part in match.groups()]
                return date(year, month, day), True
            month_name, day_text, year_text = match.groups()
            dt = datetime.strptime(f"{month_name} {day_text} {year_text}", "%B %d %Y")
            return dt.date(), True
        except ValueError:
            try:
                dt = datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%b %d %Y")
                return dt.date(), True
            except ValueError:
                continue

    month_year = _DATE_PATTERN_MONTH_YEAR.search(text)
    if month_year:
        month_name, year_text = month_year.groups()
        try:
            dt = datetime.strptime(f"{month_name} 1 {year_text}", "%B %d %Y")
            return dt.date(), False
        except ValueError:
            try:
                dt = datetime.strptime(f"{month_name} 1 {year_text}", "%b %d %Y")
                return dt.date(), False
            except ValueError:
                return None, False

    return None, False


def _is_cmmc_relevant(opportunity: Opportunity) -> bool:
    if opportunity.cmmc_level:
        return True
    text = " ".join(
        part for part in [opportunity.title, opportunity.scope, opportunity.timeline or ""]
        if part
    ).lower()
    return "cmmc" in text or "nist 800-171" in text


def _confidence_score(confidence: str) -> int:
    lookup = {"high": 3, "medium": 2, "low": 1}
    return lookup.get((confidence or "").lower(), 1)


def _source_quality_score(citations: List[str]) -> int:
    if not citations:
        return 0
    score = 0
    for citation in citations:
        lowered = citation.lower()
        if any(hint in lowered for hint in _LOW_SIGNAL_URL_HINTS):
            score -= 1
        else:
            score += 1
    return score

