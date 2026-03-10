"""
Deterministic source guardrails for evidence-locked synthesis.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, List, Set
from urllib.parse import urlparse

from models.bd_schemas import SignalEvidence


class SourceGuardrails:
    """Applies domain-tier trust scoring and domain-cap controls."""

    REGULATORY_HOSTS = {
        "fdic.gov",
        "federalreserve.gov",
        "consumerfinance.gov",
        "occ.treas.gov",
        "sec.gov",
        "fincen.gov",
        "treasury.gov",
        "justice.gov",
        "ag.ny.gov",
        "oag.maryland.gov",
        "ag.state.mn.us",
        "oag.ca.gov",
    }
    TIER1_MEDIA_HOSTS = {
        "reuters.com",
        "bloomberg.com",
        "bloomberglaw.com",
        "apnews.com",
        "wsj.com",
        "ft.com",
        "fintechmagazine.com",
    }

    def __init__(
        self,
        domain_cap: int = 3,
        confirmed_min_tier: int | None = None,
        source_policy_mode: str | None = None,
    ):
        # `source_policy_mode` is accepted for compatibility, but source policy currently
        # influences discovery behavior instead of hard confirmation gating.
        if confirmed_min_tier is None:
            # Keep confirmation gating stable; source policy mode influences search/discovery
            # strategy rather than hard confirmation eligibility thresholds.
            confirmed_min_tier = 1
        self.domain_cap = max(1, domain_cap)
        self.confirmed_min_tier = confirmed_min_tier

    def _host(self, url: str) -> str:
        try:
            host = urlparse(url).netloc.lower().strip()
        except Exception:
            host = ""
        return host.removeprefix("www.")

    def score_url(self, url: str) -> int:
        host = self._host(url)
        if not host:
            return 0
        if host.endswith(".gov") or host.endswith(".mil") or host in self.REGULATORY_HOSTS:
            return 3
        if host in self.TIER1_MEDIA_HOSTS:
            return 2
        return 1

    def is_confirmed_eligible(self, url: str) -> bool:
        return self.score_url(url) >= self.confirmed_min_tier

    def apply_domain_cap(self, urls: Iterable[str]) -> List[str]:
        capped: List[str] = []
        domain_counts = defaultdict(int)
        seen = set()
        for raw in urls:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            host = self._host(url)
            if host and domain_counts[host] >= self.domain_cap:
                continue
            if host:
                domain_counts[host] += 1
            capped.append(url)
        return capped

    def enforce_on_signal_evidence(
        self,
        signal_evidence: Iterable[SignalEvidence],
        available_sources: Set[str],
    ) -> List[SignalEvidence]:
        normalized_sources = {str(url).strip() for url in available_sources if str(url).strip()}
        enforced: List[SignalEvidence] = []

        for evidence in signal_evidence:
            normalized_url = (evidence.source_url or "").strip()
            status = evidence.status
            analysis = (evidence.analysis or "").strip()

            if normalized_url and normalized_url not in normalized_sources:
                status = "Rejected"
                analysis = (
                    f"{analysis} Source URL not present in provided source set."
                    if analysis else "Source URL not present in provided source set."
                )
            elif status == "Confirmed":
                if not self.is_confirmed_eligible(normalized_url):
                    status = "Insufficient"
                    analysis = (
                        f"{analysis} Source tier below confirmed threshold."
                        if analysis else "Source tier below confirmed threshold."
                    )

            enforced.append(
                SignalEvidence(
                    signal_code=evidence.signal_code,
                    signal_label=evidence.signal_label,
                    status=status,  # type: ignore[arg-type]
                    evidence_quote=evidence.evidence_quote,
                    source_url=normalized_url,
                    source_title=evidence.source_title,
                    analysis=analysis,
                )
            )

        return enforced
