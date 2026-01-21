"""
BD Orchestrator for coordinating the full BD research workflow.

Orchestrates the sequence:
1. Run Deep Research (or use provided output)
2. Extract opportunities from Deep Research output
3. Query Credentials Agent for each opportunity (parallel)
4. Synthesize final MD Report via Final Analyst

Uses asyncio for parallel credential lookups.
"""
import asyncio
import json
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, List, Any
from pathlib import Path

from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    CredentialsResponse,
    MDReport,
    BDContext
)
from services.opportunity_extractor import OpportunityExtractor
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
        credentials_agent: Optional[CredentialsAgent] = None,
        final_analyst: Optional[FinalAnalystAgent] = None,
        traces_dir: Optional[Path] = None
    ):
        """Initialize orchestrator with optional custom components.
        
        Args:
            extractor: OpportunityExtractor instance (or None to create)
            credentials_agent: CredentialsAgent instance (or None to create from env)
            final_analyst: FinalAnalystAgent instance (or None to create)
            traces_dir: Directory for saving trace files (or None to skip)
        """
        self.extractor = extractor or OpportunityExtractor()
        self.credentials_agent = credentials_agent
        self.final_analyst = final_analyst or FinalAnalystAgent()
        self.traces_dir = traces_dir
    
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
            ctx.trace.append(f"Extracted {len(ctx.parsed_research.opportunities)} opportunities")
            
            # Step 3: Query credentials for top opportunities
            await self._notify(progress_cb, "Validating with Credentials Agent...")
            await self._ensure_credentials_agent()
            
            top_opportunities = ctx.parsed_research.opportunities[:5]
            ctx.credentials_results = await self._lookup_credentials_parallel(
                top_opportunities,
                trigger.sector,
                ctx
            )
            
            matched = sum(1 for r in ctx.credentials_results.values() if not r.no_matches_found)
            ctx.trace.append(f"Credentials: {matched}/{len(top_opportunities)} matched")
            
            # Step 4: Synthesize final report
            await self._notify(progress_cb, "Synthesizing MD Report...")
            ctx.final_report = await self.final_analyst.synthesize(
                trigger,
                ctx.parsed_research,
                ctx.credentials_results
            )
            ctx.trace.append("Synthesis complete")
            
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
    
    async def _lookup_credentials_parallel(
        self,
        opportunities: List[Any],
        sector: str,
        ctx: BDContext
    ) -> Dict[str, CredentialsResponse]:
        """Query credentials for multiple opportunities in parallel."""
        if not opportunities:
            return {}
        
        results: Dict[str, CredentialsResponse] = {}
        
        # Create tasks for parallel execution
        tasks = [
            self.credentials_agent.find_credentials(opp, sector)
            for opp in opportunities
        ]
        
        # Execute in parallel with error handling
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for opp, response in zip(opportunities, responses):
            if isinstance(response, Exception):
                ctx.errors.append(f"Credentials lookup failed for {opp.title}: {response}")
                results[opp.title] = CredentialsResponse(
                    opportunity_title=opp.title,
                    matches=[],
                    no_matches_found=True
                )
            else:
                results[opp.title] = response
        
        return results
    
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
                "credentials_lookups": len(ctx.credentials_results),
                "credentials_matched": sum(
                    1 for r in ctx.credentials_results.values() 
                    if not r.no_matches_found
                ),
                "trace": ctx.trace,
                "errors": ctx.errors,
                "duration_seconds": duration
            }
            
            trace_file.write_text(json.dumps(trace_data, indent=2))
            logger.info(f"Trace saved to {trace_file}")
            
        except Exception as e:
            logger.warning(f"Failed to save trace: {e}")
