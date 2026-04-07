"""
Movement-specific candidate selection and credential search context building.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from models.bd_schemas import CredentialSearchContext, SignalEvidence
from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalized_key(value: Any) -> str:
    return _normalized_text(value).lower()


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _role_category(new_role: str) -> str:
    normalized = _normalized_key(new_role)
    exec_markers = (
        "chief",
        "ceo",
        "cio",
        "cto",
        "cfo",
        "coo",
        "president",
        "general counsel",
        "board",
        "head of",
    )
    return "EXEC" if any(marker in normalized for marker in exec_markers) else "BUYER"


def _unique_preserve_order(values: List[str], *, limit: Optional[int] = None) -> List[str]:
    results: List[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalized_text(value)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        results.append(normalized)
        if limit is not None and len(results) >= limit:
            break
    return results


@dataclass(frozen=True)
class MovementCredentialCandidate:
    """Single movement row selected for credentials lookup."""

    source_type: str
    person_name: str
    target_company: str
    new_role: str
    previous_role: str
    category: str
    evidence_quote: str
    source_url: str
    selection_reason: str
    ranked_row: Optional[Dict[str, Any]] = None

    @property
    def dedupe_key(self) -> str:
        return _normalized_key(self.person_name)


class MovementCredentialCandidateSelector:
    """Select the movement rows worth precomputing credentials for."""

    def select(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        ranked_rows: List[Dict[str, Any]],
        actioning_context: Optional[Dict[str, Any]],
        max_candidates: int = 3,
    ) -> List[MovementCredentialCandidate]:
        if max_candidates <= 0:
            return []

        ordered_rows = list(ranked_rows or [])
        selected: List[MovementCredentialCandidate] = []
        seen: set[str] = set()

        named_candidate = self._build_named_mover_candidate(
            request=request,
            preflight=preflight,
            ranked_rows=ordered_rows,
            actioning_context=actioning_context or {},
        )
        if named_candidate is not None:
            selected.append(named_candidate)
            seen.add(named_candidate.dedupe_key)

        exact_matches: List[MovementCredentialCandidate] = []
        fallbacks: List[MovementCredentialCandidate] = []
        for rank_index, row in enumerate(ordered_rows, start=1):
            candidate = self._build_ranked_row_candidate(row=row, rank_index=rank_index)
            if candidate is None or candidate.dedupe_key in seen:
                continue
            if _normalized_key(row.get("person_match_status")) == "matched":
                exact_matches.append(candidate)
            else:
                fallbacks.append(candidate)

        for candidate in [*exact_matches, *fallbacks]:
            if len(selected) >= max_candidates:
                break
            if candidate.dedupe_key in seen:
                continue
            selected.append(candidate)
            seen.add(candidate.dedupe_key)

        return selected[:max_candidates]

    def _build_ranked_row_candidate(
        self,
        *,
        row: Dict[str, Any],
        rank_index: int,
    ) -> Optional[MovementCredentialCandidate]:
        movement = _as_dict(row).get("movement")
        if movement is None:
            return None
        person_name = _normalized_text(getattr(movement, "person_name", ""))
        target_company = _normalized_text(getattr(movement, "target_company", ""))
        new_role = _normalized_text(getattr(movement, "new_role", ""))
        previous_role = _normalized_text(getattr(movement, "previous_role", ""))
        if not person_name or not target_company or not new_role:
            return None

        matched = _normalized_key(row.get("person_match_status")) == "matched"
        selection_reason = (
            f"Selected exact ProConnect match ranked #{rank_index}."
            if matched
            else f"Selected ranked fallback row #{rank_index} after matched movers."
        )
        evidence = getattr(movement, "evidence", None)
        return MovementCredentialCandidate(
            source_type="ranked_row",
            person_name=person_name,
            target_company=target_company,
            new_role=new_role,
            previous_role=previous_role,
            category=_normalized_text(getattr(movement, "category", "")) or _role_category(new_role),
            evidence_quote=_normalized_text(getattr(evidence, "evidence_quote", "")),
            source_url=_normalized_text(getattr(evidence, "source_url", "")),
            selection_reason=selection_reason,
            ranked_row=row,
        )

    def _build_named_mover_candidate(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        ranked_rows: List[Dict[str, Any]],
        actioning_context: Dict[str, Any],
    ) -> Optional[MovementCredentialCandidate]:
        if not request.synthetic_scenario:
            return None
        if _normalized_key(preflight.person_resolution.match_status) != "matched":
            return None
        if not actioning_context:
            return None

        named_people = {
            _normalized_key(request.person_name),
            _normalized_key(preflight.person_resolution.matched_name or request.person_name),
        }
        named_people.discard("")
        if any(
            _normalized_key(getattr(row.get("movement"), "person_name", "")) in named_people
            for row in ranked_rows
        ):
            return None

        person_name = _normalized_text(preflight.person_resolution.matched_name or request.person_name)
        target_company = _normalized_text(preflight.to_account.company_name or request.to_company)
        new_role = _normalized_text(request.new_role)
        previous_role = _normalized_text(
            preflight.person_resolution.matched_title or f"Current role at {request.from_company}"
        )
        if not person_name or not target_company or not new_role:
            return None

        return MovementCredentialCandidate(
            source_type="named_mover",
            person_name=person_name,
            target_company=target_company,
            new_role=new_role,
            previous_role=previous_role,
            category=_role_category(new_role),
            evidence_quote=(
                f"Scenario input validated against ProConnect: {person_name} is modeled as moving "
                f"from {request.from_company} to {target_company} as {new_role}."
            ),
            source_url="internal://named-move-scenario",
            selection_reason="Reserved named mover scenario row because it is an exact ProConnect match.",
            ranked_row=None,
        )


class MovementCredentialContextBuilder:
    """Build a structured credentials search context for movement-led lookups."""

    _FS_ROLE_PROFILES: Dict[str, Dict[str, List[str]]] = {
        "technology_leadership": {
            "buyer_priorities": [
                "technology modernization",
                "cyber resilience",
                "data governance",
                "AI governance",
                "IT risk and controls",
            ],
            "likely_client_needs": [
                "modernize technology governance and control environment",
                "prioritize cloud and platform operating model decisions",
                "strengthen board-ready cyber and AI oversight",
            ],
        },
        "security_privacy": {
            "buyer_priorities": [
                "security strategy",
                "resilience and incident readiness",
                "identity and access control",
                "privacy and regulatory alignment",
            ],
            "likely_client_needs": [
                "improve cyber governance and resilience programs",
                "close control gaps tied to regulatory scrutiny",
                "modernize identity, access, and threat response processes",
            ],
        },
        "data_ai": {
            "buyer_priorities": [
                "data governance",
                "AI enablement",
                "analytics operating model",
                "data quality and controls",
            ],
            "likely_client_needs": [
                "stand up enterprise data governance and quality controls",
                "govern AI adoption with risk, compliance, and model controls",
                "improve analytics delivery and business adoption",
            ],
        },
        "risk_compliance_audit": {
            "buyer_priorities": [
                "enterprise risk management",
                "regulatory compliance",
                "controls rationalization",
                "internal audit modernization",
            ],
            "likely_client_needs": [
                "strengthen risk and controls programs under regulatory pressure",
                "modernize internal audit and compliance operating models",
                "improve issue management, reporting, and assurance coverage",
            ],
        },
        "finance_controllership": {
            "buyer_priorities": [
                "finance transformation",
                "controllership effectiveness",
                "regulatory reporting",
                "cost and performance management",
            ],
            "likely_client_needs": [
                "improve finance controls and reporting readiness",
                "streamline planning, close, and controllership processes",
                "modernize finance operating model and governance",
            ],
        },
        "legal_corporate_secretary": {
            "buyer_priorities": [
                "legal operations",
                "corporate governance",
                "regulatory coordination",
                "board and entity management",
            ],
            "likely_client_needs": [
                "improve governance, committee, and entity-management processes",
                "modernize legal operations and risk reporting workflows",
                "support regulatory readiness and cross-functional coordination",
            ],
        },
        "operations_transformation": {
            "buyer_priorities": [
                "operating model effectiveness",
                "process optimization",
                "service delivery resilience",
                "transformation execution",
            ],
            "likely_client_needs": [
                "optimize operating model and process effectiveness",
                "improve service delivery, resiliency, and controls",
                "execute transformation with measurable business outcomes",
            ],
        },
        "executive_general": {
            "buyer_priorities": [
                "strategy execution",
                "governance",
                "risk management",
                "operating model clarity",
            ],
            "likely_client_needs": [
                "support the new leader's first-year agenda with pragmatic governance and transformation work",
                "align executive priorities to delivery-ready programs",
            ],
        },
        "buyer_general": {
            "buyer_priorities": [
                "functional transformation",
                "controls improvement",
                "team effectiveness",
                "process modernization",
            ],
            "likely_client_needs": [
                "translate new-role accountability into practical transformation work",
                "improve function-specific controls, processes, and reporting",
            ],
        },
    }

    def build(
        self,
        *,
        candidate: MovementCredentialCandidate,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        signal_evidence: List[SignalEvidence],
        actioning_context: Optional[Dict[str, Any]],
    ) -> CredentialSearchContext:
        company_context = self._resolve_company_context(
            company_name=candidate.target_company,
            request=request,
            preflight=preflight,
            actioning_context=actioning_context or {},
        )
        industry = self._resolve_industry(
            preflight=preflight,
            request=request,
            company_context=company_context,
        )
        subindustry = _normalized_text(
            company_context.get("subIndustry")
            or company_context.get("subindustry")
            or company_context.get("sub_industry")
        )
        role_family = self._infer_role_family(candidate.new_role, candidate.category)
        priorities, likely_needs = self._resolve_role_profile(
            industry=industry,
            role_family=role_family,
            category=candidate.category,
        )
        account_signals = self._build_account_signals(
            candidate=candidate,
            preflight=preflight,
            signal_evidence=signal_evidence,
            actioning_context=actioning_context or {},
        )

        return CredentialSearchContext(
            person_name=candidate.person_name,
            person_title=candidate.new_role,
            company_name=candidate.target_company,
            industry=industry,
            subindustry=subindustry,
            role_family=role_family,
            buyer_priorities=priorities,
            likely_client_needs=likely_needs,
            account_signals=account_signals,
            selection_reason=candidate.selection_reason,
        )

    def _resolve_industry(
        self,
        *,
        preflight: TransitionPreflight,
        request: MovementBriefRequest,
        company_context: Dict[str, Any],
    ) -> str:
        raw = (
            company_context.get("industry")
            or preflight.inferred_industry
            or request.industry_override
            or ""
        )
        text = _normalized_text(raw)
        if text.lower() == "financial_services":
            return "Financial Services"
        if text.lower() == "financial services & real estate":
            return "Financial Services"
        return text or "General"

    def _resolve_company_context(
        self,
        *,
        company_name: str,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        actioning_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        from_context = _as_dict(actioning_context.get("from_company_context"))
        to_context = _as_dict(actioning_context.get("to_company_context"))
        candidates = [
            (
                _normalized_key(preflight.to_account.company_name or request.to_company),
                _as_dict(to_context.get("account_context")),
            ),
            (
                _normalized_key(preflight.from_account.company_name or request.from_company),
                _as_dict(from_context.get("account_header")),
            ),
        ]
        company_key = _normalized_key(company_name)
        for expected_key, context in candidates:
            if expected_key and company_key == expected_key:
                return context
        return _as_dict(to_context.get("account_context")) or _as_dict(from_context.get("account_header"))

    def _build_account_signals(
        self,
        *,
        candidate: MovementCredentialCandidate,
        preflight: TransitionPreflight,
        signal_evidence: List[SignalEvidence],
        actioning_context: Dict[str, Any],
    ) -> List[str]:
        signals: List[str] = []
        signals.extend(
            item.signal_label
            for item in signal_evidence
            if getattr(item, "status", "") == "Confirmed"
        )
        signals.extend(
            _normalized_text(item.title)
            for item in list(preflight.opportunity_hypotheses or [])[:3]
            if _normalized_text(item.title)
        )
        if preflight.quick_indicators.warm_intro_path_available:
            signals.append("Warm introduction path available.")
        if preflight.quick_indicators.destination_worked_before:
            signals.append("Protiviti has prior destination-account work.")

        if candidate.source_type == "named_mover":
            profile = _as_dict(actioning_context.get("person_profile"))
            if int(profile.get("project_count") or 0) > 0 or int(profile.get("win_count") or 0) > 0:
                signals.append("Protiviti has direct person-linked delivery history.")
            else:
                signals.append("Exact ProConnect match for the named mover.")
        else:
            row = candidate.ranked_row or {}
            if int(row.get("project_count") or 0) > 0 or int(row.get("win_count") or 0) > 0:
                signals.append("Protiviti has direct person-linked delivery history.")
            elif _normalized_key(row.get("person_match_status")) == "matched":
                signals.append("Exact ProConnect match for this buyer/executive.")
            if row.get("relationship_owner"):
                signals.append(f"Relationship owner identified: {_normalized_text(row.get('relationship_owner'))}.")

        return _unique_preserve_order(signals, limit=6)

    def _resolve_role_profile(
        self,
        *,
        industry: str,
        role_family: str,
        category: str,
    ) -> Tuple[List[str], List[str]]:
        is_financial_services = "financial" in _normalized_key(industry)
        if is_financial_services and role_family in self._FS_ROLE_PROFILES:
            profile = self._FS_ROLE_PROFILES[role_family]
            return list(profile["buyer_priorities"]), list(profile["likely_client_needs"])

        fallback_family = "executive_general" if _normalized_key(category) == "exec" else "buyer_general"
        profile = self._FS_ROLE_PROFILES[fallback_family]
        return list(profile["buyer_priorities"]), list(profile["likely_client_needs"])

    def _infer_role_family(self, new_role: str, category: str) -> str:
        normalized = _normalized_key(new_role)
        if any(marker in normalized for marker in ("chief information", "cio", "chief technology", "cto", "technology officer", "information officer")):
            return "technology_leadership"
        if any(marker in normalized for marker in ("chief security", "ciso", "security", "privacy")):
            return "security_privacy"
        if any(marker in normalized for marker in ("data", "analytics", "ai", "artificial intelligence", "digital")):
            return "data_ai"
        if any(marker in normalized for marker in ("risk", "compliance", "audit", "controls")):
            return "risk_compliance_audit"
        if any(marker in normalized for marker in ("finance", "financial", "controller", "controll", "treasurer", "accounting", "cfo")):
            return "finance_controllership"
        if any(marker in normalized for marker in ("general counsel", "legal", "corporate secretary", "corporate counsel")):
            return "legal_corporate_secretary"
        if any(marker in normalized for marker in ("operations", "operating", "transformation", "procurement", "service delivery")):
            return "operations_transformation"
        return "executive_general" if _normalized_key(category) == "exec" else "buyer_general"
