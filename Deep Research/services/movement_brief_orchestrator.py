"""
Orchestration for the named-move People Movement Brief workflow.
"""
from __future__ import annotations

import inspect
import sys
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
from services.proconnect_movement_service import ProConnectMovementService
from services.proconnect_transition_service import ProConnectTransitionService
from services.signal_registry_service import get_signal_registry_service


SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from proconnect_client import DEFAULT_BASE_URL, ProConnectClient, resolve_bearer_token  # noqa: E402


ProgressCallback = Callable[[Any], Any]
DeepResearchRunner = Callable[..., Awaitable[Dict[str, Any]]]


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
        self.prompt_builder = prompt_builder or MovementPromptBuilder()
        self.fs_signal_evidence_digestor = fs_signal_evidence_digestor or FSSignalEvidenceDigestor()
        self.movement_digestor = movement_digestor or FSMovementDigestor()
        self.proconnect_service = proconnect_service
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
    ) -> MovementBriefRunResult:
        """Run the full named-move movement-led pipeline."""
        trigger = build_movement_trigger(request)
        _, preflight, prompt_package = await self._prepare_move_context(
            request,
            progress_cb=progress_cb,
            prompt_override=prompt_override,
        )

        await self._notify(progress_cb, "Running Deep Research...")
        structured_evidence_map: Dict[str, Any] = {}
        if deep_research_output is None:
            if deep_research_response is not None:
                deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                structured_evidence_map = build_structured_evidence_map(deep_research_response)
            else:
                deep_research_response = await self._run_deep_research(prompt_package, progress_cb)
                deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                structured_evidence_map = build_structured_evidence_map(deep_research_response)

        deep_research_markdown = deep_research_output or ""
        deep_research_summary = self._extract_summary(deep_research_response, deep_research_markdown)

        await self._notify(progress_cb, "Normalizing financial-services signal evidence...")
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

        await self._notify(progress_cb, "Extracting movement rows...")
        movement_rows, movement_diagnostics = await self.movement_digestor.digest(
            trigger=trigger,
            deep_research_markdown=deep_research_markdown,
        )

        await self._notify(progress_cb, "Matching movement leverage in ProConnect...")
        proconnect_service = self._get_proconnect_service()
        light_enriched_rows = proconnect_service.light_enrich_movements(movement_rows)
        ranked_rows = self.ranker.rank(light_enriched_rows, max_rows=10)

        await self._notify(progress_cb, "Deep-enriching top movement rows...")
        ranked_movements = [row["movement"] for row in ranked_rows]
        deep_enriched_rows = proconnect_service.deep_enrich_movements(ranked_movements, max_rows=10)

        await self._notify(progress_cb, "Validating credentials for prioritized movers...")
        derived_opportunities = self.opportunity_deriver.derive(
            request=request,
            preflight=preflight,
            signal_evidence=signal_evidence,
            ranked_rows=ranked_rows,
            max_opportunities=3,
        )
        credentials_lookup = await self.credentials_lookup_runner.run(
            [item.opportunity for item in derived_opportunities],
            sector=trigger.sector,
            max_opportunities=3,
        )
        credential_packets = self.credentials_service.build_proof_packets(
            derived_opportunities,
            credentials_lookup.results,
        )

        await self._notify(progress_cb, "Assembling movement brief...")
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

    async def _prepare_move_context(
        self,
        request: MovementBriefRequest,
        *,
        progress_cb: Optional[ProgressCallback],
        prompt_override: Optional[str] = None,
    ) -> tuple[Any, TransitionPreflight, MovementPromptPackage]:
        await self._emit(
            progress_cb,
            stage="resolving_named_move",
            message="Resolving named move context.",
            status="in_progress",
        )
        transition_request = build_transition_request_for_movement(request)
        service = self._get_transition_service()

        await self._emit(
            progress_cb,
            stage="building_relationship_context",
            message="Building relationship context from ProConnect.",
            status="in_progress",
        )
        preflight = service.build_preflight(transition_request)
        await self._emit(
            progress_cb,
            stage="building_relationship_context",
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
        await self._emit(
            progress_cb,
            stage="generating_research_plan",
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
        response = await runner(prompt_package.user_prompt, **kwargs)
        return response if isinstance(response, dict) else {"summary": str(response or "")}

    def _get_deep_research_runner(self) -> DeepResearchRunner:
        if self.deep_research_runner is None:
            from tools.orchestrators import run_deep_research

            self.deep_research_runner = run_deep_research
        return self.deep_research_runner

    def _get_transition_service(self) -> ProConnectTransitionService:
        if self.transition_service is None:
            token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
            base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
            token, _ = resolve_bearer_token(None, token_file)
            client = ProConnectClient(base_url=base_url, bearer_token=token)
            self.transition_service = ProConnectTransitionService(client=client)
        return self.transition_service

    def _get_proconnect_service(self) -> ProConnectMovementService:
        if self.proconnect_service is None:
            token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
            base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
            token, _ = resolve_bearer_token(None, token_file)
            client = ProConnectClient(base_url=base_url, bearer_token=token)
            self.proconnect_service = ProConnectMovementService(client=client)
        return self.proconnect_service

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
                "stage": "running_deep_research",
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
