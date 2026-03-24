"""
BD Orchestrator for coordinating the full BD research workflow.

Orchestrates the sequence:
1. Run Deep Research (or use provided output)
2. Extract opportunities from Deep Research output
3. Optionally normalize opportunities via ATLAS digestor
4. Query Credentials Agent once for top opportunities (batched)
5. Synthesize final MD Report via Final Analyst
"""
import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Optional, Callable, Dict, List, Any, TYPE_CHECKING
from pathlib import Path

from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    Opportunity,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    OpportunityExtractionDiagnostics,
    MDReport,
    BDContext
)
from services.opportunity_extractor import OpportunityExtractor
from services.opportunity_digestor import OpportunityDigestor
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor
from services.fs_opportunity_deriver import FSOpportunityDeriver
from services.signal_registry_service import get_signal_registry_service
from services.credentials_lookup_runner import CredentialsLookupRunner

if TYPE_CHECKING:
    from agents.final_analyst_agent import FinalAnalystAgent

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[str], Any]


def _create_default_final_analyst() -> "FinalAnalystAgent":
    """Import lazily to avoid startup-order issues during app bootstrap."""
    from agents.final_analyst_agent import FinalAnalystAgent

    return FinalAnalystAgent()


class BDOrchestrator:
    """Orchestrates the BD research workflow.
    
    Sequence:
    1. Deep Research → raw markdown
    2. Opportunity Extraction → structured opportunities
    3. Credentials Lookup → validation per opportunity
    4. Final Synthesis → MD Report
    
    Example:
        orchestrator = BDOrchestrator()
        report = await orchestrator.run(trigger, progress_callback=print)
    """
    
    def __init__(
        self,
        extractor: Optional[OpportunityExtractor] = None,
        opportunity_digestor: Optional[OpportunityDigestor] = None,
        fs_signal_evidence_digestor: Optional[FSSignalEvidenceDigestor] = None,
        fs_opportunity_deriver: Optional[FSOpportunityDeriver] = None,
        credentials_agent: Optional[Any] = None,
        credentials_lookup_runner: Optional[CredentialsLookupRunner] = None,
        final_analyst: Optional["FinalAnalystAgent"] = None,
        traces_dir: Optional[Path] = None,
        use_atlas_digestion: bool = False,
        credentials_lookup_mode: str = "serial_per_opportunity",
    ):
        """Initialize orchestrator with optional custom components.
        
        Args:
            extractor: OpportunityExtractor instance (or None to create)
            opportunity_digestor: OpportunityDigestor instance (or None to create)
            credentials_agent: CredentialsAgent instance (or None to create from env)
            credentials_lookup_runner: Shared credentials runner instance (or None to create)
            final_analyst: FinalAnalystAgent instance (or None to create)
            traces_dir: Directory for saving trace files (or None to skip)
            use_atlas_digestion: Whether to normalize opportunities with ATLAS
            credentials_lookup_mode: serial_per_opportunity (default) or batched_single_call
        """
        self.extractor = extractor or OpportunityExtractor()
        self.opportunity_digestor = opportunity_digestor or OpportunityDigestor()
        self.fs_signal_evidence_digestor = fs_signal_evidence_digestor or FSSignalEvidenceDigestor()
        self.fs_opportunity_deriver = fs_opportunity_deriver or FSOpportunityDeriver()
        self.credentials_agent = credentials_agent
        self.credentials_lookup_runner = credentials_lookup_runner or CredentialsLookupRunner(
            credentials_agent=credentials_agent,
            lookup_mode=credentials_lookup_mode,
        )
        self.final_analyst = final_analyst or _create_default_final_analyst()
        self.traces_dir = traces_dir
        self.use_atlas_digestion = use_atlas_digestion
        self.signal_registry = get_signal_registry_service()
        self.credentials_lookup_mode = self.credentials_lookup_runner.lookup_mode

    async def run(
        self,
        trigger: BDTrigger,
        deep_research_output: Optional[str] = None,
        structured_source_urls: Optional[List[str]] = None,
        structured_evidence_map: Optional[Dict[str, Any]] = None,
        progress_cb: Optional[ProgressCallback] = None
    ) -> MDReport:
        """Run the full BD orchestration workflow.
        
        Args:
            trigger: User's BD trigger request
            deep_research_output: Pre-computed Deep Research markdown (or None to run)
            progress_cb: Optional callback for progress updates
            
        Returns:
            MDReport with synthesized findings
        """
        start_time = datetime.now()
        
        # Initialize context
        ctx = BDContext(trigger=trigger)
        ctx.structured_source_urls = self._merge_source_urls(structured_source_urls or [])
        evidence_map = structured_evidence_map or {}
        ctx.fs_section_source_map = dict(evidence_map.get("section_source_map") or {})
        ctx.fs_signal_source_candidates = dict(evidence_map.get("signal_source_candidates") or {})
        ctx.credentials_lookup_mode = self.credentials_lookup_mode
        
        try:
            # Step 1: Get Deep Research output
            await self._notify(progress_cb, "Running Deep Research...")
            if deep_research_output:
                ctx.deep_research_raw = deep_research_output
                ctx.trace.append("Using provided Deep Research output")
            else:
                ctx.deep_research_raw = await self._run_deep_research(trigger, progress_cb)
            
            ctx.trace.append(f"Deep Research: {len(ctx.deep_research_raw or '')} chars")
            
            # Step 2: Extract opportunities
            await self._notify(progress_cb, "Extracting opportunities...")
            ctx.parsed_research = self.extractor.extract(ctx.deep_research_raw or "")
            ctx.parsed_research.opportunities = self._ensure_opportunity_ids(
                ctx.parsed_research.opportunities,
                prefix="bd",
            )
            ctx.parsed_research.structured_citations = self._merge_source_urls(
                list(ctx.parsed_research.structured_citations or []) + ctx.structured_source_urls
            )
            ctx.parsed_research.section_source_map = dict(ctx.fs_section_source_map)
            ctx.parsed_research.signal_source_candidates = dict(ctx.fs_signal_source_candidates)
            ctx.opportunities_source = (
                "deterministic_extractor"
                if ctx.parsed_research.opportunities
                else "none"
            )

            if self.use_atlas_digestion:
                await self._notify(progress_cb, "Normalizing opportunities with ATLAS...")
                digested_opportunities, digest_details = await self.opportunity_digestor.digest(
                    ctx.trigger,
                    ctx.deep_research_raw or "",
                )
                ctx.opportunity_digest_diagnostics = digest_details
                if digested_opportunities:
                    digested_opportunities = self._ensure_opportunity_ids(
                        digested_opportunities,
                        prefix="bd",
                    )
                    candidate_signals = 0
                    if ctx.parsed_research.extraction_diagnostics:
                        candidate_signals = ctx.parsed_research.extraction_diagnostics.candidate_signal_count
                    ctx.parsed_research.opportunities = digested_opportunities
                    ctx.parsed_research.extraction_diagnostics = OpportunityExtractionDiagnostics(
                        status="Parsed",
                        reason=f"Parsed {len(digested_opportunities)} opportunities using atlas_digest.",
                        opportunities_extracted_count=len(digested_opportunities),
                        extraction_method="atlas_digest",
                        extraction_confidence="High",
                        candidate_signal_count=candidate_signals,
                    )
                    ctx.opportunities_source = "atlas_digest"
                    ctx.trace.append(
                        f"ATLAS digest normalized {len(digested_opportunities)} opportunities."
                    )
                else:
                    reason = digest_details.get("reason") if digest_details else "No reason provided."
                    ctx.trace.append(f"ATLAS digest returned no opportunities: {reason}")

            extraction_diag = ctx.parsed_research.extraction_diagnostics or self._classify_extraction(
                ctx.parsed_research,
                ctx.deep_research_raw or ""
            )
            ctx.opportunity_extraction_status = extraction_diag.status
            ctx.opportunity_extraction_reason = extraction_diag.reason
            ctx.opportunities_extracted_count = len(ctx.parsed_research.opportunities)
            ctx.trace.append(
                f"Extracted {ctx.opportunities_extracted_count} opportunities "
                f"(status={ctx.opportunity_extraction_status})"
            )

            if self.signal_registry.is_financial_services(trigger.sector):
                await self._notify(progress_cb, "Normalizing financial-services signal evidence...")
                requested_fs_signals = list(trigger.signals)
                if not requested_fs_signals:
                    requested_fs_signals = self.signal_registry.get_fs_signal_codes()
                    ctx.trace.append(
                        "No FS signals were explicitly requested; defaulted to full FS signal set."
                    )
                (
                    fs_signal_evidence,
                    fs_digest_diagnostics,
                    allowed_sources,
                ) = await self.fs_signal_evidence_digestor.digest(
                    trigger=trigger,
                    deep_research_markdown=ctx.deep_research_raw or "",
                    requested_signal_codes=requested_fs_signals,
                    source_urls=self._merge_source_urls(
                        list(ctx.parsed_research.raw_citations or [])
                        + list(ctx.parsed_research.structured_citations or [])
                    ),
                    section_source_map=ctx.parsed_research.section_source_map,
                    signal_source_candidates=ctx.parsed_research.signal_source_candidates,
                )
                ctx.fs_signal_evidence = fs_signal_evidence
                ctx.fs_allowed_sources = allowed_sources
                ctx.fs_confirmation_sources = allowed_sources
                ctx.fs_discovery_sources = list(
                    (
                        (fs_digest_diagnostics or {}).get("discovery_sources")
                        or []
                    )
                )
                reason_codes = list((fs_digest_diagnostics or {}).get("reason_codes") or [])
                ctx.fs_normalization_diagnostics = {
                    "reason_codes": reason_codes,
                    "source_coverage_alert": (fs_digest_diagnostics or {}).get("source_coverage_alert"),
                }
                ctx.parsed_research.normalization_diagnostics = dict(ctx.fs_normalization_diagnostics)
                ctx.opportunity_digest_diagnostics = {
                    **(ctx.opportunity_digest_diagnostics or {}),
                    "fs_signal_evidence_digest": fs_digest_diagnostics,
                }
                coverage_alert = (fs_digest_diagnostics or {}).get("source_coverage_alert")
                if coverage_alert:
                    ctx.trace.append(f"FS source coverage alert: {coverage_alert}")
                    logger.warning("FS source coverage alert: %s", coverage_alert)

                ctx.fs_phase3_candidates = self.fs_opportunity_deriver.derive(
                    trigger=trigger,
                    signal_evidence=ctx.fs_signal_evidence,
                    max_opportunities=3,
                )
                if ctx.fs_phase3_candidates:
                    ctx.parsed_research.opportunities = self._phase_candidates_to_opportunities(ctx)
                    ctx.opportunities_extracted_count = len(ctx.parsed_research.opportunities)
                    ctx.opportunities_source = "fs_signal_derivation"
                    ctx.opportunity_extraction_status = "Parsed"
                    ctx.opportunity_extraction_reason = (
                        f"Derived {ctx.opportunities_extracted_count} opportunities from confirmed FS signals."
                    )
                    ctx.trace.append(
                        f"FS evidence mode derived {ctx.opportunities_extracted_count} opportunities."
                    )

            # Step 3: Query credentials for top opportunities
            top_opportunities = ctx.parsed_research.opportunities[:3]
            status_counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
            if ctx.opportunity_extraction_status == "Extraction Failed":
                ctx.lookups_skipped_reason = (
                    ctx.opportunity_extraction_reason
                    or "Credentials lookup skipped because opportunity extraction failed."
                )
                ctx.credentials_results = {}
                ctx.credentials_diagnostics = {}
                await self._notify(progress_cb, "Skipping credentials lookup due to extraction failure.")
                ctx.trace.append("Credentials lookup skipped due to extraction failure.")
            elif not top_opportunities:
                ctx.lookups_skipped_reason = "No opportunities identified for credentials validation."
                ctx.credentials_results = {}
                ctx.credentials_diagnostics = {}
                await self._notify(progress_cb, "No opportunities found; skipping credentials lookup.")
                ctx.trace.append("Credentials lookup skipped because no opportunities were identified.")
            else:
                await self._notify(progress_cb, "Validating with Credentials Agent...")
                lookup_run = await self.credentials_lookup_runner.run(
                    top_opportunities,
                    sector=trigger.sector,
                )
                ctx.credentials_results = lookup_run.results
                ctx.credentials_diagnostics = lookup_run.diagnostics
                ctx.credentials_batch_diagnostics = lookup_run.batch_diagnostics
                status_counts = lookup_run.status_counts
                if ctx.credentials_lookup_mode == "batched_single_call":
                    ctx.trace.append("Executed single batched credentials lookup.")
                else:
                    ctx.trace.append("Executed serial credentials lookups (top 3).")

            if ctx.lookups_skipped_reason:
                ctx.lookups_executed_count = 0
            elif top_opportunities:
                ctx.lookups_executed_count = len(top_opportunities)
            else:
                ctx.lookups_executed_count = len(ctx.credentials_results)
            ctx.credentials_status_counts = status_counts
            ctx.trace.append(
                "Credentials: "
                f"matched={status_counts['Matched']}, "
                f"no_match={status_counts['No Match']}, "
                f"failed={status_counts['Lookup Failed']}, "
                f"executed={ctx.lookups_executed_count}"
            )
            
            # Step 4: Synthesize final report
            await self._notify(progress_cb, "Synthesizing MD Report...")
            preflight_context = self._build_preflight_context(ctx)
            ctx.final_report = await self.final_analyst.synthesize(
                trigger,
                ctx.parsed_research,
                ctx.credentials_results,
                opportunity_extraction_status=ctx.opportunity_extraction_status,
                opportunity_extraction_reason=ctx.opportunity_extraction_reason,
                opportunities_extracted_count=ctx.opportunities_extracted_count,
                lookups_executed_count=ctx.lookups_executed_count,
                lookups_skipped_reason=ctx.lookups_skipped_reason,
                credentials_status_counts=ctx.credentials_status_counts,
                credentials_lookup_mode=ctx.credentials_lookup_mode,
                credentials_batch_diagnostics=ctx.credentials_batch_diagnostics,
                confirmed_signal_evidence=ctx.fs_signal_evidence,
                phase3_candidates=ctx.fs_phase3_candidates,
                allowed_sources=ctx.fs_allowed_sources,
                preflight_context=preflight_context,
            )
            self._attach_credentials_evidence(ctx.final_report, ctx.credentials_results, ctx.credentials_diagnostics)
            self._attach_pipeline_diagnostics(ctx.final_report, ctx)
            ctx.synthesis_status = ctx.final_report.synthesis_status
            ctx.synthesis_fallback_reason = ctx.final_report.synthesis_fallback_reason
            ctx.synthesis_error_message = ctx.final_report.synthesis_error_message
            ctx.trace.append(f"Synthesis complete (status={ctx.synthesis_status})")
            if ctx.synthesis_status == "fallback":
                ctx.trace.append(
                    "Synthesis fallback reason: "
                    f"{ctx.synthesis_fallback_reason or 'unknown'}"
                )
                if ctx.synthesis_error_message:
                    ctx.trace.append(f"Synthesis fallback error: {ctx.synthesis_error_message}")
                if ctx.synthesis_fallback_reason in {"synthesis_error", "parse_error"}:
                    ctx.errors.append(
                        "Synthesis fallback: "
                        f"{ctx.synthesis_fallback_reason} - "
                        f"{ctx.synthesis_error_message or 'No error message'}"
                    )
            
            # Save trace
            duration = (datetime.now() - start_time).total_seconds()
            self._save_trace(ctx, duration)
            
            await self._notify(progress_cb, f"Complete! ({duration:.1f}s)")
            return ctx.final_report
            
        except Exception as e:
            ctx.errors.append(f"Orchestration failed: {str(e)}")
            logger.exception(f"BD Orchestration failed: {e}")
            self._save_trace(ctx, (datetime.now() - start_time).total_seconds())
            raise

    async def _notify(self, cb: Optional[ProgressCallback], message: str):
        """Send progress notification if callback provided."""
        if cb:
            try:
                result = cb(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")
    
    async def _run_deep_research(
        self,
        trigger: BDTrigger,
        progress_cb: Optional[ProgressCallback]
    ) -> str:
        """Fallback when the caller does not provide Deep Research output.

        The current application flows are expected to run Deep Research upstream
        and pass its output into the BD orchestrator. This method preserves a
        deterministic fallback for older or script-driven entry points.
        """
        await self._notify(
            progress_cb, 
            "Deep Research output was not provided; skipping direct research execution in this BD run."
        )
        return ""
    
    def _classify_extraction(
        self,
        parsed_research: DeepResearchOutput,
        raw_markdown: str
    ) -> OpportunityExtractionDiagnostics:
        """Classify extraction status when extractor diagnostics are missing."""
        parsed_count = len(parsed_research.opportunities)
        if parsed_count > 0:
            return OpportunityExtractionDiagnostics(
                status="Parsed",
                reason=f"Parsed {parsed_count} opportunities.",
                opportunities_extracted_count=parsed_count,
                extraction_method="section_structured",
                extraction_confidence="Medium",
                candidate_signal_count=0
            )

        markdown = (raw_markdown or "").lower()
        rich_signals = sum(
            1 for token in ("solicitation", "rfp", "idiq", "contract", "cmmc", "value:", "timeline:", "$")
            if token in markdown
        )
        if rich_signals >= 3:
            return OpportunityExtractionDiagnostics(
                status="Extraction Failed",
                reason="Opportunity-like text present but no structured opportunities parsed.",
                opportunities_extracted_count=0,
                extraction_method="none",
                extraction_confidence="Low",
                candidate_signal_count=rich_signals
            )

        return OpportunityExtractionDiagnostics(
            status="No Opportunities",
            reason="No opportunity-like content detected.",
            opportunities_extracted_count=0,
            extraction_method="none",
            extraction_confidence="Low",
            candidate_signal_count=rich_signals
        )

    def _attach_credentials_evidence(
        self,
        report: MDReport,
        credentials_results: Dict[str, CredentialsResponse],
        diagnostics: Dict[str, CredentialsLookupDiagnostics]
    ) -> None:
        """Attach explicit credentials evidence and lookup statuses to the final report."""
        report.credentials_evidence = list(diagnostics.values())
        for index, opp_report in enumerate(report.top_opportunities):
            cred_resp = self._resolve_credentials_response_for_opportunity(
                getattr(opp_report.opportunity, "opportunity_id", None),
                opp_report.opportunity.title,
                credentials_results,
                fallback_index=index,
            )
            if not cred_resp:
                continue

            opp_report.credentials_lookup_status = cred_resp.lookup_status

            if cred_resp.lookup_status == "Matched":
                opp_report.credentials = cred_resp.matches[:2]
                if opp_report.validation_status == "No Internal Data":
                    opp_report.validation_status = "Validated" if len(cred_resp.matches) >= 2 else "Partial"
            else:
                opp_report.credentials = []
                # Preserve legacy validation labels while surfacing explicit status separately.
                opp_report.validation_status = "No Internal Data"

        if report.phase3_opportunities:
            for phase_opp in report.phase3_opportunities:
                cred_resp = self._resolve_credentials_response_for_signal(
                    phase_opp.derived_from_signal,
                    credentials_results,
                )
                if not cred_resp:
                    continue
                if cred_resp.lookup_status == "Matched" and cred_resp.matches:
                    titles = [match.title for match in cred_resp.matches[:2] if match.title]
                    if titles:
                        phase_opp.credentials_summary = (
                            "Matched credentials: " + "; ".join(titles) + "."
                        )
                elif cred_resp.lookup_status == "Lookup Failed":
                    phase_opp.credentials_summary = (
                        "Credential lookup failed for this opportunity in this run."
                    )
                else:
                    phase_opp.credentials_summary = "No materially aligned credentials identified."

    def _resolve_credentials_response_for_opportunity(
        self,
        opportunity_id: Optional[str],
        title: str,
        credentials_results: Dict[str, CredentialsResponse],
        fallback_index: Optional[int] = None,
    ) -> Optional[CredentialsResponse]:
        if opportunity_id and opportunity_id in credentials_results:
            return credentials_results[opportunity_id]
        if title in credentials_results:
            return credentials_results[title]

        signal_code = self._extract_signal_code(title)
        if signal_code:
            response = self._resolve_credentials_response_for_signal(signal_code, credentials_results)
            if response:
                return response

        normalized_title = self._normalize_lookup_key(title)
        if not normalized_title:
            return None

        fuzzy_hits: List[tuple[str, CredentialsResponse]] = []
        for key, response in credentials_results.items():
            normalized_key = self._normalize_lookup_key(key)
            if not normalized_key:
                continue
            if normalized_key in normalized_title or normalized_title in normalized_key:
                fuzzy_hits.append((key, response))

        if len(fuzzy_hits) == 1:
            return fuzzy_hits[0][1]
        if fuzzy_hits:
            fuzzy_hits.sort(key=lambda item: len(item[0]), reverse=True)
            return fuzzy_hits[0][1]

        if fallback_index is not None and 0 <= fallback_index < len(credentials_results):
            return list(credentials_results.values())[fallback_index]
        return None

    def _resolve_credentials_response_for_signal(
        self,
        signal_code: Optional[str],
        credentials_results: Dict[str, CredentialsResponse],
    ) -> Optional[CredentialsResponse]:
        if not signal_code:
            return None
        normalized_code = signal_code.upper().strip()
        if not normalized_code.startswith("FS."):
            return None

        scoped = [
            (key, response)
            for key, response in credentials_results.items()
            if self._extract_signal_code(key) == normalized_code
            or self._extract_signal_code(response.opportunity_title) == normalized_code
            or self._extract_signal_code(response.opportunity_id or "") == normalized_code
        ]
        if len(scoped) == 1:
            return scoped[0][1]
        if scoped:
            scoped.sort(key=lambda item: len(item[0]), reverse=True)
            return scoped[0][1]
        return None

    def _extract_signal_code(self, text: str) -> Optional[str]:
        if not text:
            return None
        match = re.match(r"\s*(FS\.[A-Z0-9_.]+)\s*:", text.strip(), re.IGNORECASE)
        if not match:
            return None
        return match.group(1).upper()

    def _normalize_lookup_key(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    def _attach_pipeline_diagnostics(self, report: MDReport, ctx: BDContext) -> None:
        """Attach pipeline-level diagnostics for rendering and traceability."""
        report.opportunity_extraction_status = ctx.opportunity_extraction_status
        report.opportunity_extraction_reason = ctx.opportunity_extraction_reason
        report.opportunities_extracted_count = ctx.opportunities_extracted_count
        report.lookups_executed_count = ctx.lookups_executed_count
        report.lookups_skipped_reason = ctx.lookups_skipped_reason
        report.credentials_status_counts = dict(ctx.credentials_status_counts)
        report.credentials_lookup_mode = ctx.credentials_lookup_mode
        report.credentials_batch_diagnostics = ctx.credentials_batch_diagnostics
        report.opportunities_source = ctx.opportunities_source
        if ctx.synthesis_status:
            report.synthesis_status = ctx.synthesis_status
        if ctx.synthesis_fallback_reason:
            report.synthesis_fallback_reason = ctx.synthesis_fallback_reason
        if ctx.synthesis_error_message:
            report.synthesis_error_message = ctx.synthesis_error_message

    def _phase_candidates_to_opportunities(self, ctx: BDContext) -> List[Opportunity]:
        """Convert deterministic phase candidates into opportunities for credential validation."""
        opportunities: List[Opportunity] = []
        for index, candidate in enumerate(ctx.fs_phase3_candidates[:3], 1):
            opportunity_id = self._build_opportunity_id(
                prefix="phase3",
                parts=[candidate.derived_from_signal, candidate.overview, candidate.technical_explanation],
            )
            opportunities.append(
                Opportunity(
                    opportunity_id=opportunity_id,
                    title=f"{candidate.derived_from_signal}: {candidate.overview[:90]}",
                    agency=None,
                    scope=(candidate.technical_explanation or candidate.overview or "").strip(),
                    estimated_value=None,
                    timeline=None,
                    incumbent=None,
                    cmmc_level=None,
                    confidence="High",
                    citations=list(candidate.sources or []),
                )
            )
        return opportunities

    def _ensure_opportunity_ids(self, opportunities: List[Opportunity], *, prefix: str) -> List[Opportunity]:
        normalized: List[Opportunity] = []
        for index, opportunity in enumerate(opportunities, 1):
            if getattr(opportunity, "opportunity_id", None):
                normalized.append(opportunity)
                continue
            normalized.append(
                opportunity.model_copy(
                    update={"opportunity_id": self._build_opportunity_id(prefix=prefix, parts=[opportunity.title, opportunity.scope, getattr(opportunity, "agency", "") or "", ",".join(opportunity.citations or [])])}
                )
            )
        return normalized

    def _build_preflight_context(self, ctx: BDContext) -> Dict[str, Any]:
        opportunities = [
            {
                "opportunity_id": opp.opportunity_id,
                "title": opp.title,
                "agency": opp.agency,
                "scope": opp.scope,
                "estimated_value": opp.estimated_value,
                "timeline": opp.timeline,
                "incumbent": opp.incumbent,
                "cmmc_level": opp.cmmc_level,
                "confidence": opp.confidence,
            }
            for opp in (ctx.parsed_research.opportunities if ctx.parsed_research else [])
        ]
        return {
            "sector": ctx.trigger.sector,
            "signals": list(ctx.trigger.signals),
            "company_focus": ctx.trigger.company_focus,
            "geography": ctx.trigger.geography,
            "time_window_days": ctx.trigger.time_window_days,
            "min_value_usd": ctx.trigger.min_value_usd,
            "opportunities": opportunities,
            "opportunities_source": ctx.opportunities_source,
            "structured_source_urls": list(ctx.structured_source_urls),
        }

    def _build_opportunity_id(self, *, prefix: str, parts: List[str]) -> str:
        seed = "|".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())
        digest = hashlib.sha1(f"{prefix}|{seed}".encode("utf-8")).hexdigest()[:12]
        return f"{prefix}_{digest}"
    
    def _save_trace(self, ctx: BDContext, duration: float):
        """Save execution trace to file."""
        if not self.traces_dir:
            return
        
        try:
            self.traces_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trace_file = self.traces_dir / f"bd_run_{timestamp}.json"
            
            trace_data = {
                "timestamp": datetime.now().isoformat(),
                "trigger": {
                    "sector": ctx.trigger.sector,
                    "signals": ctx.trigger.signals,
                    "company_focus": ctx.trigger.company_focus,
                    "geography": ctx.trigger.geography
                },
                "deep_research_length": len(ctx.deep_research_raw or ""),
                "opportunities_extracted": len(ctx.parsed_research.opportunities) if ctx.parsed_research else 0,
                "opportunity_extraction_status": ctx.opportunity_extraction_status,
                "opportunity_extraction_reason": ctx.opportunity_extraction_reason,
                "opportunities_extracted_count": ctx.opportunities_extracted_count,
                "lookups_executed_count": ctx.lookups_executed_count,
                "lookups_skipped_reason": ctx.lookups_skipped_reason,
                "opportunities_source": ctx.opportunities_source,
                "credentials_lookup_mode": ctx.credentials_lookup_mode,
                "credentials_lookups": len(ctx.credentials_results),
                "credentials_matched": sum(1 for r in ctx.credentials_results.values() if r.lookup_status == "Matched"),
                "credentials_no_match": sum(1 for r in ctx.credentials_results.values() if r.lookup_status == "No Match"),
                "credentials_lookup_failed": sum(
                    1 for r in ctx.credentials_results.values() if r.lookup_status == "Lookup Failed"
                ),
                "credentials_status_counts": dict(ctx.credentials_status_counts),
                "synthesis_status": ctx.synthesis_status,
                "synthesis_fallback_reason": ctx.synthesis_fallback_reason,
                "synthesis_error_message": ctx.synthesis_error_message,
                "credentials_batch_diagnostics": (
                    ctx.credentials_batch_diagnostics.model_dump()
                    if ctx.credentials_batch_diagnostics and hasattr(ctx.credentials_batch_diagnostics, "model_dump")
                    else (ctx.credentials_batch_diagnostics.__dict__ if ctx.credentials_batch_diagnostics else None)
                ),
                "opportunity_digest_diagnostics": ctx.opportunity_digest_diagnostics,
                "structured_source_urls_count": len(ctx.structured_source_urls),
                "fs_discovery_sources_count": len(ctx.fs_discovery_sources),
                "fs_confirmation_sources_count": len(ctx.fs_confirmation_sources),
                "fs_section_source_map_count": len(ctx.fs_section_source_map),
                "fs_signal_source_candidates_count": len(ctx.fs_signal_source_candidates),
                "fs_normalization_diagnostics": ctx.fs_normalization_diagnostics,
                "credentials_diagnostics": [
                    diag.model_dump() if hasattr(diag, "model_dump") else diag.__dict__
                    for diag in ctx.credentials_diagnostics.values()
                ],
                "trace": ctx.trace,
                "errors": ctx.errors,
                "duration_seconds": duration
            }
            
            trace_file.write_text(json.dumps(trace_data, indent=2))
            logger.info(f"Trace saved to {trace_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save trace: {e}")

    def _merge_source_urls(self, urls: List[str]) -> List[str]:
        merged: List[str] = []
        seen = set()
        for raw in urls:
            value = str(raw or "").strip()
            if not value.startswith(("http://", "https://")):
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
        return merged
