"""
Deterministic derivation of credential lookup plays from named-move movement context.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List

from models.bd_schemas import Opportunity, SignalEvidence
from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight


@dataclass(frozen=True)
class MovementDerivedOpportunity:
    """Credentials lookup input tied back to a prioritized movement row."""

    opportunity_id: str
    person_name: str
    opportunity: Opportunity
    rationale: str
    source_person_names: List[str] = field(default_factory=list)
    source_signal_codes: List[str] = field(default_factory=list)
    source_movement_row_refs: List[str] = field(default_factory=list)
    source_account_refs: List[str] = field(default_factory=list)


class MovementOpportunityDeriver:
    """Turn ranked movement context into up to three consulting plays for credentials lookup."""

    def derive(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        signal_evidence: List[SignalEvidence],
        ranked_rows: List[dict],
        max_opportunities: int = 3,
    ) -> List[MovementDerivedOpportunity]:
        confirmed_signals = [item.signal_label for item in signal_evidence if item.status == "Confirmed"]
        signal_hint = ", ".join(confirmed_signals[:2]) or "Financial Services pressure signals"
        results: List[MovementDerivedOpportunity] = []
        for index, row in enumerate(ranked_rows[:max_opportunities], 1):
            movement = row["movement"]
            role_scope = str(movement.new_role or "leadership scope").strip()
            opportunity_id = self._build_opportunity_id(
                movement.person_name,
                request.from_company,
                request.to_company,
                movement.target_company,
                movement.new_role,
                movement.evidence.source_url,
            )
            title = self._build_title(movement.person_name, role_scope)
            scope = (
                f"Support {movement.person_name}'s transition into {role_scope} at {request.to_company}. "
                f"Use the named move, source/destination account context, and broader account signals to validate a practical advisory play."
            )
            requirements = (
                f"Warm path available: {'yes' if preflight.quick_indicators.warm_intro_path_available else 'no'}. "
                f"Prior destination work: {'yes' if preflight.quick_indicators.destination_worked_before else 'no'}. "
                f"Anchor on {signal_hint}."
            )
            opportunity = Opportunity(
                opportunity_id=opportunity_id,
                title=title,
                agency=request.to_company,
                scope=scope,
                incumbent=requirements,
                confidence="High" if row.get("action_posture") == "Immediate Re-engagement" else "Medium",
                citations=[movement.evidence.source_url] if movement.evidence.source_url else [],
            )
            results.append(
                MovementDerivedOpportunity(
                    opportunity_id=opportunity_id,
                    person_name=movement.person_name,
                    opportunity=opportunity,
                    rationale=str(movement.evidence.evidence_quote or "").strip(),
                    source_person_names=[movement.person_name, request.person_name],
                    source_signal_codes=[item.signal_code for item in signal_evidence[:2]],
                    source_movement_row_refs=self._build_row_refs(movement, row, index),
                    source_account_refs=self._build_account_refs(request.from_company, request.to_company),
                )
            )
        return results

    @staticmethod
    def _build_title(person_name: str, role_scope: str) -> str:
        normalized_scope = role_scope.strip()
        if normalized_scope:
            return f"{person_name} {normalized_scope} Advisory Play"
        return f"{person_name} Advisory Play"

    def _build_opportunity_id(
        self,
        person_name: str,
        from_company: str,
        to_company: str,
        target_company: str,
        new_role: str,
        source_url: str,
    ) -> str:
        seed = "|".join(
            [
                person_name.strip().lower(),
                from_company.strip().lower(),
                to_company.strip().lower(),
                target_company.strip().lower(),
                new_role.strip().lower(),
                source_url.strip().lower(),
            ]
        )
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        return f"mov_{digest}"

    def _build_row_refs(self, movement, row: dict, index: int) -> List[str]:
        refs = [
            f"row:{index}",
            f"person:{movement.person_name}",
            f"company:{movement.target_company}",
        ]
        source_url = str(getattr(movement.evidence, "source_url", "") or "").strip()
        if source_url:
            refs.append(f"url:{source_url}")
        row_id = str(row.get("row_id") or "").strip()
        if row_id:
            refs.append(f"row_id:{row_id}")
        return refs

    def _build_account_refs(self, from_company: str, to_company: str) -> List[str]:
        refs = []
        if from_company.strip():
            refs.append(f"from:{from_company.strip()}")
        if to_company.strip():
            refs.append(f"to:{to_company.strip()}")
        return refs
