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
import json
import logging
from datetime import datetime
from typing import Optional, Callable, Dict, List, Any
from pathlib import Path

from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    Opportunity,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
    OpportunityExtractionDiagnostics,
    MDReport,
    BDContext
)
from services.opportunity_extractor import OpportunityExtractor
from services.opportunity_digestor import OpportunityDigestor
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor
from services.fs_opportunity_deriver import FSOpportunityDeriver
from services.signal_registry_service import get_signal_registry_service
from agents.credentials_agent import CredentialsAgent
from agents.final_analyst_agent import FinalAnalystAgent

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[str], Any]


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
        credentials_agent: Optional[CredentialsAgent] = None,
        final_analyst: Optional[FinalAnalystAgent] = None,
        traces_dir: Optional[Path] = None,
        use_atlas_digestion: bool = False,
        credentials_lookup_mode: str = "serial_per_opportunity",
    ):
        """Initialize orchestrator with optional custom components.
        
        Args:
            extractor: OpportunityExtractor instance (or None to create)
            opportunity_digestor: OpportunityDigestor instance (or None to create)
            credentials_agent: CredentialsAgent instance (or None to create from env)
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
        self.final_analyst = final_analyst or FinalAnalystAgent()
        self.traces_dir = traces_dir
        self.use_atlas_digestion = use_atlas_digestion
        self.signal_registry = get_signal_registry_service()
        allowed_lookup_modes = {"serial_per_opportunity", "batched_single_call"}
        if credentials_lookup_mode not in allowed_lookup_modes:
            logger.warning(
                "Unknown credentials_lookup_mode '%s'; defaulting to serial_per_opportunity.",
                credentials_lookup_mode,
            )
            credentials_lookup_mode = "serial_per_opportunity"
        self.credentials_lookup_mode = credentials_lookup_mode
    
    async def _ensure_credentials_agent(self):
        """Lazy-load credentials agent if not provided."""
        if self.credentials_agent is None:
            self.credentials_agent = CredentialsAgent.from_env()
    
    async def run(
        self,
        trigger: BDTrigger,
        deep_research_output: Optional[str] = None,
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
                (
                    fs_signal_evidence,
                    fs_digest_diagnostics,
                    allowed_sources,
                ) = await self.fs_signal_evidence_digestor.digest(
                    trigger=trigger,
                    deep_research_markdown=ctx.deep_research_raw or "",
                    requested_signal_codes=list(trigger.signals),
                    source_urls=ctx.parsed_research.raw_citations,
                )
                ctx.fs_signal_evidence = fs_signal_evidence
                ctx.fs_allowed_sources = allowed_sources
                ctx.opportunity_digest_diagnostics = {
                    **(ctx.opportunity_digest_diagnostics or {}),
                    "fs_signal_evidence_digest": fs_digest_diagnostics,
                }

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
                await self._ensure_credentials_agent()
                if ctx.credentials_lookup_mode == "batched_single_call":
                    (
                        ctx.credentials_results,
                        ctx.credentials_batch_diagnostics,
                    ) = await self.credentials_agent.find_credentials_batch(
                        top_opportunities,
                        trigger.sector,
                        max_matches_per_opportunity=3,
                    )
                    ctx.trace.append("Executed single batched credentials lookup.")
                else:
                    ctx.credentials_results = {}
                    for opportunity in top_opportunities:
                        ctx.credentials_results[opportunity.title] = await self._lookup_single_with_retry(
                            opportunity,
                            trigger.sector,
                        )
                    ctx.credentials_batch_diagnostics = None
                    ctx.trace.append("Executed serial credentials lookups (top 3).")

                ctx.credentials_diagnostics = self._collect_credentials_diagnostics(
                    top_opportunities,
                    trigger.sector,
                    ctx.credentials_results
                )
                status_counts = self._count_lookup_statuses(ctx.credentials_results)

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

    async def _lookup_single_with_retry(
        self,
        opportunity: Opportunity,
        sector: str,
    ) -> CredentialsResponse:
        """Lookup one opportunity and retry once if it fails due to timeout-like failure."""
        response = await self.credentials_agent.find_credentials(opportunity, sector=sector)
        if self._is_timeout_lookup_failure(response):
            logger.warning(
                "Retrying serial credentials lookup after timeout-like failure for '%s'.",
                opportunity.title,
            )
            response = await self.credentials_agent.find_credentials(opportunity, sector=sector)
        return response

    def _is_timeout_lookup_failure(self, response: Optional[CredentialsResponse]) -> bool:
        if not response or response.lookup_status != "Lookup Failed":
            return False
        message_parts: List[str] = []
        if response.failure_reason:
            message_parts.append(response.failure_reason)
        if response.diagnostics and response.diagnostics.error_message:
            message_parts.append(response.diagnostics.error_message)
        combined = " ".join(message_parts).lower()
        retryable_markers = (
            "timed out",
            "timeout",
            "getaddrinfo failed",
            "temporary failure in name resolution",
            "name or service not known",
            "network is unreachable",
            "connection reset",
            "connection aborted",
            "connection refused",
            "bad gateway",
            "gateway timeout",
        )
        return any(marker in combined for marker in retryable_markers)
    
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
        """Run Deep Research (placeholder for actual implementation).
        
        In production, this would call the deep_research_client.
        For MVP, we expect pre-computed output to be passed in.
        """
        # TODO: Integrate with deep_research_client when ready
        # For now, return placeholder indicating Deep Research should be run separately
        await self._notify(
            progress_cb, 
            "Note: Deep Research should be run separately and output passed in"
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

    def _count_lookup_statuses(self, results: Dict[str, CredentialsResponse]) -> Dict[str, int]:
        """Count lookup statuses for trace summaries."""
        counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
        for response in results.values():
            status = response.lookup_status
            if status not in counts:
                status = "Lookup Failed"
            counts[status] += 1
        return counts

    def _collect_credentials_diagnostics(
        self,
        opportunities: List[Any],
        sector: str,
        results: Dict[str, CredentialsResponse]
    ) -> Dict[str, CredentialsLookupDiagnostics]:
        """Collect diagnostics for all looked-up opportunities."""
        diagnostics: Dict[str, CredentialsLookupDiagnostics] = {}
        for opp in opportunities:
            response = results.get(opp.title)
            if response and response.diagnostics:
                diagnostics[opp.title] = response.diagnostics
                continue
            lookup_status = response.lookup_status if response else "Lookup Failed"
            diagnostics[opp.title] = CredentialsLookupDiagnostics(
                opportunity_title=opp.title,
                sector=sector,
                query_text="",
                raw_response_text="",
                parse_outcome="diagnostics_missing",
                lookup_status=lookup_status,
                error_message=response.failure_reason if response else "Missing credentials response.",
                duration_ms=0.0,
                match_count=len(response.matches) if response else 0
            )
        return diagnostics

    def _attach_credentials_evidence(
        self,
        report: MDReport,
        credentials_results: Dict[str, CredentialsResponse],
        diagnostics: Dict[str, CredentialsLookupDiagnostics]
    ) -> None:
        """Attach explicit credentials evidence and lookup statuses to the final report."""
        report.credentials_evidence = list(diagnostics.values())
        for opp_report in report.top_opportunities:
            title = opp_report.opportunity.title
            cred_resp = credentials_results.get(title)
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
        for candidate in ctx.fs_phase3_candidates[:3]:
            opportunities.append(
                Opportunity(
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
