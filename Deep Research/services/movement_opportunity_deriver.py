"""
Deterministic derivation of credential lookup plays from named-move movement context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from models.bd_schemas import Opportunity, SignalEvidence
from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight


@dataclass(frozen=True)
class MovementDerivedOpportunity:
    """Credentials lookup input tied back to a prioritized movement row."""

    person_name: str
    opportunity: Opportunity
    rationale: str
    source_person_names: List[str] = field(default_factory=list)
    source_signal_codes: List[str] = field(default_factory=list)


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
        for row in ranked_rows[:max_opportunities]:
            movement = row["movement"]
            role_scope = str(movement.new_role or "leadership scope").strip()
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
                title=title,
                agency=request.to_company,
                scope=scope,
                incumbent=requirements,
                confidence="High" if row.get("action_posture") == "Immediate Re-engagement" else "Medium",
                citations=[movement.evidence.source_url] if movement.evidence.source_url else [],
            )
            results.append(
                MovementDerivedOpportunity(
                    person_name=movement.person_name,
                    opportunity=opportunity,
                    rationale=str(movement.evidence.evidence_quote or "").strip(),
                    source_person_names=[movement.person_name, request.person_name],
                    source_signal_codes=[item.signal_code for item in signal_evidence[:2]],
                )
            )
        return results

    @staticmethod
    def _build_title(person_name: str, role_scope: str) -> str:
        normalized_scope = role_scope.strip()
        if normalized_scope:
            return f"{person_name} {normalized_scope} Advisory Play"
        return f"{person_name} Advisory Play"
