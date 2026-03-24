"""
Transition Playbook orchestration.

Owns the transition-specific workflow:
1. ProConnect preflight
2. Research-plan composition
3. Deep Research
4. BD orchestration (credentials + synthesis)
5. ProConnect actioning context
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config.config import AppConfig
from models.bd_schemas import MDReport
from models.transition_schemas import TransitionPreflight, TransitionRequest
from services.bd_orchestrator import BDOrchestrator
from services.bd_trigger_context import build_trigger_for_bd_enrichment
from services.deep_research_formatter import (
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)
from services.proconnect_auth import resolve_runtime_bearer_token
from services.proconnect_transition_service import ProConnectTransitionService
from services.transition_prompt_builder import TransitionPromptBuilder, TransitionPromptPackage
from services.workflow_state import WorkflowStage
from scripts.proconnect_client import DEFAULT_BASE_URL, ProConnectClient


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]
logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass
class TransitionPlaybookRunResult:
    preflight: TransitionPreflight
    prompt_package: TransitionPromptPackage
    deep_research_response: Dict[str, Any]
    bd_report: MDReport
    actioning_context: Dict[str, Any]


@dataclass(frozen=True)
class ReviewedTransitionRunInput:
    run_id: str
    request: TransitionRequest
    preflight: TransitionPreflight
    prompt_package: TransitionPromptPackage


class TransitionPlaybookOrchestrator:
    """Coordinates the transition workflow end to end."""

    def __init__(
        self,
        proconnect_service: Optional[ProConnectTransitionService] = None,
        prompt_builder: Optional[TransitionPromptBuilder] = None,
        deep_research_runner: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
        bd_orchestrator: Optional[BDOrchestrator] = None,
    ) -> None:
        self.proconnect_service = proconnect_service
        self._owns_proconnect_service = proconnect_service is None
        self.prompt_builder = prompt_builder
        self.deep_research_runner = deep_research_runner
        self.bd_orchestrator = bd_orchestrator

    async def build_preflight(
        self,
        request: TransitionRequest,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> TransitionPreflight:
        """Build transition validation context before research is launched."""
        _, preflight, _ = await self._prepare_transition_context(
            request,
            progress_cb=progress_cb,
            include_prompt=True,
        )
        return preflight

    async def run_transition_playbook(
        self,
        request: TransitionRequest,
        progress_cb: Optional[ProgressCallback] = None,
        prompt_override: Optional[str] = None,
        reviewed_preflight: Optional[TransitionPreflight] = None,
        reviewed_prompt_package: Optional[TransitionPromptPackage] = None,
        reviewed_run_id: Optional[str] = None,
    ) -> TransitionPlaybookRunResult:
        """Run the full transition workflow."""
        transition_case: Optional[Dict[str, Any]]
        preflight: TransitionPreflight
        prompt_package: TransitionPromptPackage
        if reviewed_preflight and reviewed_prompt_package:
            transition_case = None
            preflight = reviewed_preflight
            prompt_package = reviewed_prompt_package
            logger.info(
                "Transition research using reviewed context run_id=%s person=%s destination=%s",
                reviewed_run_id,
                request.person_name,
                request.to_company,
            )
        else:
            transition_case, preflight, prompt_package = await self._prepare_transition_context(
                request,
                progress_cb=progress_cb,
                include_prompt=True,
                prompt_override=prompt_override,
            )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.RUNNING_DEEP_RESEARCH.value,
            message="Running Deep Research.",
            status="in_progress",
        )
        logger.info(
            "Transition Deep Research starting run_id=%s industry=%s prompt_chars=%s",
            reviewed_run_id,
            prompt_package.industry_key,
            len(prompt_package.user_prompt),
        )
        deep_research_response = await self._run_deep_research(
            prompt_package,
            progress_cb=progress_cb,
        )
        logger.info(
            "Transition Deep Research finished run_id=%s industry=%s",
            reviewed_run_id,
            prompt_package.industry_key,
        )

        bd = self._get_bd_orchestrator()
        trigger = self._build_bd_trigger(request, prompt_package, preflight=preflight, reviewed_run_id=reviewed_run_id)
        dr_markdown = format_deep_research_response_as_markdown(deep_research_response)
        structured_source_urls = self._extract_structured_source_urls(deep_research_response)
        structured_evidence_map = build_structured_evidence_map(deep_research_response)

        report = await bd.run(
            trigger,
            deep_research_output=dr_markdown,
            structured_source_urls=structured_source_urls,
            structured_evidence_map=structured_evidence_map,
            progress_cb=self._make_bd_progress_wrapper(progress_cb),
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.VALIDATING_CREDENTIALS.value,
            message="Credentials validation complete.",
            status="complete",
            **self._build_report_progress_metadata(report),
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.MAPPING_WARM_LEADS.value,
            message="Mapping warm leads and outreach context.",
            status="in_progress",
        )
        actioning_context = await asyncio.to_thread(
            self._get_proconnect_service().build_actioning_context,
            request,
            transition_case=transition_case,
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.MAPPING_WARM_LEADS.value,
            message="Warm leads and relationship routes mapped.",
            status="complete",
            **self._build_actioning_progress_metadata(actioning_context, preflight),
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.ASSEMBLING_BRIEF.value,
            message="Transition brief inputs assembled.",
            status="complete",
            opportunity_count=len(report.top_opportunities or []),
            recommended_action_count=len(report.recommended_actions or []),
        )

        return TransitionPlaybookRunResult(
            preflight=preflight,
            prompt_package=prompt_package,
            deep_research_response=deep_research_response,
            bd_report=report,
            actioning_context=actioning_context,
        )

    async def run_transition_playbook_from_reviewed_context(
        self,
        *,
        request: TransitionRequest,
        preflight: TransitionPreflight,
        prompt_package: TransitionPromptPackage,
        run_id: str,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> TransitionPlaybookRunResult:
        reviewed = ReviewedTransitionRunInput(
            run_id=run_id,
            request=request,
            preflight=preflight,
            prompt_package=prompt_package,
        )
        return await self.run_transition_playbook(
            reviewed.request,
            progress_cb=progress_cb,
            reviewed_preflight=reviewed.preflight,
            reviewed_prompt_package=reviewed.prompt_package,
            reviewed_run_id=reviewed.run_id,
        )

    async def _prepare_transition_context(
        self,
        request: TransitionRequest,
        *,
        progress_cb: Optional[ProgressCallback],
        include_prompt: bool,
        prompt_override: Optional[str] = None,
    ) -> tuple[Optional[Dict[str, Any]], TransitionPreflight, TransitionPromptPackage]:
        await self._emit(
            progress_cb,
            stage=WorkflowStage.RESOLVING_TRANSITION.value,
            message="Resolving transition scenario.",
            status="in_progress",
        )

        service = self._get_proconnect_service()
        transition_case = None
        if hasattr(service, "load_transition_case"):
            transition_case = await asyncio.to_thread(service.load_transition_case, request)

        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUILDING_RELATIONSHIP_CONTEXT.value,
            message="Building relationship context from ProConnect.",
            status="in_progress",
        )
        preflight = await asyncio.to_thread(
            service.build_preflight,
            request,
            transition_case=transition_case,
        )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.BUILDING_RELATIONSHIP_CONTEXT.value,
            message="Relationship context built from ProConnect.",
            status="complete",
            **self._build_preflight_progress_metadata(preflight),
        )

        builder = self._get_prompt_builder() if include_prompt else None
        if builder:
            prompt_package = builder.build(preflight)
            if prompt_override:
                prompt_package = TransitionPromptPackage(
                    industry_key=prompt_package.industry_key,
                    system_prompt=prompt_package.system_prompt,
                    user_prompt=prompt_override,
                )
                preflight.suggested_research_prompt = prompt_override
            if not preflight.suggested_research_prompt:
                preflight.suggested_research_prompt = prompt_package.user_prompt
        else:
            prompt_package = TransitionPromptPackage(
                industry_key=preflight.inferred_industry,
                system_prompt="",
                user_prompt=preflight.suggested_research_prompt,
            )

        await self._emit(
            progress_cb,
            stage=WorkflowStage.GENERATING_RESEARCH_PLAN.value,
            message="Generated research plan from validated transition context.",
            status="complete",
            industry_key=prompt_package.industry_key,
            opportunity_hypothesis_count=len(preflight.opportunity_hypotheses or []),
            prompt_overridden=bool(prompt_override),
        )
        return transition_case, preflight, prompt_package

    async def _run_deep_research(
        self,
        prompt_package: TransitionPromptPackage,
        *,
        progress_cb: Optional[ProgressCallback],
    ) -> Dict[str, Any]:
        runner = self._get_deep_research_runner()
        wrapped_progress = self._make_deep_research_progress_wrapper(progress_cb)
        kwargs = self._build_runner_kwargs(
            runner,
            industry=prompt_package.industry_key,
            progress_callback=wrapped_progress,
            instructions_override=prompt_package.system_prompt,
        )
        return await runner(prompt_package.user_prompt, **kwargs)

    def _get_proconnect_service(self) -> ProConnectTransitionService:
        if self.proconnect_service is None:
            return self._build_live_proconnect_service()
        if self._owns_proconnect_service:
            return self._build_live_proconnect_service()
        return self.proconnect_service

    def _build_live_proconnect_service(self) -> ProConnectTransitionService:
        token_file = getattr(AppConfig, "PROCONNECT_TOKEN_FILE", None)
        base_url = getattr(AppConfig, "PROCONNECT_BASE_URL", DEFAULT_BASE_URL)
        fallback_paths = [
            Path.cwd() / "token.txt",
            SCRIPT_DIR / "token.txt",
        ]
        token, _ = resolve_runtime_bearer_token(token_file=token_file, fallback_paths=fallback_paths)
        client = ProConnectClient(base_url=base_url, bearer_token=token)
        return ProConnectTransitionService(client=client)

    def _get_prompt_builder(self) -> TransitionPromptBuilder:
        if self.prompt_builder is None:
            self.prompt_builder = TransitionPromptBuilder()
        return self.prompt_builder

    def _get_deep_research_runner(self):
        if self.deep_research_runner is None:
            from tools.orchestrators import run_deep_research

            self.deep_research_runner = run_deep_research
        return self.deep_research_runner

    def _get_bd_orchestrator(self) -> BDOrchestrator:
        if self.bd_orchestrator is None:
            self.bd_orchestrator = BDOrchestrator()
        return self.bd_orchestrator

    def _build_bd_trigger(
        self,
        request: TransitionRequest,
        prompt_package: TransitionPromptPackage,
        *,
        preflight: Optional[TransitionPreflight] = None,
        reviewed_run_id: Optional[str] = None,
    ):
        session_params = {
            "company": (preflight.to_account.company_name if preflight and preflight.to_account.company_name else request.to_company),
            "signals": "",
            "geography": request.geography or "",
            "other_context": request.additional_context or "",
            "preflight_context": {
                "run_id": reviewed_run_id,
                "person_match_status": preflight.person_resolution.match_status if preflight else None,
                "resolved_source_company": preflight.from_account.company_name if preflight else request.from_company,
                "resolved_destination_company": preflight.to_account.company_name if preflight else request.to_company,
                "source_account_id": preflight.from_account.account_id if preflight else None,
                "destination_account_id": preflight.to_account.account_id if preflight else None,
                "warm_intro_path_available": preflight.quick_indicators.warm_intro_path_available if preflight else None,
                "opportunity_hypotheses": [
                    hypothesis.model_dump() if hasattr(hypothesis, "model_dump") else hypothesis.dict()
                    for hypothesis in (preflight.opportunity_hypotheses or [])
                ] if preflight else [],
            },
        }
        return build_trigger_for_bd_enrichment(
            sector=prompt_package.industry_key,
            user_query=prompt_package.user_prompt,
            session_params=session_params,
        )

    async def _emit(
        self,
        cb: Optional[ProgressCallback],
        *,
        stage: str,
        message: str,
        status: str,
        **extra: Any,
    ) -> None:
        if not cb:
            return
        event = {"stage": stage, "message": message, "status": status, **extra}
        result = cb(event)
        if asyncio.iscoroutine(result):
            await result

    def _make_deep_research_progress_wrapper(
        self,
        progress_cb: Optional[ProgressCallback],
    ) -> Callable[[str, Dict[str, Any]], Awaitable[None]]:
        async def _wrapped(text: str, metadata: Dict[str, Any]) -> None:
            await self._emit(
                progress_cb,
                stage="running_deep_research",
                message=text or "Deep Research activity update.",
                status=str(metadata.get("status") or "in_progress"),
                citation_count=metadata.get("citation_count", 0),
                poll_count=metadata.get("poll_count", 0),
                activity_log=metadata.get("activity_log", []),
            )

        return _wrapped

    def _make_bd_progress_wrapper(
        self,
        progress_cb: Optional[ProgressCallback],
    ) -> Callable[[str], Awaitable[None]]:
        async def _wrapped(message: str) -> None:
            lowered = (message or "").lower()
            if "credential" in lowered:
                stage = WorkflowStage.VALIDATING_CREDENTIALS.value
            elif "synthes" in lowered or "report" in lowered:
                stage = WorkflowStage.ASSEMBLING_BRIEF.value
            else:
                stage = WorkflowStage.VALIDATING_CREDENTIALS.value

            await self._emit(
                progress_cb,
                stage=stage,
                message=message,
                status="in_progress",
            )

        return _wrapped

    @staticmethod
    def _build_runner_kwargs(runner, **candidate_kwargs: Any) -> Dict[str, Any]:
        signature = inspect.signature(runner)
        params = signature.parameters
        accepts_varkw = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        kwargs: Dict[str, Any] = {}
        for key, value in candidate_kwargs.items():
            if key in params or accepts_varkw:
                kwargs[key] = value
        return kwargs

    @staticmethod
    def _extract_structured_source_urls(response: Dict[str, Any]) -> List[str]:
        urls: List[str] = []
        seen = set()

        def _add(url: Any) -> None:
            value = str(url or "").strip()
            if not value.startswith(("http://", "https://")):
                return
            key = value.lower()
            if key in seen:
                return
            seen.add(key)
            urls.append(value)

        for citation in response.get("citations", []) or []:
            if isinstance(citation, dict):
                _add(citation.get("url"))

        for section in response.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            for citation in section.get("citations", []) or []:
                if isinstance(citation, dict):
                    _add(citation.get("url"))

        metadata = response.get("metadata", {}) or {}
        for key in ("discovery_sources", "confirmation_sources", "display_sources"):
            for url in metadata.get(key, []) or []:
                _add(url)

        return urls

    @staticmethod
    def _build_preflight_progress_metadata(preflight: TransitionPreflight) -> Dict[str, Any]:
        indicators = preflight.quick_indicators
        return {
            "person_match_status": preflight.person_resolution.match_status,
            "matched_person_name": preflight.person_resolution.matched_name,
            "warm_intro_path_available": indicators.warm_intro_path_available,
            "source_worked_before": indicators.source_worked_before,
            "destination_worked_before": indicators.destination_worked_before,
            "source_key_buyer_count": indicators.source_key_buyer_count,
            "destination_key_buyer_count": indicators.destination_key_buyer_count,
            "source_connected_colleague_count": indicators.source_connected_colleague_count,
            "destination_connected_colleague_count": indicators.destination_connected_colleague_count,
            "inferred_industry": preflight.inferred_industry,
        }

    @staticmethod
    def _build_report_progress_metadata(report: MDReport) -> Dict[str, Any]:
        return {
            "lookups_executed_count": report.lookups_executed_count,
            "credentials_status_counts": dict(report.credentials_status_counts or {}),
            "validated_opportunity_count": len(report.top_opportunities or []),
        }

    @staticmethod
    def _build_actioning_progress_metadata(
        actioning_context: Dict[str, Any],
        preflight: TransitionPreflight,
    ) -> Dict[str, Any]:
        from_context = _as_dict(actioning_context.get("from_company_context"))
        to_context = _as_dict(actioning_context.get("to_company_context"))
        from_relationship = _as_dict(from_context.get("relationship_network"))
        to_relationship = _as_dict(to_context.get("relationship_network"))

        source_connected = _as_list(_as_dict(from_relationship.get("connected_colleagues")).get("items"))
        destination_connected = _as_list(_as_dict(to_relationship.get("connected_colleagues")).get("items"))
        destination_alumni = _as_list(_as_dict(to_relationship.get("protiviti_alumni")).get("items"))

        return {
            "warm_intro_path_available": bool(
                to_relationship.get("warm_intro_path_available")
                or preflight.quick_indicators.warm_intro_path_available
            ),
            "source_connected_colleague_count": len(source_connected),
            "destination_connected_colleague_count": len(destination_connected),
            "destination_alumni_count": len(destination_alumni),
            "warning_count": len(_as_list(actioning_context.get("warnings"))),
        }
