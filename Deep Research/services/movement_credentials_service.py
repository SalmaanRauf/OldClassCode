"""
Credential proof packets for prioritized movement rows.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from models.movement_schemas import MovementCredentialsProof, MovementCredentialReference


LookupCallable = Callable[[Any], Dict[str, Any]]


class MovementCredentialsService:
    """Build proof packets for prioritized movement rows."""

    def __init__(self, lookup: LookupCallable):
        self.lookup = lookup

    def build_proof_packets(self, ranked_rows: List[Dict[str, Any]]) -> Dict[str, MovementCredentialsProof]:
        packets: Dict[str, MovementCredentialsProof] = {}
        for row in ranked_rows:
            movement = row["movement"]
            key = movement.person_name
            try:
                raw = self.lookup(movement)
                packets[key] = self._coerce(raw)
            except Exception as exc:
                packets[key] = MovementCredentialsProof(
                    lookup_status="Lookup Failed",
                    summary=str(exc),
                    matched_credentials=[],
                )
        return packets

    def _coerce(self, payload: Dict[str, Any]) -> MovementCredentialsProof:
        references = []
        for item in payload.get("matched_credentials") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if not title or not url:
                continue
            references.append(MovementCredentialReference(title=title, url=url))

        status = str(payload.get("lookup_status") or "No Match").strip()
        if status not in {"Matched", "No Match", "Lookup Failed"}:
            status = "No Match"
        return MovementCredentialsProof(
            lookup_status=status,
            summary=str(payload.get("summary") or "").strip(),
            matched_credentials=references,
        )
