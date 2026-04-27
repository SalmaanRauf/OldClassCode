"""
Three-stage account brief orchestration.
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from config.config import Config as AppConfig
from services.account_brief_synthesizer import (
    AccountBriefSynthesisResult,
    AccountBriefSynthesizer,
    SynthesizedSuggestedPlay,
)
from services.account_research_input import AccountResearchInput
from services.proconnect_account_research_service import ProConnectAccountResearchService
from services.proconnect_auth import resolve_runtime_bearer_token
from services.public_account_research_orchestrator import (
    PublicAccountResearchOrchestrator,
    PublicAccountResearchRunResult,
)
from scripts.proconnect_client import DEFAULT_BASE_URL, ProConnectClient


SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


class AccountBriefOrchestrator:
    """Coordinate ProConnect facts, public research, and bounded synthesis."""

    def __init__(
        self,
        *,
        proconnect_service: Any = None,
        public_research_orchestrator: Any = None,
        synthesizer: Any = None,
    ) -> None:
        self.proconnect_service = proconnect_service
        self.public_research_orchestrator = public_research_orchestrator
        self.synthesizer = synthesizer
        self._owns_proconnect_service = proconnect_service is None

    async def run(
        self,
        request: AccountResearchInput,
        *,
        industry_key: Optional[str] = None,
        progress_cb=None,
    ) -> Dict[str, Any]:
        await self._emit_progress(
            progress_cb,
            stage="resolving_account",
            message=f"Resolving {request.account_name} in ProConnect.",
            status="running",
        )
        await self._emit_progress(
            progress_cb,
            stage="collecting_proconnect_context",
            message=f"Collecting internal ProConnect context for {request.account_name}.",
            status="running",
        )
        proconnect_summary = await self._collect_proconnect_summary(request)
        resolved_company_name = self._first_text(
            ((proconnect_summary.get("account_resolution") or {}).get("company_name")),
            ((proconnect_summary.get("account_resolution") or {}).get("resolved_name")),
            request.account_name,
        )

        await self._emit_progress(
            progress_cb,
            stage="running_public_research",
            message=f"Running public Deep Research for {resolved_company_name}.",
            status="running",
        )
        deep_research_result = await self._get_public_research_orchestrator().run(
            company_name=resolved_company_name,
            focus_hint=self._public_focus_hint(request.focus_hint),
            industry=industry_key or None,
            progress_cb=progress_cb,
        )
        deep_research_summary = self._unwrap_public_research_result(deep_research_result)

        coverage_gaps = self._merge_coverage_gaps(
            proconnect_summary.get("coverage_gaps") or [],
            deep_research_summary.get("coverage_gaps") or [],
        )
        synthesis_input = self._get_synthesizer().build_input(
            request_context={
                "account_name": resolved_company_name,
                "raw_input": request.raw_input,
                "focus_hint": request.focus_hint,
            },
            proconnect_summary=proconnect_summary,
            deep_research_summary=deep_research_summary,
            source_boundary_rules={
                "no_public_as_internal": True,
                "no_internal_as_public": True,
                "no_unsupported_factual_claims": True,
            },
            coverage_gaps=coverage_gaps,
            synthesis_rules={
                "short_brief": True,
                "light_inference": True,
                "facts_first": True,
                "preserve_uncertainty": True,
            },
        )
        await self._emit_progress(
            progress_cb,
            stage="synthesizing_account_brief",
            message=f"Synthesizing final account brief for {resolved_company_name}.",
            status="running",
        )
        synthesis_result = await self._get_synthesizer().synthesize(synthesis_input)
        synthesis = self._normalize_synthesis(
            synthesis_result=synthesis_result,
            proconnect_summary=proconnect_summary,
            deep_research_summary=deep_research_summary,
            coverage_gaps=coverage_gaps,
        )

        response = {
            "type": "account_brief",
            "company": resolved_company_name,
            "request": {
                "account_name": resolved_company_name,
                "raw_input": request.raw_input,
                "focus_hint": request.focus_hint,
            },
            "proconnect_summary": proconnect_summary,
            "deep_research_summary": deep_research_summary,
            "synthesis": synthesis,
            "coverage_gaps": coverage_gaps,
            "citations": list(deep_research_summary.get("citations") or []),
        }
        await self._emit_progress(
            progress_cb,
            stage="account_brief_complete",
            message=f"Account brief ready for {resolved_company_name}.",
            status="complete",
        )
        return response

    async def _collect_proconnect_summary(self, request: AccountResearchInput) -> Dict[str, Any]:
        result = await asyncio.to_thread(
            self._collect_proconnect_summary_sync,
            request,
        )
        return result

    def _collect_proconnect_summary_sync(self, request: AccountResearchInput) -> Dict[str, Any]:
        result = self._get_proconnect_service().collect_account_research(request.account_name)
        if inspect.isawaitable(result):
            raise TypeError("ProConnect account collection must be synchronous.")
        return dict(result or {})

    def _get_proconnect_service(self) -> ProConnectAccountResearchService:
        if self.proconnect_service is None:
            if self._owns_proconnect_service:
                return self._build_live_proconnect_service()
            raise RuntimeError("ProConnect service is not configured.")
        if self._owns_proconnect_service:
            return self._build_live_proconnect_service()
        return self.proconnect_service

    def _get_public_research_orchestrator(self) -> PublicAccountResearchOrchestrator:
        if self.public_research_orchestrator is None:
            self.public_research_orchestrator = PublicAccountResearchOrchestrator()
        return self.public_research_orchestrator

    def _get_synthesizer(self) -> AccountBriefSynthesizer:
        if self.synthesizer is None:
            self.synthesizer = AccountBriefSynthesizer()
        return self.synthesizer

    @staticmethod
    def _unwrap_public_research_result(result: Any) -> Dict[str, Any]:
        if isinstance(result, PublicAccountResearchRunResult):
            return dict(result.deep_research_response or {})
        if isinstance(result, dict):
            return dict(result)
        payload = getattr(result, "deep_research_response", None)
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    @classmethod
    def _normalize_synthesis(
        cls,
        *,
        synthesis_result: Optional[AccountBriefSynthesisResult],
        proconnect_summary: Dict[str, Any],
        deep_research_summary: Dict[str, Any],
        coverage_gaps: List[str],
    ) -> Dict[str, Any]:
        account_status = dict(proconnect_summary.get("account_status") or {})
        opportunities = list(proconnect_summary.get("open_opportunities") or [])
        if synthesis_result is None:
            return {
                "headline": account_status.get("summary") or deep_research_summary.get("summary") or "Account brief assembled from available evidence.",
                "account_status_summary": account_status.get("summary") or "Internal account status is partially available.",
                "why_now": deep_research_summary.get("summary") or "Public why-now evidence is limited.",
                "relationship_posture": cls._build_relationship_posture(proconnect_summary),
                "buyer_posture": cls._build_buyer_posture(proconnect_summary),
                "leadership_coverage_summary": cls._build_leadership_coverage_summary(proconnect_summary, deep_research_summary),
                "top_openings": cls._fallback_top_openings(opportunities),
                "suggested_plays": [],
                "key_gaps": list(coverage_gaps or []),
                "takeaway": "Use the sourced internal and public evidence directly while final analyst synthesis is unavailable.",
            }

        return {
            "headline": synthesis_result.account_summary,
            "account_status_summary": account_status.get("summary") or synthesis_result.account_summary,
            "why_now": cls._join_text_list(synthesis_result.signal_summary),
            "relationship_posture": cls._build_relationship_posture(proconnect_summary),
            "buyer_posture": cls._build_buyer_posture(proconnect_summary),
            "leadership_coverage_summary": cls._build_leadership_coverage_summary(proconnect_summary, deep_research_summary),
            "top_openings": cls._normalize_top_openings(synthesis_result.opportunity_summary, opportunities),
            "suggested_plays": cls._normalize_suggested_plays(synthesis_result.suggested_plays),
            "key_gaps": list(coverage_gaps or []),
            "takeaway": synthesis_result.takeaway,
        }

    @classmethod
    def _build_relationship_posture(cls, proconnect_summary: Dict[str, Any]) -> str:
        relationships = dict(proconnect_summary.get("known_relationships") or {})
        alumni = list(((relationships.get("protiviti_alumni") or {}).get("items") or []))
        connected = list(((relationships.get("connected_colleagues") or {}).get("items") or []))
        routes = list(relationships.get("relationship_routes") or [])
        if routes:
            return (
                f"Known internal relationship routes are present via {', '.join(routes)} "
                f"({len(alumni)} alumni, {len(connected)} connected colleagues)."
            )
        return "No warm intro path is currently surfaced in ProConnect."

    @classmethod
    def _build_buyer_posture(cls, proconnect_summary: Dict[str, Any]) -> str:
        buyers = list(proconnect_summary.get("known_buyers") or [])
        if not buyers:
            return "Known buyer coverage is thin in ProConnect."
        top_names = [cls._first_text(item.get("name")) for item in buyers[:3]]
        top_names = [name for name in top_names if name]
        names_text = ", ".join(top_names)
        return f"Known buyer coverage includes {len(buyers)} buyer record(s){': ' + names_text if names_text else '.'}"

    @classmethod
    def _build_leadership_coverage_summary(
        cls,
        proconnect_summary: Dict[str, Any],
        deep_research_summary: Dict[str, Any],
    ) -> str:
        org_chart = dict(proconnect_summary.get("org_chart_coverage") or {})
        org_people_count = int(org_chart.get("people_count") or 0)
        public_sections = list(deep_research_summary.get("sections") or [])
        public_titles = [
            cls._first_text(section.get("title"))
            for section in public_sections
            if isinstance(section, dict)
        ]
        public_titles = [title for title in public_titles if title]
        if org_people_count:
            return (
                f"ProConnect surfaced {org_people_count} org-chart contact(s). "
                f"Public research sections include {', '.join(public_titles[:3]) or 'additional leadership context'}."
            )
        if public_titles:
            return f"Leadership coverage relies on public research sections such as {', '.join(public_titles[:3])}."
        return "Leadership coverage is limited across both internal and public sources."

    @classmethod
    def _normalize_top_openings(
        cls,
        synthesized_items: List[str],
        internal_opportunities: List[Dict[str, Any]],
    ) -> List[str]:
        normalized = [cls._first_text(item) for item in list(synthesized_items or [])]
        normalized = [item for item in normalized if item]
        if normalized:
            return normalized
        return cls._fallback_top_openings(internal_opportunities)

    @classmethod
    def _fallback_top_openings(cls, internal_opportunities: List[Dict[str, Any]]) -> List[str]:
        openings: List[str] = []
        for item in list(internal_opportunities or [])[:3]:
            name = cls._first_text(item.get("opportunity"), item.get("solution"), item.get("service_name"))
            stage = cls._first_text(item.get("stage"))
            if not name:
                continue
            openings.append(f"{name}{f' ({stage})' if stage else ''}")
        return openings

    @classmethod
    def _normalize_suggested_plays(
        cls,
        plays: List[SynthesizedSuggestedPlay],
    ) -> List[str]:
        rows: List[str] = []
        for item in list(plays or []):
            if not item.play or not item.why_now:
                continue
            rows.append(f"{item.play} Why now: {item.why_now}")
        return rows

    def _build_live_proconnect_service(self) -> ProConnectAccountResearchService:
        token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
        base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
        fallback_paths = [
            Path.cwd() / "token.txt",
            SCRIPT_DIR / "token.txt",
        ]
        token, _ = resolve_runtime_bearer_token(token_file=token_file, fallback_paths=fallback_paths)
        client = ProConnectClient(base_url=base_url, bearer_token=token)
        return ProConnectAccountResearchService(client=client)

    @staticmethod
    def _public_focus_hint(focus_hint: Optional[str]) -> Optional[str]:
        text = " ".join(str(focus_hint or "").split()).strip()
        if not text:
            return None

        internal_patterns = [
            r"\bproconnect\b",
            r"\bprotiviti\b",
            r"\brobert\s+half\b",
            r"\brhi\b",
            r"\bpro\b",
            r"\bmsa\b",
            r"\bno\s+known\s+work\b",
            r"\bknown\s+work\b",
            r"\bworked\s+before\b",
            r"\baccount\s+team\b",
            r"\brelationship\s+(?:owner|owners|gap|gaps|route|routes|mapping|status|context|network)\b",
            r"\bconnected\s+colleagues?\b",
            r"\bwarm\s+intro\b",
            r"\binternal\s+(?:buyer|buyers|pipeline|relationship|relationships|opportunity|opportunities)\b",
            r"\bopen\s+opportunit(?:y|ies)\b",
            r"\bpast\s+work\b",
            r"\bpipeline\b",
            r"\bpgp\s+elite\b",
            r"\benterprise\s+revenue\s+acceleration\b",
        ]
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in internal_patterns):
            return None
        return text

    @staticmethod
    def _merge_coverage_gaps(*groups: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for group in groups:
            for item in list(group or []):
                text = " ".join(str(item or "").split()).strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(text)
        return merged

    @staticmethod
    def _join_text_list(items: List[str]) -> str:
        normalized = [AccountBriefOrchestrator._first_text(item) for item in list(items or [])]
        normalized = [item for item in normalized if item]
        return " ".join(normalized)

    @staticmethod
    def _first_text(*values: Any) -> str:
        for value in values:
            text = " ".join(str(value or "").split()).strip()
            if text:
                return text
        return ""

    @staticmethod
    async def _emit_progress(progress_cb, **event: Any) -> None:
        if progress_cb is None:
            return
        result = progress_cb(dict(event))
        if inspect.isawaitable(result):
            await result
