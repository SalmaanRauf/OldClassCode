"""
Orchestration for the named-move People Movement Brief workflow.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config.config import AppConfig
from models.bd_schemas import SignalEvidence
from models.movement_schemas import (
    MovementBrief,
    MovementBriefRequest,
    MovementCredentialsProof,
    MovementRecord,
)
from models.transition_schemas import TransitionPreflight
from services.credentials_lookup_runner import CredentialsLookupRunResult, CredentialsLookupRunner
from services.deep_research_formatter import (
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)
from services.fs_movement_digestor import FSMovementDigestor
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor
from services.movement_brief_assembler import MovementBriefAssembler
from services.movement_credentials_service import MovementCredentialsService
from services.movement_form_mapper import build_movement_trigger, build_transition_request_for_movement
from services.movement_opportunity_deriver import MovementOpportunityDeriver
from services.movement_prompt_builder import MovementPromptBuilder, MovementPromptPackage
from services.movement_brief_synthesizer import MovementBriefSynthesizer
from services.proconnect_auth import resolve_runtime_bearer_token
from services.proconnect_movement_service import ProConnectMovementService
from services.proconnect_transition_service import ProConnectTransitionService
from services.signal_registry_service import get_signal_registry_service
from services.workflow_state import WorkflowStage
from scripts.proconnect_client import DEFAULT_BASE_URL, ProConnectClient


ProgressCallback = Callable[[Any], Any]
DeepResearchRunner = Callable[..., Awaitable[Dict[str, Any]]]
logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


@dataclass(frozen=True)
class MovementPreflightResult:
    preflight: TransitionPreflight
    actioning_context: Dict[str, Any]
    prompt_package: MovementPromptPackage


@dataclass(frozen=True)
class MovementBriefRunResult:
    """End-to-end artifacts for a people movement brief run."""

    request: MovementBriefRequest
    preflight: TransitionPreflight
    actioning_context: Dict[str, Any]
    prompt_package: MovementPromptPackage
    movement_brief: MovementBrief
    deep_research_markdown: str
    signal_evidence: List[SignalEvidence]
    movement_rows: List[MovementRecord]
    light_enriched_rows: List[Dict[str, Any]]
    ranked_rows: List[Dict[str, Any]]
    deep_enriched_rows: List[Dict[str, Any]]
    derived_opportunities: List[Any]
    credential_packets: Dict[str, MovementCredentialsProof]
    credentials_lookup: CredentialsLookupRunResult
    signal_diagnostics: Dict[str, Any]
    movement_diagnostics: Dict[str, Any]


@dataclass(frozen=True)
class ReviewedMovementRunInput:
    run_id: str
    request: MovementBriefRequest
    preflight: TransitionPreflight
    actioning_context: Dict[str, Any]
    prompt_package: MovementPromptPackage


class MovementBriefOrchestrator:
    """Coordinates preflight, Deep Research, movement extraction, leverage, proof, and assembly."""

    def __init__(
        self,
        *,
        transition_service: Optional[ProConnectTransitionService] = None,
        prompt_builder: Optional[MovementPromptBuilder] = None,
        fs_signal_evidence_digestor: Optional[FSSignalEvidenceDigestor] = None,
        movement_digestor: Optional[FSMovementDigestor] = None,
        proconnect_service: Optional[ProConnectMovementService] = None,
        ranker: Optional[Any] = None,
        opportunity_deriver: Optional[MovementOpportunityDeriver] = None,
        credentials_lookup_runner: Optional[CredentialsLookupRunner] = None,
        credentials_service: Optional[MovementCredentialsService] = None,
        assembler: Optional[MovementBriefAssembler] = None,
        brief_synthesizer: Optional[MovementBriefSynthesizer] = None,
        deep_research_runner: Optional[DeepResearchRunner] = None,
    ) -> None:
        self.signal_registry = get_signal_registry_service()
        self.transition_service = transition_service
        self._owns_transition_service = transition_service is None
        self.prompt_builder = prompt_builder or MovementPromptBuilder()
        self.fs_signal_evidence_digestor = fs_signal_evidence_digestor or FSSignalEvidenceDigestor()
        self.movement_digestor = movement_digestor or FSMovementDigestor()
        self.proconnect_service = proconnect_service
        self._owns_proconnect_service = proconnect_service is None
        from services.movement_ranker import MovementRanker

        self.ranker = ranker or MovementRanker()
        self.opportunity_deriver = opportunity_deriver or MovementOpportunityDeriver()
        self.credentials_lookup_runner = credentials_lookup_runner or CredentialsLookupRunner()
        self.credentials_service = credentials_service or MovementCredentialsService()
        self.assembler = assembler or MovementBriefAssembler()
        self.brief_synthesizer = brief_synthesizer or MovementBriefSynthesizer()
        self.deep_research_runner = deep_research_runner

    async def build_preflight(
        self,
        request: MovementBriefRequest,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> MovementPreflightResult:
        _, preflight, actioning_context, prompt_package = await self._prepare_move_context(
            request,
            progress_cb=progress_cb,
        )
        return MovementPreflightResult(
            preflight=preflight,
            actioning_context=actioning_context,
            prompt_package=prompt_package,
        )

    async def run(
        self,
        request: MovementBriefRequest,
        *,
        deep_research_output: Optional[str] = None,
        deep_research_response: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[ProgressCallback] = None,
        prompt_override: Optional[str] = None,
        reviewed_preflight: Optional[TransitionPreflight] = None,
        reviewed_actioning_context: Optional[Dict[str, Any]] = None,
        reviewed_prompt_package: Optional[MovementPromptPackage] = None,
        reviewed_run_id: Optional[str] = None,
    ) -> MovementBriefRunResult:
        """Run the full named-move movement-led pipeline."""
        if reviewed_preflight and reviewed_prompt_package:
            preflight = reviewed_preflight
            actioning_context = dict(reviewed_actioning_context or {})
            prompt_package = reviewed_prompt_package
            logger.info(
                "Movement research using reviewed context run_id=%s person=%s destination=%s",
                reviewed_run_id,
                request.person_name,
                request.to_company,
            )
        else:
            _, preflight, actioning_context, prompt_package = await self._prepare_move_context(
                request,
                progress_cb=progress_cb,
                prompt_override=prompt_override,
            )
            logger.info(
                "Movement research rebuilt context person=%s destination=%s",
                request.person_name,
                request.to_company,
            )
        self._log_named_mover_context(
            request=request,
            preflight=preflight,
            actioning_context=actioning_context,
            run_id=reviewed_run_id,
        )
        trigger = build_movement_trigger(request)
        trigger.company_focus = (
            str(preflight.to_account.company_name or "").strip()
            or trigger.company_focus
            or request.to_company
        )

        structured_evidence_map: Dict[str, Any] = {}
        if deep_research_output is None:
            if deep_research_response is not None:
                deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                structured_evidence_map = build_structured_evidence_map(deep_research_response)
            else:
                logger.info(
                    "Movement Deep Research starting run_id=%s industry=%s prompt_chars=%s",
                    reviewed_run_id,
                    prompt_package.industry_key,
                    len(prompt_package.user_prompt),
                )
                deep_research_response = await self._run_deep_research(prompt_package, progress_cb)
                logger.info(
                    "Movement Deep Research finished run_id=%s industry=%s",
                    reviewed_run_id,
                    prompt_package.industry_key,
                )
                deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                structured_evidence_map = build_structured_evidence_map(deep_research_response)

        deep_research_markdown = deep_research_output or ""
        deep_research_summary = self._extract_summary(deep_research_response, deep_research_markdown)

        await self._emit(
            progress_cb,
            stage=WorkflowStage.ACCOUNT_SIGNALS.value,
            message="Normalizing financial-services signal evidence.",
            status="in_progress",
            run_id=reviewed_run_id,
        )
        requested_signal_codes = list(trigger.signals or [])
        if self.signal_registry.is_financial_services(trigger.sector) and not requested_signal_codes:
            requested_signal_codes = self.signal_registry.get_fs_signal_codes()

        signal_evidence, signal_diagnostics, _allowed_sources = await self.fs_signal_evidence_digestor.digest(
            trigger=trigger,
            deep_research_markdown=deep_research_markdown,
            requested_signal_codes=requested_signal_codes,
            source_urls=[],
            section_source_map=structured_evidence_map.get("section_source_map") or {},
            signal_source_candidates=structured_evidence_map.get("signal_source_candidates") or {},
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.ACCOUNT_SIGNALS.value,
            message="Financial-services signal evidence normalized.",
            status="complete",
            confirmed_signal_count=len([item for item in signal_evidence if item.status == "Confirmed"]),
            run_id=reviewed_run_id,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.EXECUTIVE_MOVEMENT.value,
            message="Extracting executive and buyer movement rows.",
            status="in_progress",
            run_id=reviewed_run_id,
        )
        movement_rows, movement_diagnostics = await self.movement_digestor.digest(
            trigger=trigger,
            deep_research_markdown=deep_research_markdown,
            target_company_aliases=self._target_company_aliases(request, preflight),
        )
        logger.info(
            "Movement rows prepared run_id=%s extracted=%s retained=%s named_mover_present=%s pass_results=%s rows=%s",
            reviewed_run_id,
            movement_diagnostics.get("movements_returned"),
            len(movement_rows),
            any(
                self._normalize_person_name(row.person_name)
                in {
                    self._normalize_person_name(request.person_name),
                    self._normalize_person_name(preflight.person_resolution.matched_name or ""),
                }
                for row in movement_rows
            ),
            movement_diagnostics.get("pass_results"),
            [
                {
                    "person": row.person_name,
                    "category": row.category,
                    "movement_type": row.movement_type,
                }
                for row in movement_rows[:25]
            ],
        )
        executive_count = len([row for row in movement_rows if getattr(row, "category", "") == "EXEC"])
        buyer_count = len([row for row in movement_rows if getattr(row, "category", "") == "BUYER"])
        await self._emit(
            progress_cb,
            stage=WorkflowStage.EXECUTIVE_MOVEMENT.value,
            message="Executive movement extracted.",
            status="complete",
            movement_count=executive_count,
            run_id=reviewed_run_id,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUYER_MOVEMENT.value,
            message="Buyer movement extracted.",
            status="complete",
            movement_count=buyer_count,
            run_id=reviewed_run_id,
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.PROCONNECT_ENRICHMENT.value,
            message="Matching movement leverage in ProConnect.",
            status="in_progress",
            run_id=reviewed_run_id,
        )
        proconnect_service = self._get_proconnect_service()
        self._prime_proconnect_accounts(proconnect_service, request, preflight)
        light_enriched_rows = proconnect_service.light_enrich_movements(movement_rows)
        light_enriched_rows = self._refresh_named_mover_enrichment(
            light_enriched_rows,
            request=request,
            preflight=preflight,
            actioning_context=actioning_context,
            proconnect_service=proconnect_service,
            include_person_detail=False,
        )
        ranked_rows = self.ranker.rank(light_enriched_rows)

        ranked_movements = [row["movement"] for row in ranked_rows]
        deep_enriched_rows = proconnect_service.deep_enrich_movements(
            ranked_movements,
            max_rows=len(ranked_movements),
        )
        deep_enriched_rows = self._refresh_named_mover_enrichment(
            deep_enriched_rows,
            request=request,
            preflight=preflight,
            actioning_context=actioning_context,
            proconnect_service=proconnect_service,
            include_person_detail=True,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.PROCONNECT_ENRICHMENT.value,
            message="Movement leverage enriched in ProConnect.",
            status="complete",
            visible_row_count=len(ranked_rows),
            run_id=reviewed_run_id,
        )
        logger.info(
            "Movement ProConnect enrichment summary run_id=%s rows=%s matched=%s top=%s",
            reviewed_run_id,
            len(ranked_rows),
            len([item for item in ranked_rows if item.get("person_match_status") == "matched"]),
            [
                {
                    "person": getattr(item.get("movement"), "person_name", ""),
                    "match_status": item.get("person_match_status"),
                    "known": bool(item.get("known")),
                    "worked_with": bool(item.get("worked_with")),
                    "projects": int(item.get("project_count") or 0),
                    "wins": int(item.get("win_count") or 0),
                    "owner": item.get("relationship_owner"),
                }
                for item in ranked_rows[:5]
            ],
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.VALIDATING_CREDENTIALS.value,
            message="Validating credentials for prioritized movers.",
            status="in_progress",
            run_id=reviewed_run_id,
        )
        derived_opportunities = self.opportunity_deriver.derive(
            request=request,
            preflight=preflight,
            signal_evidence=signal_evidence,
            ranked_rows=ranked_rows,
            actioning_context=actioning_context,
            max_opportunities=3,
        )
        ranked_rows = self._attach_opportunity_ids(ranked_rows, derived_opportunities)
        credentials_lookup = await self.credentials_lookup_runner.run(
            [item.opportunity for item in derived_opportunities],
            sector=trigger.sector,
            max_opportunities=3,
        )
        credential_packets = self.credentials_service.build_proof_packets(
            derived_opportunities,
            credentials_lookup.results,
        )
        actioning_context = self._attach_named_mover_credential_proof(
            actioning_context,
            derived_opportunities,
            credential_packets,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.VALIDATING_CREDENTIALS.value,
            message="Credentials validation complete.",
            status="complete",
            matched_count=sum(
                1 for packet in credential_packets.values() if packet.lookup_status == "Matched"
            ),
            run_id=reviewed_run_id,
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.ASSEMBLING_BRIEF.value,
            message="Assembling movement brief.",
            status="in_progress",
            run_id=reviewed_run_id,
        )
        movement_brief = self.assembler.assemble(
            request=request,
            preflight=preflight,
            actioning_context=actioning_context,
            trigger=trigger,
            signal_evidence=signal_evidence,
            movement_rows=movement_rows,
            ranked_rows=ranked_rows,
            deep_enriched_rows=deep_enriched_rows,
            credential_packets=credential_packets,
            deep_research_summary=deep_research_summary,
            derived_opportunities=derived_opportunities,
            credentials_lookup=credentials_lookup,
        )
        movement_brief = await self._apply_brief_synthesis(
            movement_brief,
            request=request,
            preflight=preflight,
            signal_evidence=signal_evidence,
            deep_research_summary=deep_research_summary,
            run_id=reviewed_run_id,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.ASSEMBLING_BRIEF.value,
            message="Movement brief assembled.",
            status="complete",
            run_id=reviewed_run_id,
        )

        return MovementBriefRunResult(
            request=request,
            preflight=preflight,
            actioning_context=dict(actioning_context or {}),
            prompt_package=prompt_package,
            movement_brief=movement_brief,
            deep_research_markdown=deep_research_markdown,
            signal_evidence=signal_evidence,
            movement_rows=movement_rows,
            light_enriched_rows=light_enriched_rows,
            ranked_rows=ranked_rows,
            deep_enriched_rows=deep_enriched_rows,
            derived_opportunities=derived_opportunities,
            credential_packets=credential_packets,
            credentials_lookup=credentials_lookup,
            signal_diagnostics=signal_diagnostics,
            movement_diagnostics=movement_diagnostics,
        )

    async def run_from_reviewed_context(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        actioning_context: Optional[Dict[str, Any]],
        prompt_package: MovementPromptPackage,
        run_id: str,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> MovementBriefRunResult:
        reviewed = ReviewedMovementRunInput(
            run_id=run_id,
            request=request,
            preflight=preflight,
            actioning_context=dict(actioning_context or {}),
            prompt_package=prompt_package,
        )
        return await self.run(
            reviewed.request,
            progress_cb=progress_cb,
            reviewed_preflight=reviewed.preflight,
            reviewed_actioning_context=reviewed.actioning_context,
            reviewed_prompt_package=reviewed.prompt_package,
            reviewed_run_id=reviewed.run_id,
        )

    def _attach_opportunity_ids(
        self,
        ranked_rows: List[Dict[str, Any]],
        derived_opportunities: List[Any],
    ) -> List[Dict[str, Any]]:
        derived_by_key: Dict[tuple[str, str, str], Any] = {}
        fallback_by_person_company: Dict[tuple[str, str], Any] = {}
        for derived in derived_opportunities:
            if str(getattr(derived, "source_type", "") or "").strip() == "named_mover":
                continue
            opportunity = getattr(derived, "opportunity", None)
            search_context = getattr(opportunity, "credential_search_context", None)
            key = (
                self._normalized_text(getattr(derived, "person_name", "") or "").lower(),
                self._normalized_text(getattr(opportunity, "agency", "") or "").lower(),
                self._normalized_text(
                    getattr(search_context, "person_title", None)
                    or self._extract_role_from_title(getattr(opportunity, "title", "") or "")
                ).lower(),
            )
            if all(key):
                derived_by_key[key] = derived
            fallback_key = (
                self._normalized_text(getattr(derived, "person_name", "") or "").lower(),
                self._normalized_text(getattr(opportunity, "agency", "") or "").lower(),
            )
            if all(fallback_key) and fallback_key not in fallback_by_person_company:
                fallback_by_person_company[fallback_key] = derived

        normalized: List[Dict[str, Any]] = []
        for row in ranked_rows:
            updated = dict(row)
            movement = updated.get("movement")
            key = (
                self._normalized_text(getattr(movement, "person_name", "") or "").lower(),
                self._normalized_text(getattr(movement, "target_company", "") or "").lower(),
                self._normalized_text(getattr(movement, "new_role", "") or "").lower(),
            )
            derived = derived_by_key.get(key)
            if derived is None:
                fallback_key = key[:2]
                derived = fallback_by_person_company.get(fallback_key)
            if derived is not None:
                opportunity_id = str(getattr(derived, "opportunity_id", "") or "").strip()
                if opportunity_id:
                    updated["opportunity_id"] = opportunity_id
                    updated["opportunity_title"] = getattr(getattr(derived, "opportunity", None), "title", "")
            normalized.append(updated)
        return normalized

    def _attach_named_mover_credential_proof(
        self,
        actioning_context: Dict[str, Any],
        derived_opportunities: List[Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> Dict[str, Any]:
        updated_context = dict(actioning_context or {})
        named_packet: Optional[MovementCredentialsProof] = None
        for derived in derived_opportunities:
            if str(getattr(derived, "source_type", "") or "").strip() != "named_mover":
                continue
            opportunity_id = str(getattr(derived, "opportunity_id", "") or "").strip()
            if not opportunity_id:
                continue
            named_packet = credential_packets.get(opportunity_id)
            if named_packet is not None:
                break

        if named_packet is None:
            updated_context.pop("named_mover_credentials_proof", None)
            return updated_context

        if hasattr(named_packet, "model_dump"):
            updated_context["named_mover_credentials_proof"] = named_packet.model_dump()
        elif hasattr(named_packet, "dict"):
            updated_context["named_mover_credentials_proof"] = named_packet.dict()
        else:
            updated_context["named_mover_credentials_proof"] = {
                "lookup_status": getattr(named_packet, "lookup_status", "No Match"),
                "summary": getattr(named_packet, "summary", ""),
                "matched_credentials": list(getattr(named_packet, "matched_credentials", []) or []),
            }
        return updated_context

    async def _prepare_move_context(
        self,
        request: MovementBriefRequest,
        *,
        progress_cb: Optional[ProgressCallback],
        prompt_override: Optional[str] = None,
    ) -> tuple[Any, TransitionPreflight, Dict[str, Any], MovementPromptPackage]:
        await self._emit(
            progress_cb,
            stage=WorkflowStage.RESOLVING_NAMED_MOVE.value,
            message="Resolving named move context.",
            status="in_progress",
        )
        transition_request = build_transition_request_for_movement(request)
        service = self._get_transition_service()
        transition_case: Optional[Dict[str, Any]] = None
        actioning_context: Dict[str, Any] = {}

        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUILDING_RELATIONSHIP_CONTEXT.value,
            message="Building relationship context from ProConnect.",
            status="in_progress",
        )
        load_transition_case = getattr(service, "load_transition_case", None)
        build_actioning_context = getattr(service, "build_actioning_context", None)
        if callable(load_transition_case):
            transition_case = await asyncio.to_thread(load_transition_case, transition_request)
            preflight = await asyncio.to_thread(
                service.build_preflight,
                transition_request,
                transition_case=transition_case,
            )
            if callable(build_actioning_context):
                actioning_context = await asyncio.to_thread(
                    build_actioning_context,
                    transition_request,
                    transition_case=transition_case,
                )
        else:
            preflight = await asyncio.to_thread(service.build_preflight, transition_request)
            if callable(build_actioning_context):
                actioning_context = await asyncio.to_thread(build_actioning_context, transition_request)
        logger.info(
            "Movement preflight resolved person=%s source_resolved=%s destination_resolved=%s match_status=%s warm_path=%s source_prior_work=%s destination_prior_work=%s source_key_buyers=%s destination_key_buyers=%s",
            request.person_name,
            preflight.from_account.resolved,
            preflight.to_account.resolved,
            preflight.person_resolution.match_status,
            preflight.quick_indicators.warm_intro_path_available,
            preflight.quick_indicators.source_worked_before,
            preflight.quick_indicators.destination_worked_before,
            preflight.quick_indicators.source_key_buyer_count,
            preflight.quick_indicators.destination_key_buyer_count,
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUILDING_RELATIONSHIP_CONTEXT.value,
            message="Relationship context built from ProConnect.",
            status="complete",
            person_match_status=preflight.person_resolution.match_status,
            warm_intro_path_available=preflight.quick_indicators.warm_intro_path_available,
            source_key_buyer_count=preflight.quick_indicators.source_key_buyer_count,
            destination_key_buyer_count=preflight.quick_indicators.destination_key_buyer_count,
        )

        prompt_package = self.prompt_builder.build(request, preflight)
        if prompt_override:
            prompt_package = MovementPromptPackage(
                industry_key=prompt_package.industry_key,
                system_prompt=prompt_package.system_prompt,
                user_prompt=prompt_override,
            )
        logger.info(
            "Movement prompt package ready industry=%s prompt_overridden=%s user_prompt_chars=%s",
            prompt_package.industry_key,
            bool(prompt_override),
            len(prompt_package.user_prompt),
        )
        await self._emit(
            progress_cb,
            stage=WorkflowStage.GENERATING_RESEARCH_PLAN.value,
            message="Generated research plan from validated move context.",
            status="complete",
            industry_key=prompt_package.industry_key,
            prompt_overridden=bool(prompt_override),
        )
        return transition_request, preflight, dict(actioning_context or {}), prompt_package

    async def _run_deep_research(
        self,
        prompt_package: MovementPromptPackage,
        progress_cb: Optional[ProgressCallback],
    ) -> Dict[str, Any]:
        runner = self._get_deep_research_runner()
        kwargs = self._build_runner_kwargs(
            runner,
            industry=prompt_package.industry_key,
            progress_callback=self._make_deep_research_progress_wrapper(progress_cb),
            instructions_override=prompt_package.system_prompt,
        )
        logger.info(
            "Dispatching Deep Research query industry=%s prompt_chars=%s",
            prompt_package.industry_key,
            len(prompt_package.user_prompt),
        )
        response = await runner(prompt_package.user_prompt, **kwargs)
        return response if isinstance(response, dict) else {"summary": str(response or "")}

    def _get_deep_research_runner(self) -> DeepResearchRunner:
        if self.deep_research_runner is None:
            from tools.orchestrators import run_deep_research

            self.deep_research_runner = run_deep_research
        return self.deep_research_runner

    def _get_transition_service(self) -> ProConnectTransitionService:
        if self.transition_service is None:
            return self._build_live_transition_service()
        if self._owns_transition_service:
            return self._build_live_transition_service()
        return self.transition_service

    def _get_proconnect_service(self) -> ProConnectMovementService:
        if self.proconnect_service is None:
            return self._build_live_movement_service()
        if self._owns_proconnect_service:
            return self._build_live_movement_service()
        return self.proconnect_service

    async def _apply_brief_synthesis(
        self,
        brief: MovementBrief,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        signal_evidence: List[SignalEvidence],
        deep_research_summary: str,
        run_id: Optional[str],
    ) -> MovementBrief:
        if not self.brief_synthesizer:
            return brief
        try:
            synthesis_input = self.brief_synthesizer.build_input(
                run_id=run_id,
                request=request,
                preflight=preflight,
                brief=brief,
                signal_evidence=signal_evidence,
                deep_research_summary=deep_research_summary,
            )
            synthesis = await self.brief_synthesizer.synthesize(synthesis_input)
            if synthesis:
                apply_synthesis = getattr(self.assembler, "apply_synthesis", None)
                if callable(apply_synthesis):
                    return apply_synthesis(brief, synthesis)
                updates = {
                    "executive_summary": getattr(synthesis, "move_summary", "") or brief.executive_summary,
                    "signal_summary": list(getattr(synthesis, "signal_summary", []) or []) or brief.signal_summary,
                    "takeaway": getattr(synthesis, "takeaway", "") or brief.takeaway,
                }
                if hasattr(brief, "model_copy"):
                    return brief.model_copy(update=updates)
                return brief.copy(update=updates)  # pragma: no cover
        except Exception as exc:
            logger.warning("Movement brief synthesis overlay failed: %s", exc)
        return brief

    def _refresh_named_mover_enrichment(
        self,
        enriched_rows: List[Dict[str, Any]],
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        actioning_context: Optional[Dict[str, Any]],
        proconnect_service: ProConnectMovementService,
        include_person_detail: bool,
    ) -> List[Dict[str, Any]]:
        enrich_row = getattr(proconnect_service, "enrich_movement", None)

        named_people = {
            self._normalize_person_name(request.person_name),
            self._normalize_person_name(preflight.person_resolution.matched_name or ""),
        }
        named_people.discard("")
        if not named_people:
            return enriched_rows

        company_hints = self._named_mover_company_hints(request=request, preflight=preflight)
        if not company_hints:
            return enriched_rows
        canonical = self._build_named_mover_actioning_enrichment(
            request=request,
            preflight=preflight,
            actioning_context=actioning_context or {},
            include_person_detail=include_person_detail,
        )

        refreshed: List[Dict[str, Any]] = []
        for entry in enriched_rows:
            movement = entry.get("movement")
            person_name = self._normalize_person_name(getattr(movement, "person_name", "") or "")
            if not movement or person_name not in named_people:
                refreshed.append(entry)
                continue

            generic_enrichment: Dict[str, Any] = {}
            if callable(enrich_row):
                for company_hint in company_hints:
                    candidate = enrich_row(
                        movement,
                        company_hint=company_hint,
                        include_person_detail=include_person_detail,
                    )
                    if self._has_enrichment_signal(candidate):
                        generic_enrichment = candidate
                        break

            refreshed.append(
                self._merge_enrichment(
                    entry,
                    generic_enrichment,
                    canonical=canonical,
                    preflight=preflight,
                )
            )

        return refreshed

    def _log_named_mover_context(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        actioning_context: Dict[str, Any],
        run_id: Optional[str],
    ) -> None:
        person_profile = actioning_context.get("person_profile") if isinstance(actioning_context, dict) else {}
        person_profile = person_profile if isinstance(person_profile, dict) else {}
        matched_person = person_profile.get("matched_person") if isinstance(person_profile.get("matched_person"), dict) else {}
        from_context = actioning_context.get("from_company_context") if isinstance(actioning_context, dict) else {}
        from_context = from_context if isinstance(from_context, dict) else {}
        top_key_buyers = from_context.get("top_key_buyers") if isinstance(from_context.get("top_key_buyers"), list) else []
        matched_key_buyer = next(
            (
                item for item in top_key_buyers
                if isinstance(item, dict)
                and self._normalize_person_name(item.get("name") or "") == self._normalize_person_name(request.person_name)
            ),
            {},
        )
        logger.info(
            "Named mover context run_id=%s requested=%s matched=%s source=%s scope=%s direct=%s profile_projects=%s profile_wins=%s matched_projects=%s matched_wins=%s matched_project_list=%s matched_win_list=%s matched_project_names=%s matched_win_names=%s key_buyer_projects=%s key_buyer_wins=%s relationship_owner=%s evidence_basis=%s",
            run_id,
            request.person_name,
            preflight.person_resolution.matched_name,
            preflight.person_resolution.match_source,
            preflight.person_resolution.match_scope,
            bool(person_profile.get("direct_person_evidence")),
            person_profile.get("project_count"),
            person_profile.get("win_count"),
            matched_person.get("project_count"),
            matched_person.get("win_count"),
            len(matched_person.get("projects") or []) if isinstance(matched_person.get("projects"), list) else 0,
            len(matched_person.get("closeWonOpps") or []) if isinstance(matched_person.get("closeWonOpps"), list) else 0,
            [self._normalized_text(item.get("name")) for item in self._as_list(matched_person.get("projects"))[:5]],
            [self._normalized_text(item.get("name")) for item in self._as_list(matched_person.get("closeWonOpps"))[:5]],
            matched_key_buyer.get("projectCount") or matched_key_buyer.get("project_count") or matched_key_buyer.get("numberOfProjects"),
            matched_key_buyer.get("winCount") or matched_key_buyer.get("wins_5y") or matched_key_buyer.get("numberOfWins"),
            person_profile.get("relationship_owner") or matched_person.get("relationship_owner"),
            person_profile.get("evidence_basis"),
        )

    def _build_named_mover_actioning_enrichment(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        actioning_context: Dict[str, Any],
        include_person_detail: bool,
    ) -> Dict[str, Any]:
        person_profile = self._as_dict(actioning_context.get("person_profile"))
        from_context = self._as_dict(actioning_context.get("from_company_context"))
        to_context = self._as_dict(actioning_context.get("to_company_context"))
        matched_person = self._as_dict(person_profile.get("matched_person"))
        match_scope = self._normalized_text(
            preflight.person_resolution.match_scope
            or matched_person.get("company_scope")
        )

        scope_context = from_context if match_scope == "from" else to_context if match_scope == "to" else {}
        account_team = self._as_dict(scope_context.get("account_team"))
        relationship_network = self._as_dict(scope_context.get("relationship_network"))
        connected_colleagues = self._as_list(
            self._as_dict(relationship_network.get("connected_colleagues")).get("items")
        )
        alumni = self._as_list(
            self._as_dict(relationship_network.get("protiviti_alumni")).get("items")
        )

        project_count = self._first_positive_int(
            person_profile.get("project_count"),
            matched_person.get("project_count"),
            matched_person.get("projectCount"),
            len(self._as_list(matched_person.get("projects"))),
        )
        win_count = self._first_positive_int(
            person_profile.get("win_count"),
            matched_person.get("win_count"),
            matched_person.get("winCount"),
            len(self._as_list(matched_person.get("closeWonOpps"))),
        )
        relationship_owner = self._first_non_empty_text(
            person_profile.get("relationship_owner"),
            matched_person.get("relationship_owner"),
            matched_person.get("relationshipOwner"),
            self._as_dict(account_team.get("account_executive")).get("name"),
            self._as_dict(account_team.get("account_mdd")).get("name"),
            self._as_dict(account_team.get("account_pmo")).get("name"),
        )

        person_match_status = self._normalized_text(
            preflight.person_resolution.match_status
            or person_profile.get("match_status")
            or matched_person.get("match_status")
        ).lower()
        exact_proconnect_match = person_match_status == "matched"

        known = exact_proconnect_match
        worked_with = bool(project_count > 0 or win_count > 0)
        person_match_status = person_match_status or None
        person_detail: Dict[str, Any] = {}
        if include_person_detail:
            person_detail = {
                "name": preflight.person_resolution.matched_name or request.person_name,
                "title": preflight.person_resolution.matched_title,
                "matched_name": preflight.person_resolution.matched_name or request.person_name,
                "matched_title": preflight.person_resolution.matched_title,
                "match_scope": match_scope or None,
                "match_source": preflight.person_resolution.match_source,
                "linked_account_id": preflight.person_resolution.linked_account_id,
                "direct_person_evidence": bool(person_profile.get("direct_person_evidence")),
                "claim_policy_note": self._normalized_text(person_profile.get("claim_policy_note")) or None,
                "relationship_owner": relationship_owner or None,
                "project_count": project_count,
                "win_count": win_count,
                "known": known,
                "worked_with": worked_with,
                "warm_intro_path_available": preflight.quick_indicators.warm_intro_path_available,
                "source_worked_before": preflight.quick_indicators.source_worked_before,
                "destination_worked_before": preflight.quick_indicators.destination_worked_before,
                "connected_colleague_count": len(connected_colleagues),
                "protiviti_alumni_count": len(alumni),
                "candidate_suggestions": [
                    self._normalized_text(item.get("name"))
                    for item in self._as_list(person_profile.get("candidate_suggestions"))[:3]
                    if isinstance(item, dict) and self._normalized_text(item.get("name"))
                ],
            }
            person_detail = {
                key: value
                for key, value in person_detail.items()
                if value not in (None, "", [], {})
            }

        enrichment = {
            "known": known,
            "worked_with": worked_with,
            "project_count": project_count,
            "win_count": win_count,
            "relationship_owner": relationship_owner or None,
            "person_match_status": person_match_status,
            "person_detail": person_detail,
        }
        if not self._has_enrichment_signal(enrichment):
            return {}
        return enrichment

    def _named_mover_company_hints(
        self,
        *,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
    ) -> List[str]:
        match_scope = str(preflight.person_resolution.match_scope or "").strip().lower()
        ordered_candidates: List[Optional[str]]
        if match_scope == "from":
            ordered_candidates = [
                preflight.from_account.company_name,
                request.from_company,
                preflight.to_account.company_name,
                request.to_company,
            ]
        elif match_scope == "to":
            ordered_candidates = [
                preflight.to_account.company_name,
                request.to_company,
                preflight.from_account.company_name,
                request.from_company,
            ]
        else:
            ordered_candidates = [
                preflight.from_account.company_name,
                request.from_company,
                preflight.to_account.company_name,
                request.to_company,
            ]

        hints: List[str] = []
        seen: set[str] = set()
        for candidate in ordered_candidates:
            normalized = " ".join(str(candidate or "").split()).strip()
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            seen.add(key)
            hints.append(normalized)
        return hints

    def _merge_enrichment(
        self,
        original: Dict[str, Any],
        replacement: Dict[str, Any],
        *,
        canonical: Optional[Dict[str, Any]] = None,
        preflight: TransitionPreflight,
    ) -> Dict[str, Any]:
        merged = dict(original)
        fallback_known = preflight.person_resolution.match_status == "matched"
        fallback_worked_with = False

        for candidate in (replacement or {}, canonical or {}):
            if not candidate:
                continue
            merged["known"] = bool(merged.get("known")) or bool(candidate.get("known"))
            merged["worked_with"] = bool(merged.get("worked_with")) or bool(candidate.get("worked_with"))
            merged["project_count"] = max(
                int(merged.get("project_count") or 0),
                int(candidate.get("project_count") or 0),
            )
            merged["win_count"] = max(
                int(merged.get("win_count") or 0),
                int(candidate.get("win_count") or 0),
            )
            relationship_owner = self._normalized_text(candidate.get("relationship_owner"))
            if relationship_owner and (candidate is canonical or not self._normalized_text(merged.get("relationship_owner"))):
                merged["relationship_owner"] = relationship_owner
            candidate_status = self._normalized_text(candidate.get("person_match_status")).lower()
            merged_status = self._normalized_text(merged.get("person_match_status")).lower()
            if candidate_status and (
                candidate_status == "matched"
                or merged_status in {"", "no_match", "not_found"}
                or candidate is canonical
            ):
                merged["person_match_status"] = candidate_status

            detail = self._as_dict(merged.get("person_detail"))
            for key, value in self._as_dict(candidate.get("person_detail")).items():
                if value in (None, "", [], {}):
                    continue
                if candidate is canonical or key not in detail or detail.get(key) in (None, "", [], {}):
                    detail[key] = value
            if detail:
                merged["person_detail"] = detail

        if merged.get("person_match_status") in {None, "", "no_match"} and preflight.person_resolution.match_status == "matched":
            merged["person_match_status"] = "matched"
        if not merged.get("known") and fallback_known:
            merged["known"] = True
        if not merged.get("worked_with") and fallback_worked_with:
            merged["worked_with"] = True
        return merged

    @staticmethod
    def _has_enrichment_signal(candidate: Dict[str, Any]) -> bool:
        return bool(
            candidate.get("known")
            or candidate.get("worked_with")
            or int(candidate.get("project_count") or 0) > 0
            or int(candidate.get("win_count") or 0) > 0
            or str(candidate.get("relationship_owner") or "").strip()
            or str(candidate.get("person_match_status") or "").strip().lower() == "matched"
            or bool(candidate.get("person_detail"))
        )

    @staticmethod
    def _normalize_person_name(value: str) -> str:
        return " ".join(str(value or "").lower().split()).strip()

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _normalized_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @staticmethod
    def _extract_role_from_title(value: Any) -> str:
        title = " ".join(str(value or "").split()).strip()
        if not title.endswith("Advisory Play"):
            return title
        core = title[: -len("Advisory Play")].strip()
        parts = core.split(" ", 1)
        return parts[1].strip() if len(parts) == 2 else core

    def _first_non_empty_text(self, *values: Any) -> str:
        for value in values:
            normalized = self._normalized_text(value)
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _first_positive_int(*values: Any) -> int:
        for value in values:
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                if value > 0:
                    return value
                continue
            text = str(value or "").strip()
            if not text:
                continue
            try:
                parsed = int(float(text))
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return 0

    def _build_live_transition_service(self) -> ProConnectTransitionService:
        token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
        base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
        fallback_paths = [
            Path.cwd() / "token.txt",
            SCRIPT_DIR / "token.txt",
        ]
        token, _ = resolve_runtime_bearer_token(token_file=token_file, fallback_paths=fallback_paths)
        client = ProConnectClient(base_url=base_url, bearer_token=token)
        return ProConnectTransitionService(client=client)

    def _build_live_movement_service(self) -> ProConnectMovementService:
        token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
        base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
        fallback_paths = [
            Path.cwd() / "token.txt",
            SCRIPT_DIR / "token.txt",
        ]
        token, _ = resolve_runtime_bearer_token(token_file=token_file, fallback_paths=fallback_paths)
        client = ProConnectClient(base_url=base_url, bearer_token=token)
        return ProConnectMovementService(client=client)

    @staticmethod
    def _build_runner_kwargs(runner: DeepResearchRunner, **candidate_kwargs: Any) -> Dict[str, Any]:
        signature = inspect.signature(runner)
        params = signature.parameters
        accepts_varkw = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        kwargs: Dict[str, Any] = {}
        for key, value in candidate_kwargs.items():
            if key in params or accepts_varkw:
                kwargs[key] = value
        return kwargs

    def _make_deep_research_progress_wrapper(
        self,
        progress_cb: Optional[ProgressCallback],
    ) -> Callable[[str, Dict[str, Any]], Awaitable[None]]:
        async def _wrapped(text: str, metadata: Dict[str, Any]) -> None:
            if progress_cb is None:
                return

            event = {
                "stage": WorkflowStage.RUNNING_DEEP_RESEARCH.value,
                "message": text or "Deep Research activity update.",
                "status": str(metadata.get("status") or "in_progress"),
                "citation_count": metadata.get("citation_count", 0),
                "poll_count": metadata.get("poll_count", 0),
                "activity_log": metadata.get("activity_log", []),
                "latest_text": metadata.get("latest_text") or text or "",
                "metadata": dict(metadata),
            }
            result = progress_cb(event)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]

        return _wrapped

    @staticmethod
    async def _notify(progress_cb: Optional[ProgressCallback], message: str) -> None:
        if progress_cb is None:
            return
        result = progress_cb(message)
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]

    @staticmethod
    async def _emit(progress_cb: Optional[ProgressCallback], **event: Any) -> None:
        if progress_cb is None:
            return
        result = progress_cb(event)
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]

    @staticmethod
    def _extract_summary(response: Optional[Dict[str, Any]], markdown: str) -> str:
        if isinstance(response, dict):
            summary = str(response.get("summary") or "").strip()
            if summary:
                return summary

        for line in (markdown or "").splitlines():
            text = line.strip().lstrip("#").strip()
            if text:
                return text
        return ""

    @classmethod
    def _prime_proconnect_accounts(
        cls,
        proconnect_service: Any,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
    ) -> None:
        prime_account = getattr(proconnect_service, "prime_company_account", None)
        if not callable(prime_account):
            return

        for account_id, aliases in (
            (
                preflight.to_account.account_id,
                cls._account_aliases(request.to_company, preflight.to_account.company_name),
            ),
            (
                preflight.from_account.account_id,
                cls._account_aliases(request.from_company, preflight.from_account.company_name),
            ),
        ):
            account_id_text = str(account_id or "").strip()
            if not account_id_text or not aliases:
                continue
            prime_account(account_id=account_id_text, company_names=aliases)

    @staticmethod
    def _target_company_aliases(
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
    ) -> List[str]:
        aliases: List[str] = []
        for candidate in (
            request.to_company,
            preflight.to_account.company_name,
        ):
            text = str(candidate or "").strip()
            if text and text not in aliases:
                aliases.append(text)
        return aliases

    @staticmethod
    def _account_aliases(*candidates: Optional[str]) -> List[str]:
        aliases: List[str] = []
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text and text not in aliases:
                aliases.append(text)
        return aliases
