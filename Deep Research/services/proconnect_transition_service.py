"""
Runtime ProConnect service for Transition Playbook workflows.

This module intentionally reuses the existing script-oriented ProConnect
stakeholder flow rather than re-implementing lookup logic in Chainlit code.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from models.transition_schemas import (
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)


SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from proconnect_stakeholder_payload import run_stakeholder_case  # noqa: E402


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


class ProConnectTransitionService:
    """Thin runtime wrapper around the existing ProConnect stakeholder flow."""

    def __init__(
        self,
        client: Optional[Any] = None,
        case_runner: Optional[Callable[..., Dict[str, Any]]] = None,
    ) -> None:
        self.client = client
        self.case_runner = case_runner or run_stakeholder_case

    def load_transition_case(
        self,
        request: TransitionRequest,
        *,
        enable_probes: bool = True,
        from_account_id_override: Optional[str] = None,
        to_account_id_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load the existing transition/stakeholder payload from ProConnect."""
        if self.client is None:
            raise ValueError("ProConnectTransitionService requires a client to load live transition cases.")

        research_inputs = {
            "provided_name": request.person_name,
            "provided_role": request.new_role,
            "potential_service_needs": request.additional_context,
            "simulated_research_datapoint": (
                "Synthetic transition scenario." if request.synthetic_scenario else None
            ),
        }

        return self.case_runner(
            client=self.client,
            person=request.person_name,
            from_company=request.from_company,
            to_company=request.to_company,
            department_hint=request.department_hint,
            from_account_id_override=from_account_id_override,
            to_account_id_override=to_account_id_override,
            research_inputs=research_inputs,
            enable_probes=enable_probes,
        )

    def build_preflight(
        self,
        request: TransitionRequest,
        *,
        transition_case: Optional[Dict[str, Any]] = None,
        enable_probes: bool = True,
        from_account_id_override: Optional[str] = None,
        to_account_id_override: Optional[str] = None,
    ) -> TransitionPreflight:
        """Convert a transition case into the compact review surface contract."""
        case = transition_case or self.load_transition_case(
            request,
            enable_probes=enable_probes,
            from_account_id_override=from_account_id_override,
            to_account_id_override=to_account_id_override,
        )
        payload = _as_dict(case.get("transition_payload"))

        return TransitionPreflight(
            request=request,
            person_resolution=self._build_person_resolution(request, payload),
            from_account=self._build_account_resolution(request, payload, scope="from"),
            to_account=self._build_account_resolution(request, payload, scope="to"),
            quick_indicators=self._build_quick_indicators(payload),
            opportunity_hypotheses=self._build_opportunity_hypotheses(payload),
            inferred_industry=self._infer_industry(payload, request),
            suggested_research_prompt="",
        )

    def build_actioning_context(
        self,
        request: TransitionRequest,
        *,
        transition_case: Optional[Dict[str, Any]] = None,
        enable_probes: bool = True,
        from_account_id_override: Optional[str] = None,
        to_account_id_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Expose richer context for post-research outreach/action recommendations."""
        case = transition_case or self.load_transition_case(
            request,
            enable_probes=enable_probes,
            from_account_id_override=from_account_id_override,
            to_account_id_override=to_account_id_override,
        )
        payload = _as_dict(case.get("transition_payload"))
        movement_evidence = _as_dict(payload.get("movement_evidence"))
        return {
            "person_profile": _as_dict(payload.get("person_profile")),
            "from_company_context": _as_dict(payload.get("from_company_context")),
            "to_company_context": _as_dict(payload.get("to_company_context")),
            "ranked_opportunities_top10": _as_list(movement_evidence.get("ranked_opportunities_top10")),
            "warnings": _as_list(case.get("warnings")),
        }

    def _build_person_resolution(
        self,
        request: TransitionRequest,
        payload: Dict[str, Any],
    ) -> TransitionPersonResolution:
        profile = _as_dict(payload.get("person_profile"))
        matched = _as_dict(profile.get("matched_person"))
        return TransitionPersonResolution(
            requested_name=str(profile.get("person_requested") or request.person_name),
            match_status=str(profile.get("match_status") or "not_requested"),
            matched_name=matched.get("name") or profile.get("person_requested"),
            matched_title=matched.get("title") or profile.get("title_salesforce") or profile.get("title_external"),
            match_source=matched.get("source"),
            direct_person_evidence=bool(profile.get("direct_person_evidence")),
        )

    def _build_account_resolution(
        self,
        request: TransitionRequest,
        payload: Dict[str, Any],
        *,
        scope: str,
    ) -> AccountResolution:
        movement_event = _as_dict(payload.get("movement_event"))
        if scope == "from":
            company_name = (
                _as_dict(payload.get("from_company_context")).get("account_header", {}).get("company_name")
                or movement_event.get("from_company")
                or request.from_company
            )
            resolved = bool(movement_event.get("from_account_resolved"))
            account_id = movement_event.get("from_account_id")
        else:
            to_context = _as_dict(payload.get("to_company_context"))
            company_name = (
                _as_dict(to_context.get("account_context")).get("company_name")
                or movement_event.get("to_company")
                or request.to_company
            )
            resolved = bool(movement_event.get("to_account_resolved"))
            account_id = movement_event.get("to_account_id")

        return AccountResolution(
            company_name=str(company_name or ""),
            resolved=resolved,
            account_id=str(account_id) if account_id else None,
        )

    def _build_quick_indicators(self, payload: Dict[str, Any]) -> QuickRelationshipIndicators:
        from_context = _as_dict(payload.get("from_company_context"))
        to_context = _as_dict(payload.get("to_company_context"))
        from_priors = _as_dict(from_context.get("prior_relationship_indicators"))
        from_relationship = _as_dict(from_context.get("relationship_network"))
        to_relationship = _as_dict(to_context.get("relationship_network"))
        to_account_context = _as_dict(to_context.get("account_context"))
        to_key_buyers = _as_dict(to_context.get("key_buyers"))

        source_connected = _as_list(_as_dict(from_relationship.get("connected_colleagues")).get("items"))
        destination_connected = _as_list(_as_dict(to_relationship.get("connected_colleagues")).get("items"))

        source_key_buyer_count = int(from_priors.get("key_buyer_count") or len(_as_list(from_context.get("top_key_buyers"))))
        destination_key_buyer_count = len(_as_list(to_key_buyers.get("items")))

        return QuickRelationshipIndicators(
            warm_intro_path_available=bool(
                from_priors.get("warm_intro_path_available")
                or to_relationship.get("warm_intro_path_available")
            ),
            source_worked_before=bool(from_context.get("worked_before")),
            destination_worked_before=bool(
                to_account_context.get("worked_before") or to_context.get("worked_before")
            ),
            source_key_buyer_count=source_key_buyer_count,
            destination_key_buyer_count=destination_key_buyer_count,
            source_connected_colleague_count=len(source_connected),
            destination_connected_colleague_count=len(destination_connected),
        )

    def _build_opportunity_hypotheses(self, payload: Dict[str, Any]) -> List[OpportunityHypothesis]:
        movement_evidence = _as_dict(payload.get("movement_evidence"))
        ranked = _as_list(movement_evidence.get("ranked_opportunities_top10"))
        hypotheses: List[OpportunityHypothesis] = []

        for item in ranked[:3]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("opportunity") or "").strip()
            if not title:
                continue
            stage = str(item.get("stage") or "Active destination signal").strip()
            primary_key_buyer = str(item.get("primary_key_buyer") or "").strip()
            rationale = f"Destination account signal currently sits at stage: {stage}."
            if primary_key_buyer:
                rationale += f" Primary buyer context: {primary_key_buyer}."
            hypotheses.append(
                OpportunityHypothesis(
                    title=title,
                    rationale=rationale,
                    confidence=self._normalize_confidence(item.get("rank_band")),
                )
            )

        return hypotheses

    def _infer_industry(self, payload: Dict[str, Any], request: TransitionRequest) -> str:
        if request.industry_override:
            return request.industry_override

        to_context = _as_dict(payload.get("to_company_context"))
        account_context = _as_dict(to_context.get("account_context"))
        from_context = _as_dict(payload.get("from_company_context"))
        from_header = _as_dict(from_context.get("account_header"))

        industry_candidates = [
            account_context.get("industry"),
            from_header.get("industry"),
        ]

        for candidate in industry_candidates:
            normalized = self._normalize_industry(candidate)
            if normalized != "general":
                return normalized
        return "general"

    @staticmethod
    def _normalize_confidence(rank_band: Any) -> str:
        normalized = str(rank_band or "Medium").strip().title()
        if normalized not in {"High", "Medium", "Low"}:
            return "Medium"
        return normalized

    @staticmethod
    def _normalize_industry(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "general"
        if "financial" in text or "bank" in text or "mortgage" in text:
            return "financial_services"
        if "defense" in text:
            return "defense"
        if "health" in text or "medical" in text:
            return "healthcare"
        return "general"
