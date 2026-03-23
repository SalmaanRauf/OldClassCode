"""
Shared credentials lookup runner extracted from the BD orchestrator.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

from models.bd_schemas import (
    CredentialsBatchDiagnostics,
    CredentialsLookupDiagnostics,
    CredentialsResponse,
    Opportunity,
)

if TYPE_CHECKING:
    from agents.credentials_agent import CredentialsAgent

logger = logging.getLogger(__name__)


def _create_default_credentials_agent() -> "CredentialsAgent":
    """Import lazily to avoid startup-order issues during app bootstrap."""
    from agents.credentials_agent import CredentialsAgent

    return CredentialsAgent.from_env()


@dataclass(frozen=True)
class CredentialsLookupRunResult:
    """Bundle of results and diagnostics from a credentials lookup run."""

    results: Dict[str, CredentialsResponse]
    diagnostics: Dict[str, CredentialsLookupDiagnostics]
    batch_diagnostics: Optional[CredentialsBatchDiagnostics]
    status_counts: Dict[str, int]
    lookups_executed_count: int


class CredentialsLookupRunner:
    """Run credentials validation for the top opportunities in either mode."""

    def __init__(
        self,
        *,
        credentials_agent: Optional["CredentialsAgent"] = None,
        lookup_mode: str = "serial_per_opportunity",
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        allowed_lookup_modes = {"serial_per_opportunity", "batched_single_call"}
        if lookup_mode not in allowed_lookup_modes:
            logger.warning(
                "Unknown credentials lookup_mode '%s'; defaulting to serial_per_opportunity.",
                lookup_mode,
            )
            lookup_mode = "serial_per_opportunity"
        self.credentials_agent = credentials_agent
        self.lookup_mode = lookup_mode
        self._retry_backoff_seconds = retry_backoff_seconds

    async def run(
        self,
        opportunities: List[Opportunity],
        *,
        sector: str,
        max_opportunities: int = 3,
    ) -> CredentialsLookupRunResult:
        requested = list(opportunities[:max_opportunities])
        if not requested:
            return CredentialsLookupRunResult(
                results={},
                diagnostics={},
                batch_diagnostics=None,
                status_counts={"Matched": 0, "No Match": 0, "Lookup Failed": 0},
                lookups_executed_count=0,
            )

        await self._ensure_credentials_agent()
        assert self.credentials_agent is not None

        if self.lookup_mode == "batched_single_call":
            results, batch_diagnostics = await self.credentials_agent.find_credentials_batch(
                requested,
                sector,
                max_matches_per_opportunity=3,
            )
            diagnostics = self._collect_credentials_diagnostics(requested, sector, results)
            status_counts = self._count_lookup_statuses(results)
            return CredentialsLookupRunResult(
                results=results,
                diagnostics=diagnostics,
                batch_diagnostics=batch_diagnostics,
                status_counts=status_counts,
                lookups_executed_count=len(requested),
            )

        results: Dict[str, CredentialsResponse] = {}
        for opportunity in requested:
            results[opportunity.title] = await self._lookup_single_with_retry(opportunity, sector)

        diagnostics = self._collect_credentials_diagnostics(requested, sector, results)
        status_counts = self._count_lookup_statuses(results)
        return CredentialsLookupRunResult(
            results=results,
            diagnostics=diagnostics,
            batch_diagnostics=None,
            status_counts=status_counts,
            lookups_executed_count=len(requested),
        )

    async def _ensure_credentials_agent(self) -> None:
        if self.credentials_agent is None:
            self.credentials_agent = _create_default_credentials_agent()

    async def _lookup_single_with_retry(
        self,
        opportunity: Opportunity,
        sector: str,
    ) -> CredentialsResponse:
        response = await self.credentials_agent.find_credentials(opportunity, sector=sector)
        if self._is_timeout_lookup_failure(response):
            logger.warning(
                "Retrying serial credentials lookup after retryable transport failure for '%s'.",
                opportunity.title,
            )
            await asyncio.sleep(self._retry_backoff_seconds)
            response = await self.credentials_agent.find_credentials(opportunity, sector=sector)
        return response

    def _is_timeout_lookup_failure(self, response: Optional[CredentialsResponse]) -> bool:
        if not response or response.lookup_status != "Lookup Failed":
            return False
        message_parts: List[str] = []
        if response.failure_reason:
            message_parts.append(response.failure_reason)
        if response.diagnostics and response.diagnostics.error_message:
            message_parts.append(response.diagnostics.error_message)
        combined = " ".join(message_parts).lower()
        retryable_markers = (
            "timed out",
            "timeout",
            "getaddrinfo failed",
            "temporary failure in name resolution",
            "name or service not known",
            "network is unreachable",
            "connection reset",
            "connection aborted",
            "connection refused",
            "bad gateway",
            "gateway timeout",
            "internal server error",
            "internalservererror",
            "http error 500",
            "status code 500",
            "request failed with status code internalservererror",
            "unable to create chat session",
            "failed to create chat session",
        )
        return any(marker in combined for marker in retryable_markers)

    def _count_lookup_statuses(self, results: Dict[str, CredentialsResponse]) -> Dict[str, int]:
        counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
        for response in results.values():
            status = response.lookup_status
            if status not in counts:
                status = "Lookup Failed"
            counts[status] += 1
        return counts

    def _collect_credentials_diagnostics(
        self,
        opportunities: List[Opportunity],
        sector: str,
        results: Dict[str, CredentialsResponse],
    ) -> Dict[str, CredentialsLookupDiagnostics]:
        diagnostics: Dict[str, CredentialsLookupDiagnostics] = {}
        for opportunity in opportunities:
            response = results.get(opportunity.title)
            if response and response.diagnostics:
                diagnostics[opportunity.title] = response.diagnostics
                continue
            lookup_status = response.lookup_status if response else "Lookup Failed"
            diagnostics[opportunity.title] = CredentialsLookupDiagnostics(
                opportunity_title=opportunity.title,
                sector=sector,
                query_text="",
                raw_response_text="",
                parse_outcome="diagnostics_missing",
                lookup_status=lookup_status,
                error_message=response.failure_reason if response else "Missing credentials response.",
                duration_ms=0.0,
                match_count=len(response.matches) if response else 0,
            )
        return diagnostics
