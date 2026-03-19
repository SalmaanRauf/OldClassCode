"""
Orchestration for the people movement brief workflow.
"""
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from config.config import AppConfig
from models.bd_schemas import BDTrigger, SignalEvidence
from models.movement_schemas import MovementBrief, MovementCredentialsProof, MovementRecord
from services.deep_research_formatter import (
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)
from services.fs_movement_digestor import FSMovementDigestor
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor
from services.movement_brief_assembler import MovementBriefAssembler
from services.movement_credentials_service import MovementCredentialsService
from services.movement_ranker import MovementRanker
from services.proconnect_movement_service import ProConnectMovementService
from services.signal_registry_service import get_signal_registry_service

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from proconnect_client import DEFAULT_BASE_URL, ProConnectClient, resolve_bearer_token  # noqa: E402


ProgressCallback = Callable[[Any], Any]
DeepResearchRunner = Callable[..., Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class MovementBriefRunResult:
    """End-to-end artifacts for a people movement brief run."""

    movement_brief: MovementBrief
    deep_research_markdown: str
    signal_evidence: List[SignalEvidence]
    movement_rows: List[MovementRecord]
    light_enriched_rows: List[Dict[str, Any]]
    ranked_rows: List[Dict[str, Any]]
    deep_enriched_rows: List[Dict[str, Any]]
    credential_packets: Dict[str, MovementCredentialsProof]
    signal_diagnostics: Dict[str, Any]
    movement_diagnostics: Dict[str, Any]


class MovementBriefOrchestrator:
    """Coordinates Deep Research, movement extraction, leverage, proof, and assembly."""

    def __init__(
        self,
        *,
        fs_signal_evidence_digestor: Optional[FSSignalEvidenceDigestor] = None,
        movement_digestor: Optional[FSMovementDigestor] = None,
        proconnect_service: Optional[ProConnectMovementService] = None,
        ranker: Optional[MovementRanker] = None,
        credentials_service: Optional[MovementCredentialsService] = None,
        assembler: Optional[MovementBriefAssembler] = None,
        deep_research_runner: Optional[DeepResearchRunner] = None,
    ) -> None:
        self.signal_registry = get_signal_registry_service()
        self.fs_signal_evidence_digestor = fs_signal_evidence_digestor or FSSignalEvidenceDigestor()
        self.movement_digestor = movement_digestor or FSMovementDigestor()
        self.proconnect_service = proconnect_service
        self.ranker = ranker or MovementRanker()
        self.credentials_service = credentials_service
        self.assembler = assembler or MovementBriefAssembler()
        self.deep_research_runner = deep_research_runner

    async def run(
        self,
        trigger: BDTrigger,
        *,
        deep_research_output: Optional[str] = None,
        deep_research_response: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> MovementBriefRunResult:
        """Run the full movement-led pipeline and return the assembled brief."""
        await self._notify(progress_cb, "Running Deep Research...")

        structured_evidence_map: Dict[str, Any] = {}
        if deep_research_output is None:
            if deep_research_response is not None:
                deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                structured_evidence_map = build_structured_evidence_map(deep_research_response)
            else:
                deep_research_response = await self._run_deep_research(trigger, progress_cb)
                if isinstance(deep_research_response, dict):
                    deep_research_output = format_deep_research_response_as_markdown(deep_research_response)
                    structured_evidence_map = build_structured_evidence_map(deep_research_response)
                else:
                    deep_research_output = str(deep_research_response or "")

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
        credentials_service = self._get_credentials_service()
        credential_packets = credentials_service.build_proof_packets(ranked_rows)

        await self._notify(progress_cb, "Assembling movement brief...")
        movement_brief = self.assembler.assemble(
            trigger=trigger,
            signal_evidence=signal_evidence,
            movement_rows=movement_rows,
            ranked_rows=ranked_rows,
            deep_enriched_rows=deep_enriched_rows,
            credential_packets=credential_packets,
            deep_research_summary=deep_research_summary,
        )

        return MovementBriefRunResult(
            movement_brief=movement_brief,
            deep_research_markdown=deep_research_markdown,
            signal_evidence=signal_evidence,
            movement_rows=movement_rows,
            light_enriched_rows=light_enriched_rows,
            ranked_rows=ranked_rows,
            deep_enriched_rows=deep_enriched_rows,
            credential_packets=credential_packets,
            signal_diagnostics=signal_diagnostics,
            movement_diagnostics=movement_diagnostics,
        )

    async def _run_deep_research(
        self,
        trigger: BDTrigger,
        progress_cb: Optional[ProgressCallback],
    ) -> Dict[str, Any]:
        runner = self._get_deep_research_runner()
        query = trigger.user_prompt_context or trigger.company_focus or trigger.sector
        response = await runner(
            query,
            **self._build_runner_kwargs(
                runner,
                industry=trigger.sector.replace(" ", "_").lower(),
                progress_callback=self._make_deep_research_progress_wrapper(progress_cb),
            ),
        )
        return response if isinstance(response, dict) else {"summary": str(response or "")}

    def _get_deep_research_runner(self) -> DeepResearchRunner:
        if self.deep_research_runner is None:
            from tools.orchestrators import run_deep_research

            self.deep_research_runner = run_deep_research
        return self.deep_research_runner

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

    def _get_credentials_service(self) -> MovementCredentialsService:
        if self.credentials_service is None:
            self.credentials_service = MovementCredentialsService(
                lookup=lambda _row: {"lookup_status": "No Match", "summary": "No proof lookup configured."}
            )
        return self.credentials_service

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
