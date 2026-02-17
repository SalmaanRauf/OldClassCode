"""
Final Analyst Agent for synthesizing BD research into MD Reports.

Uses ATLAS/Semantic Kernel to generate concise, actionable reports
combining Deep Research findings with Credentials validation.

The agent follows the existing kernel_setup.py pattern with ATLASClient.
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from models.bd_schemas import (
    BDTrigger,
    DeepResearchOutput,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
    MDReport,
    MDReportOpportunity,
    Opportunity,
    CredentialMatch
)

logger = logging.getLogger(__name__)

# Path to SK prompt
PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_Final_Synthesis_prompt.txt"


class FinalAnalystAgent:
    """Agent for synthesizing BD research into MD reports.
    
    Uses ATLAS via Semantic Kernel to generate concise synthesis
    of Deep Research + Credentials data.
    
    Example:
        agent = FinalAnalystAgent()
        report = await agent.synthesize(trigger, research, credentials)
    """
    
    def __init__(self, kernel=None, exec_settings=None):
        """Initialize with optional kernel (for testing with mocks).
        
        Args:
            kernel: Semantic Kernel instance (or None to load from kernel_setup)
            exec_settings: Execution settings (or None to load from kernel_setup)
        """
        self._kernel = kernel
        self._exec_settings = exec_settings
        self._prompt_template: Optional[str] = None
    
    async def _ensure_kernel(self):
        """Lazy-load kernel from kernel_setup if not provided."""
        if self._kernel is None:
            from config.kernel_setup import get_kernel_async
            self._kernel, self._exec_settings = await get_kernel_async()
    
    def _load_prompt(self) -> str:
        """Load the synthesis prompt template."""
        if self._prompt_template is None:
            if PROMPT_PATH.exists():
                self._prompt_template = PROMPT_PATH.read_text()
            else:
                # Fallback inline prompt
                self._prompt_template = self._get_fallback_prompt()
        return self._prompt_template
    
    async def synthesize(
        self,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str = "Parsed",
        opportunity_extraction_reason: Optional[str] = None,
        opportunities_extracted_count: int = 0,
        lookups_executed_count: int = 0,
        lookups_skipped_reason: Optional[str] = None,
        credentials_status_counts: Optional[Dict[str, int]] = None,
        credentials_lookup_mode: str = "batched_single_call",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
    ) -> MDReport:
        """Synthesize research and credentials into MD report.
        
        Args:
            trigger: Original user trigger
            research: Parsed Deep Research output
            credentials: Credentials responses keyed by opportunity title
            
        Returns:
            MDReport with synthesized findings
        """
        await self._ensure_kernel()
        
        if credentials_status_counts is None:
            credentials_status_counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
            for response in credentials.values():
                status = response.lookup_status if response.lookup_status in credentials_status_counts else "Lookup Failed"
                credentials_status_counts[status] += 1

        if opportunity_extraction_status != "Parsed" and lookups_executed_count == 0:
            return self._fallback_report(
                trigger,
                research,
                credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
                fallback_reason="extraction_skip",
            )

        # Build prompt variables
        prompt_vars = self._build_prompt_variables(
            trigger,
            research,
            credentials,
            opportunity_extraction_status=opportunity_extraction_status,
            opportunity_extraction_reason=opportunity_extraction_reason,
            opportunities_extracted_count=opportunities_extracted_count,
            lookups_executed_count=lookups_executed_count,
            lookups_skipped_reason=lookups_skipped_reason,
            credentials_status_counts=credentials_status_counts,
            credentials_lookup_mode=credentials_lookup_mode,
            credentials_batch_diagnostics=credentials_batch_diagnostics,
        )
        
        # Fill template
        prompt = self._load_prompt()
        for key, value in prompt_vars.items():
            prompt = prompt.replace("{{$" + key + "}}", value)
        
        try:
            # Call ATLAS via kernel
            from semantic_kernel.contents.chat_history import ChatHistory
            
            history = ChatHistory()
            history.add_user_message(prompt)
            
            chat = self._kernel.get_service("atlas")
            result = await chat.get_chat_message_content(
                chat_history=history,
                settings=self._exec_settings,
                kernel=self._kernel
            )
            
            # Parse JSON response
            response_text = str(result)
            return self._parse_report(
                response_text,
                trigger,
                research,
                credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
            )
            
        except Exception as e:
            logger.exception(f"Synthesis failed: {e}")
            # Return fallback report
            return self._fallback_report(
                trigger,
                research,
                credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
                fallback_reason="synthesis_error",
            )
    
    def _build_prompt_variables(
        self,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str,
        opportunity_extraction_reason: Optional[str],
        opportunities_extracted_count: int,
        lookups_executed_count: int,
        lookups_skipped_reason: Optional[str],
        credentials_status_counts: Dict[str, int],
        credentials_lookup_mode: str,
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics]
    ) -> Dict[str, str]:
        """Build variables for prompt template."""
        # Trigger summary
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.geography:
            trigger_parts.append(f"Geography: {trigger.geography}")
        trigger_summary = "; ".join(trigger_parts)
        
        # Research summary
        research_summary = research.executive_summary or "No executive summary available"
        
        # Opportunities JSON (top 3 for batched credentials parity)
        opps_data = []
        for opp in research.opportunities[:3]:
            opps_data.append({
                "title": opp.title,
                "agency": opp.agency,
                "scope": opp.scope[:200] if opp.scope else "",
                "estimated_value": opp.estimated_value,
                "timeline": opp.timeline,
                "cmmc_level": opp.cmmc_level,
                "confidence": opp.confidence
            })
        
        # Credentials JSON
        creds_data = {}
        for title, resp in credentials.items():
            creds_data[title] = {
                "matches": [
                    {"title": m.title, "value_provided": m.value_provided, "url": m.url}
                    for m in resp.matches[:3]
                ],
                "no_matches_found": resp.no_matches_found,
                "lookup_status": resp.lookup_status,
                "failure_reason": resp.failure_reason
            }
        
        return {
            "trigger_summary": trigger_summary,
            "research_summary": research_summary,
            "opportunities_json": json.dumps(opps_data, indent=2),
            "credentials_json": json.dumps(creds_data, indent=2),
            "extraction_diagnostics_json": json.dumps(
                {
                    "opportunity_extraction_status": opportunity_extraction_status,
                    "opportunity_extraction_reason": opportunity_extraction_reason,
                    "opportunities_extracted_count": opportunities_extracted_count,
                    "lookups_executed_count": lookups_executed_count,
                    "lookups_skipped_reason": lookups_skipped_reason,
                    "credentials_status_counts": credentials_status_counts,
                    "credentials_lookup_mode": credentials_lookup_mode,
                    "credentials_batch_diagnostics": self._batch_diagnostics_for_prompt(
                        credentials_batch_diagnostics
                    ),
                },
                indent=2
            )
        }

    def _batch_diagnostics_for_prompt(
        self,
        diagnostics: Optional[CredentialsBatchDiagnostics]
    ) -> Optional[Dict[str, object]]:
        """Keep prompt diagnostics compact by excluding full I/O payload text."""
        if diagnostics is None:
            return None
        return {
            "invoked": diagnostics.invoked,
            "lookup_count_requested": diagnostics.lookup_count_requested,
            "lookup_count_returned": diagnostics.lookup_count_returned,
            "duration_ms": diagnostics.duration_ms,
            "parse_outcome": diagnostics.parse_outcome,
            "error_type": diagnostics.error_type,
            "error_message": diagnostics.error_message,
        }
    
    def _parse_report(
        self,
        response_text: str,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str,
        opportunity_extraction_reason: Optional[str],
        opportunities_extracted_count: int,
        lookups_executed_count: int,
        lookups_skipped_reason: Optional[str],
        credentials_status_counts: Dict[str, int],
        credentials_lookup_mode: str = "batched_single_call",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
    ) -> MDReport:
        """Parse LLM response into MDReport."""
        try:
            # Extract JSON from response
            json_str = self._extract_json(response_text)
            data = json.loads(json_str)
            
            # Build top opportunities
            top_opps = []
            for opp_data in data.get("top_opportunities", [])[:3]:
                # Find matching original opportunity
                original_opp = self._find_opportunity(
                    opp_data.get("title", ""),
                    research.opportunities
                )
                
                # Build credential matches
                cred_matches = []
                for cred_data in opp_data.get("credentials", []):
                    cred_matches.append(CredentialMatch(
                        title=cred_data.get("title", ""),
                        client_challenge="",
                        value_provided="",
                        url=cred_data.get("url", "")
                    ))

                source_title = (original_opp.title if original_opp else opp_data.get("title", ""))
                source_response = credentials.get(source_title, credentials.get(opp_data.get("title", ""), None))
                lookup_status = source_response.lookup_status if source_response else "No Match"
                if not cred_matches and source_response and source_response.matches:
                    cred_matches = source_response.matches[:2]

                validation_status = opp_data.get("validation_status", "No Internal Data")
                if validation_status not in ("Validated", "Partial", "No Internal Data"):
                    validation_status = "No Internal Data"

                if lookup_status == "Matched":
                    if validation_status == "No Internal Data":
                        validation_status = "Validated" if len(cred_matches) >= 2 else "Partial"
                else:
                    # No Match and Lookup Failed must not be represented as validated.
                    validation_status = "No Internal Data"
                
                top_opps.append(MDReportOpportunity(
                    opportunity=original_opp or Opportunity(
                        title=opp_data.get("title", "Unknown"),
                        scope=opp_data.get("scope", ""),
                        agency=opp_data.get("agency"),
                        estimated_value=opp_data.get("estimated_value"),
                        confidence="Medium"
                    ),
                    credentials=cred_matches,
                    validation_status=validation_status,
                    credentials_lookup_status=lookup_status
                ))
            
            return MDReport(
                trigger_summary=data.get("trigger_summary", ""),
                executive_summary=data.get("executive_summary", ""),
                top_opportunities=top_opps,
                signals_detected=data.get("signals_detected", [])[:5],
                recommended_actions=data.get("recommended_actions", [])[:5],
                generated_at=datetime.now(),
                confidence_note=data.get("confidence_note", ""),
                credentials_evidence=self._build_credentials_evidence(credentials),
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=dict(credentials_status_counts),
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return self._fallback_report(
                trigger,
                research,
                credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
                fallback_reason="parse_error",
            )
    
    def _find_opportunity(self, title: str, opportunities: list) -> Optional[Opportunity]:
        """Find original opportunity by title (fuzzy match)."""
        title_lower = title.lower()
        for opp in opportunities:
            if opp.title.lower() in title_lower or title_lower in opp.title.lower():
                return opp
        return None
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, handling markdown code blocks."""
        text = text.strip()
        
        # Remove markdown code block
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or (not in_block and "{" in line):
                    json_lines.append(line)
            text = "\n".join(json_lines)
        
        # Find JSON boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start >= 0 and end > start:
            return text[start:end]
        
        return text
    
    def _fallback_report(
        self,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str = "Parsed",
        opportunity_extraction_reason: Optional[str] = None,
        opportunities_extracted_count: int = 0,
        lookups_executed_count: int = 0,
        lookups_skipped_reason: Optional[str] = None,
        credentials_status_counts: Optional[Dict[str, int]] = None,
        credentials_lookup_mode: str = "batched_single_call",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
        fallback_reason: str = "synthesis_error",
    ) -> MDReport:
        """Generate fallback report when LLM fails."""
        if (
            fallback_reason == "synthesis_error"
            and opportunity_extraction_status != "Parsed"
            and lookups_executed_count == 0
        ):
            fallback_reason = "extraction_skip"

        # Build opportunities from research
        top_opps = []
        for opp in research.opportunities[:3]:
            cred_resp = credentials.get(opp.title)
            validation = "No Internal Data"
            cred_matches = []
            lookup_status = "No Match"
            
            if cred_resp:
                lookup_status = cred_resp.lookup_status
                if cred_resp.lookup_status == "Matched" and cred_resp.matches:
                    validation = "Validated" if len(cred_resp.matches) >= 2 else "Partial"
                    cred_matches = cred_resp.matches[:2]
            
            top_opps.append(MDReportOpportunity(
                opportunity=opp,
                credentials=cred_matches,
                validation_status=validation,
                credentials_lookup_status=lookup_status
            ))
        
        if credentials_status_counts is None:
            credentials_status_counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
            for response in credentials.values():
                status = response.lookup_status if response.lookup_status in credentials_status_counts else "Lookup Failed"
                credentials_status_counts[status] += 1
        if lookups_executed_count == 0 and credentials:
            lookups_executed_count = len(credentials)

        return MDReport(
            trigger_summary=f"{trigger.sector} research with {', '.join(trigger.signals)} signals",
            executive_summary=self._build_three_block_summary(
                research,
                credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts
            ),
            top_opportunities=top_opps,
            signals_detected=research.signals_detected[:5],
            recommended_actions=research.recommended_actions[:5],
            generated_at=datetime.now(),
            confidence_note=self._fallback_confidence_note(fallback_reason),
            credentials_evidence=self._build_credentials_evidence(credentials),
            opportunity_extraction_status=opportunity_extraction_status,
            opportunity_extraction_reason=opportunity_extraction_reason,
            opportunities_extracted_count=opportunities_extracted_count,
            lookups_executed_count=lookups_executed_count,
            lookups_skipped_reason=lookups_skipped_reason,
            credentials_status_counts=dict(credentials_status_counts),
            credentials_lookup_mode=credentials_lookup_mode,
            credentials_batch_diagnostics=credentials_batch_diagnostics,
        )

    def _fallback_confidence_note(self, fallback_reason: str) -> str:
        if fallback_reason == "extraction_skip":
            return "Report generated with fallback logic after extraction gating."
        if fallback_reason == "parse_error":
            return "Report generated with fallback logic due to synthesis parse error."
        return "Report generated with fallback logic due to synthesis error."

    def _build_three_block_summary(
        self,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str,
        opportunity_extraction_reason: Optional[str],
        lookups_executed_count: int,
        lookups_skipped_reason: Optional[str],
        credentials_status_counts: Dict[str, int]
    ) -> str:
        """Build fixed-format summary with deep research + credentials + combined actions."""
        counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
        for key in counts:
            counts[key] = credentials_status_counts.get(key, 0)

        deep_research_text = research.executive_summary or "No deep research summary was available."
        if lookups_executed_count == 0:
            if opportunity_extraction_status == "Extraction Failed":
                credentials_lines = [
                    "- Lookups executed: 0",
                    f"- Lookup skipped due to extraction failure: {lookups_skipped_reason or opportunity_extraction_reason or 'Opportunity parsing failed.'}",
                ]
            else:
                credentials_lines = [
                    "- Lookups executed: 0",
                    "- No opportunities identified for credentials validation.",
                ]
        else:
            credentials_lines = [
                f"- Lookups executed: {lookups_executed_count}",
                f"- Matched opportunities: {counts['Matched']}",
                f"- No-match opportunities: {counts['No Match']}",
                f"- Lookup failures: {counts['Lookup Failed']}",
            ]
            if counts["Lookup Failed"] > 0:
                failed_titles = [title for title, resp in credentials.items() if resp.lookup_status == "Lookup Failed"]
                credentials_lines.append(f"- Failed lookups: {', '.join(failed_titles[:5])}")

        combined_lines = []
        if research.recommended_actions:
            combined_lines.extend(f"- {action}" for action in research.recommended_actions[:3])
        else:
            combined_lines.append("- Continue targeted opportunity monitoring and refresh signals weekly.")
        if lookups_executed_count == 0 and opportunity_extraction_status == "Extraction Failed":
            combined_lines.append("- Re-run with a canonical opportunities section or improve opportunity extraction patterns before credentials validation.")
        if counts["Lookup Failed"] > 0 and lookups_executed_count > 0:
            combined_lines.append("- Resolve credentials lookup failures before final MD-ready validation.")
        if counts["No Match"] > 0 and lookups_executed_count > 0:
            combined_lines.append("- Prioritize opportunities with stronger internal proof or develop supporting credential narratives.")

        return "\n".join(
            [
                "Deep Research Findings",
                deep_research_text,
                "",
                "Credentials Agent Findings",
                *credentials_lines,
                "",
                "Combined Report & Action Items",
                *combined_lines
            ]
        )

    def _build_credentials_evidence(
        self,
        credentials: Dict[str, CredentialsResponse]
    ) -> list[CredentialsLookupDiagnostics]:
        """Normalize credentials diagnostics for report rendering."""
        evidence: list[CredentialsLookupDiagnostics] = []
        for title, response in credentials.items():
            if response.diagnostics:
                evidence.append(response.diagnostics)
                continue

            evidence.append(
                CredentialsLookupDiagnostics(
                    opportunity_title=title,
                    sector="",
                    query_text="",
                    raw_response_text="",
                    parse_outcome="diagnostics_missing",
                    lookup_status=response.lookup_status,
                    error_message=response.failure_reason,
                    duration_ms=0.0,
                    match_count=len(response.matches)
                )
            )
        return evidence
    
    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if file not found."""
        return """
You are a BD analyst. Synthesize this data into a JSON report:
- Trigger: {{$trigger_summary}}
- Research: {{$research_summary}}
- Opportunities: {{$opportunities_json}}
- Credentials: {{$credentials_json}}

Return JSON with: trigger_summary, executive_summary, top_opportunities, signals_detected, recommended_actions, confidence_note
"""
