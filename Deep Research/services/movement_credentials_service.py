"""
Credential proof packet mapping for prioritized movement rows.
"""
from __future__ import annotations

from typing import Any, Dict, List

from models.bd_schemas import CredentialsResponse
from models.movement_schemas import MovementCredentialReference, MovementCredentialsProof


class MovementCredentialsService:
    """Map real credentials lookup results back onto prioritized movement rows."""

    def build_proof_packets(
        self,
        derived_opportunities: List[Any],
        lookup_results: Dict[str, CredentialsResponse],
    ) -> Dict[str, MovementCredentialsProof]:
        packets: Dict[str, MovementCredentialsProof] = {}
        for item in derived_opportunities:
            opportunity = getattr(item, "opportunity", None)
            opportunity_id = str(
                getattr(item, "opportunity_id", "")
                or getattr(opportunity, "opportunity_id", "")
                or ""
            ).strip()
            person_name = str(getattr(item, "person_name", "") or "").strip()
            opportunity_title = str(getattr(opportunity, "title", "") or "").strip()
            if not opportunity_title:
                continue
            lookup_key = opportunity_id or opportunity_title
            response = lookup_results.get(lookup_key) or lookup_results.get(opportunity_title)
            if response is None:
                packets[lookup_key] = MovementCredentialsProof(
                    lookup_status="Lookup Failed",
                    summary="Credentials lookup did not return a result for this derived play.",
                    matched_credentials=[],
                )
                continue
            packets[lookup_key] = self._coerce(response)
        return packets

    def _coerce(self, response: CredentialsResponse) -> MovementCredentialsProof:
        references = [
            MovementCredentialReference(title=match.title, url=match.url)
            for match in list(response.matches or [])[:2]
            if str(match.title or "").strip() and str(match.url or "").strip()
        ]
        summary = ""
        if response.lookup_status == "Matched" and references:
            titles = "; ".join(reference.title for reference in references)
            summary = f"Matched credentials: {titles}."
        elif response.lookup_status == "Lookup Failed":
            summary = str(response.failure_reason or "Credential lookup failed.").strip()
        else:
            summary = "No materially aligned credentials identified."
        return MovementCredentialsProof(
            lookup_status=response.lookup_status,
            summary=summary,
            matched_credentials=references,
        )
