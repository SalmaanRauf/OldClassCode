"""
Runtime ProConnect service for Transition Playbook workflows.

This module intentionally reuses the existing script-oriented ProConnect
stakeholder flow rather than re-implementing lookup logic in Chainlit code.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from models.transition_schemas import (
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from scripts.proconnect_stakeholder_payload import run_stakeholder_case


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
        warnings = [str(item).strip() for item in _as_list(case.get("warnings")) if str(item or "").strip()]
        person_resolution = self._build_person_resolution(request, payload, warnings=warnings)
        from_account = self._build_account_resolution(request, payload, scope="from")
        to_account = self._build_account_resolution(request, payload, scope="to")

        return TransitionPreflight(
            request=request,
            person_resolution=person_resolution,
            from_account=from_account,
            to_account=to_account,
            quick_indicators=self._build_quick_indicators(payload),
            opportunity_hypotheses=self._build_opportunity_hypotheses(payload),
            inferred_industry=self._infer_industry(payload, request),
            suggested_research_prompt="",
            review_diagnostics=self._build_review_diagnostics(
                request=request,
                person_resolution=person_resolution,
                from_account=from_account,
                to_account=to_account,
                warnings=warnings,
            ),
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
        *,
        warnings: Optional[List[str]] = None,
    ) -> TransitionPersonResolution:
        profile = _as_dict(payload.get("person_profile"))
        raw_resolution = _as_dict(payload.get("person_resolution"))
        matched = _as_dict(profile.get("matched_person"))
        suggestions_raw = _as_list(profile.get("candidate_suggestions"))
        top_candidate = suggestions_raw[0] if suggestions_raw and isinstance(suggestions_raw[0], dict) else {}
        raw_status = str(profile.get("match_status") or raw_resolution.get("status") or "not_requested").strip().lower()
        normalized_status = raw_status if raw_status in {"matched", "candidate", "not_found", "not_requested"} else "not_found"
        if normalized_status in {"ambiguous", "not_found"} and top_candidate:
            normalized_status = "candidate"
        return TransitionPersonResolution(
            requested_name=str(profile.get("person_requested") or request.person_name),
            match_status=normalized_status,
            matched_name=matched.get("name") or top_candidate.get("name") or profile.get("person_requested"),
            matched_title=(
                matched.get("title")
                or top_candidate.get("title")
                or profile.get("title_salesforce")
                or profile.get("title_external")
            ),
            match_source=matched.get("source") or top_candidate.get("source") or raw_resolution.get("match_source"),
            match_scope=matched.get("company_scope") or top_candidate.get("company_scope") or raw_resolution.get("match_scope"),
            linked_account_id=matched.get("linked_account_id") or top_candidate.get("linked_account_id"),
            direct_person_evidence=bool(profile.get("direct_person_evidence")),
            match_diagnostics=self._build_person_match_diagnostics(
                request=request,
                profile=profile,
                raw_resolution=raw_resolution,
                warnings=warnings or [],
            ),
            candidate_suggestions=self._format_candidate_suggestions(suggestions_raw),
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

    def _build_review_diagnostics(
        self,
        *,
        request: TransitionRequest,
        person_resolution: TransitionPersonResolution,
        from_account: AccountResolution,
        to_account: AccountResolution,
        warnings: List[str],
    ) -> List[str]:
        diagnostics: List[str] = list(person_resolution.match_diagnostics)
        if not from_account.resolved:
            diagnostics.append(
                f"Source account lookup did not resolve cleanly for {request.from_company}; using raw company text."
            )
        if not to_account.resolved:
            diagnostics.append(
                f"Destination account lookup did not resolve cleanly for {request.to_company}; using raw company text."
            )
        diagnostics.extend(warnings[:4])
        return self._dedupe_lines(diagnostics)

    def _build_person_match_diagnostics(
        self,
        *,
        request: TransitionRequest,
        profile: Dict[str, Any],
        raw_resolution: Dict[str, Any],
        warnings: List[str],
    ) -> List[str]:
        diagnostics: List[str] = []
        status = str(profile.get("match_status") or raw_resolution.get("status") or "not_found").strip().lower()
        matched = _as_dict(profile.get("matched_person"))
        top_candidate = _as_list(profile.get("candidate_suggestions"))
        match_strategy = str(raw_resolution.get("match_strategy") or "").strip()
        if status == "matched":
            scope = matched.get("company_scope") or raw_resolution.get("match_scope") or "unknown"
            source = matched.get("source") or raw_resolution.get("match_source") or "unknown source"
            strategy_note = f" using {match_strategy.replace('_', ' ')}" if match_strategy else ""
            diagnostics.append(
                f"Matched {request.person_name} on the {scope} account via {source}{strategy_note}."
            )
        elif top_candidate:
            best = top_candidate[0] if isinstance(top_candidate[0], dict) else {}
            score = best.get("score")
            score_text = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
            source = str(best.get("source") or "candidate pool").replace("_", " ")
            diagnostics.append(
                f"No exact account-scoped match. Closest candidate is {best.get('name') or request.person_name} via {source}{score_text}."
            )
        else:
            diagnostics.append(
                f"No exact person match was found for {request.person_name} in the scoped ProConnect account pools."
            )

        if not profile.get("direct_person_evidence"):
            diagnostics.append("Direct person-level evidence is unavailable; treat the named mover as planning context only.")

        if warnings:
            diagnostics.extend(warnings[:2])
        return self._dedupe_lines(diagnostics)

    def _format_candidate_suggestions(self, candidates: List[Any]) -> List[str]:
        formatted: List[str] = []
        for item in candidates[:3]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            title = str(item.get("title") or "").strip()
            source = str(item.get("source") or "").strip().replace("_", " ")
            score = item.get("score")
            suffix_bits: List[str] = []
            if title:
                suffix_bits.append(title)
            if source:
                suffix_bits.append(source)
            if isinstance(score, (int, float)):
                suffix_bits.append(f"score {score:.2f}")
            suffix = f" ({'; '.join(suffix_bits)})" if suffix_bits else ""
            formatted.append(f"{name}{suffix}")
        return self._dedupe_lines(formatted)

    @staticmethod
    def _dedupe_lines(lines: List[str]) -> List[str]:
        seen: set[str] = set()
        output: List[str] = []
        for line in lines:
            normalized = str(line or "").strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            output.append(normalized)
        return output

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
