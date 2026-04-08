"""
Deterministic derivation of credential lookup plays from named-move movement context.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from models.bd_schemas import Opportunity, SignalEvidence
from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight
from services.movement_credential_context import (
    MovementCredentialCandidate,
    MovementCredentialCandidateSelector,
    MovementCredentialContextBuilder,
)


@dataclass(frozen=True)
class MovementDerivedOpportunity:
    """Credentials lookup input tied back to a prioritized movement row."""

    opportunity_id: str
    person_name: str
    opportunity: Opportunity
    rationale: str
    source_type: str = "ranked_row"
    source_person_names: List[str] = field(default_factory=list)
    source_signal_codes: List[str] = field(default_factory=list)
    source_movement_row_refs: List[str] = field(default_factory=list)
    source_account_refs: List[str] = field(default_factory=list)


class MovementOpportunityDeriver:
    """Turn ranked movement context into up to three consulting plays for credentials lookup."""

    def __init__(
        self,
        *,
        candidate_selector: Optional[MovementCredentialCandidateSelector] = None,
        context_builder: Optional[MovementCredentialContextBuilder] = None,
    ) -> None:
        self.candidate_selector = candidate_selector or MovementCredentialCandidateSelector()
        self.context_builder = context_builder or MovementCredentialContextBuilder()

    def derive(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        signal_evidence: List[SignalEvidence],
        ranked_rows: List[dict],
        actioning_context: Optional[Dict[str, Any]] = None,
        max_opportunities: int = 3,
    ) -> List[MovementDerivedOpportunity]:
        selected_candidates = self.candidate_selector.select(
            request=request,
            preflight=preflight,
            ranked_rows=ranked_rows,
            actioning_context=actioning_context,
            max_candidates=max_opportunities,
        )
        results: List[MovementDerivedOpportunity] = []
        for index, candidate in enumerate(selected_candidates, 1):
            opportunity_id = self._build_opportunity_id(
                candidate.person_name,
                request.from_company,
                request.to_company,
                candidate.target_company,
                candidate.new_role,
                candidate.source_url,
            )
            title = self._build_title(candidate.person_name, candidate.new_role)
            scope = self._build_scope(
                person_name=candidate.person_name,
                role_scope=candidate.new_role,
                target_company=candidate.target_company,
                selection_reason=candidate.selection_reason,
            )
            credential_search_context = self.context_builder.build(
                candidate=candidate,
                request=request,
                preflight=preflight,
                signal_evidence=signal_evidence,
                actioning_context=actioning_context,
            )
            opportunity = Opportunity(
                opportunity_id=opportunity_id,
                title=title,
                agency=candidate.target_company,
                scope=scope,
                incumbent=None,
                confidence=self._confidence_for_candidate(candidate),
                citations=[candidate.source_url] if candidate.source_url and not candidate.source_url.startswith("internal://") else [],
                credential_search_context=credential_search_context,
            )
            results.append(
                MovementDerivedOpportunity(
                    opportunity_id=opportunity_id,
                    person_name=candidate.person_name,
                    opportunity=opportunity,
                    rationale=candidate.evidence_quote,
                    source_type=candidate.source_type,
                    source_person_names=self._build_source_person_names(candidate, request),
                    source_signal_codes=[item.signal_code for item in signal_evidence[:2]],
                    source_movement_row_refs=self._build_row_refs(candidate, index),
                    source_account_refs=self._build_account_refs(request.from_company, candidate.target_company),
                )
            )
        return results

    @staticmethod
    def _build_title(person_name: str, role_scope: str) -> str:
        normalized_scope = role_scope.strip()
        if normalized_scope:
            return f"{person_name} {normalized_scope} Advisory Play"
        return f"{person_name} Advisory Play"

    @staticmethod
    def _build_scope(
        *,
        person_name: str,
        role_scope: str,
        target_company: str,
        selection_reason: str,
    ) -> str:
        return (
            f"Identify the most relevant Protiviti credentials for engaging {person_name} as a leader who has "
            f"recently stepped into the {role_scope} role at {target_company}. Prioritize industry-aligned work "
            f"that helps newly promoted or hired leaders handle expanded responsibilities, first-year transition "
            f"challenges, and near-term buying needs in complex operating environments. Selection context: "
            f"{selection_reason}"
        )

    @staticmethod
    def _confidence_for_candidate(candidate: MovementCredentialCandidate) -> str:
        ranked_row = candidate.ranked_row or {}
        if candidate.source_type == "named_mover":
            return "High"
        if str(ranked_row.get("action_posture") or "").strip() == "Immediate Re-engagement":
            return "High"
        if str(ranked_row.get("person_match_status") or "").strip().lower() == "matched":
            return "High"
        return "Medium"

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

    def _build_row_refs(self, candidate: MovementCredentialCandidate, index: int) -> List[str]:
        refs = [
            f"row:{index}",
            f"person:{candidate.person_name}",
            f"company:{candidate.target_company}",
            f"source_type:{candidate.source_type}",
        ]
        source_url = str(candidate.source_url or "").strip()
        if source_url:
            refs.append(f"url:{source_url}")
        ranked_row = candidate.ranked_row or {}
        row_id = str(ranked_row.get("row_id") or "").strip()
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

    def _build_source_person_names(
        self,
        candidate: MovementCredentialCandidate,
        request: MovementBriefRequest,
    ) -> List[str]:
        values = [candidate.person_name, request.person_name]
        seen: set[str] = set()
        results: List[str] = []
        for value in values:
            normalized = value.strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            results.append(normalized)
        return results
