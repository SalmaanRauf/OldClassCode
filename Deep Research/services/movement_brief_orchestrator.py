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
    prompt_package: MovementPromptPackage


@dataclass(frozen=True)
class MovementBriefRunResult:
    """End-to-end artifacts for a people movement brief run."""

    request: MovementBriefRequest
    preflight: TransitionPreflight
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
        self.deep_research_runner = deep_research_runner

    async def build_preflight(
        self,
        request: MovementBriefRequest,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> MovementPreflightResult:
        _, preflight, prompt_package = await self._prepare_move_context(
            request,
            progress_cb=progress_cb,
        )
        return MovementPreflightResult(preflight=preflight, prompt_package=prompt_package)

    async def run(
        self,
        request: MovementBriefRequest,
        *,
        deep_research_output: Optional[str] = None,
        deep_research_response: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[ProgressCallback] = None,
        prompt_override: Optional[str] = None,
        reviewed_preflight: Optional[TransitionPreflight] = None,
        reviewed_prompt_package: Optional[MovementPromptPackage] = None,
        reviewed_run_id: Optional[str] = None,
    ) -> MovementBriefRunResult:
        """Run the full named-move movement-led pipeline."""
        if reviewed_preflight and reviewed_prompt_package:
            preflight = reviewed_preflight
            prompt_package = reviewed_prompt_package
            logger.info(
                "Movement research using reviewed context run_id=%s person=%s destination=%s",
                reviewed_run_id,
                request.person_name,
                request.to_company,
            )
        else:
            _, preflight, prompt_package = await self._prepare_move_context(
                request,
                progress_cb=progress_cb,
                prompt_override=prompt_override,
            )
            logger.info(
                "Movement research rebuilt context person=%s destination=%s",
                request.person_name,
                request.to_company,
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
        light_enriched_rows = proconnect_service.light_enrich_movements(movement_rows)
        ranked_rows = self.ranker.rank(light_enriched_rows, max_rows=10)

        ranked_movements = [row["movement"] for row in ranked_rows]
        deep_enriched_rows = proconnect_service.deep_enrich_movements(ranked_movements, max_rows=10)
        await self._emit(
            progress_cb,
            stage=WorkflowStage.PROCONNECT_ENRICHMENT.value,
            message="Movement leverage enriched in ProConnect.",
            status="complete",
            visible_row_count=len(ranked_rows[:10]),
            run_id=reviewed_run_id,
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
        prompt_package: MovementPromptPackage,
        run_id: str,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> MovementBriefRunResult:
        reviewed = ReviewedMovementRunInput(
            run_id=run_id,
            request=request,
            preflight=preflight,
            prompt_package=prompt_package,
        )
        return await self.run(
            reviewed.request,
            progress_cb=progress_cb,
            reviewed_preflight=reviewed.preflight,
            reviewed_prompt_package=reviewed.prompt_package,
            reviewed_run_id=reviewed.run_id,
        )

    def _attach_opportunity_ids(
        self,
        ranked_rows: List[Dict[str, Any]],
        derived_opportunities: List[Any],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, row in enumerate(ranked_rows):
            updated = dict(row)
            if index < len(derived_opportunities):
                derived = derived_opportunities[index]
                opportunity_id = str(getattr(derived, "opportunity_id", "") or "").strip()
                if opportunity_id:
                    updated["opportunity_id"] = opportunity_id
                    updated["opportunity_title"] = getattr(getattr(derived, "opportunity", None), "title", "")
            normalized.append(updated)
        return normalized

    async def _prepare_move_context(
        self,
        request: MovementBriefRequest,
        *,
        progress_cb: Optional[ProgressCallback],
        prompt_override: Optional[str] = None,
    ) -> tuple[Any, TransitionPreflight, MovementPromptPackage]:
        await self._emit(
            progress_cb,
            stage=WorkflowStage.RESOLVING_NAMED_MOVE.value,
            message="Resolving named move context.",
            status="in_progress",
        )
        transition_request = build_transition_request_for_movement(request)
        service = self._get_transition_service()

        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUILDING_RELATIONSHIP_CONTEXT.value,
            message="Building relationship context from ProConnect.",
            status="in_progress",
        )
        preflight = await asyncio.to_thread(service.build_preflight, transition_request)
        logger.info(
            "Movement preflight resolved person=%s source_resolved=%s destination_resolved=%s match_status=%s",
            request.person_name,
            preflight.from_account.resolved,
            preflight.to_account.resolved,
            preflight.person_resolution.match_status,
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
        return transition_request, preflight, prompt_package

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
