"""
Final Analyst Agent for synthesizing BD research into MD Reports.

Uses ATLAS/Semantic Kernel to generate concise, actionable reports
combining Deep Research findings with Credentials validation.

The agent follows the existing kernel_setup.py pattern with ATLASClient.
"""
import os
import json
import logging
import re
from datetime import datetime, date
from typing import Optional, Dict, Any, List
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
    CredentialMatch,
    SignalEvidence,
    PhaseOpportunity,
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
        credentials_lookup_mode: str = "serial_per_opportunity",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
        confirmed_signal_evidence: Optional[List[SignalEvidence]] = None,
        phase3_candidates: Optional[List[PhaseOpportunity]] = None,
        allowed_sources: Optional[List[str]] = None,
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
                confirmed_signal_evidence=confirmed_signal_evidence,
                phase3_candidates=phase3_candidates,
                allowed_sources=allowed_sources,
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
            confirmed_signal_evidence=confirmed_signal_evidence,
            phase3_candidates=phase3_candidates,
            allowed_sources=allowed_sources,
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
                confirmed_signal_evidence=confirmed_signal_evidence,
                phase3_candidates=phase3_candidates,
                allowed_sources=allowed_sources,
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
                confirmed_signal_evidence=confirmed_signal_evidence,
                phase3_candidates=phase3_candidates,
                allowed_sources=allowed_sources,
                fallback_reason="synthesis_error",
                fallback_error_message=str(e),
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
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics],
        confirmed_signal_evidence: Optional[List[SignalEvidence]],
        phase3_candidates: Optional[List[PhaseOpportunity]],
        allowed_sources: Optional[List[str]],
    ) -> Dict[str, str]:
        """Build variables for prompt template."""
        # Trigger summary
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.user_prompt_context:
            trigger_parts.append(f"User Prompt Context: {trigger.user_prompt_context}")
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
            "user_prompt_context": self._sanitize_prompt_context(trigger.user_prompt_context, max_chars=600),
            "current_date_iso": datetime.now().date().isoformat(),
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
            ),
            "confirmed_signals_json": json.dumps(
                [
                    item.model_dump() if hasattr(item, "model_dump") else item.__dict__
                    for item in (confirmed_signal_evidence or [])
                ],
                indent=2,
            ),
            "phase3_candidates_json": json.dumps(
                [
                    item.model_dump() if hasattr(item, "model_dump") else item.__dict__
                    for item in (phase3_candidates or [])
                ],
                indent=2,
            ),
            "allowed_sources_json": json.dumps(allowed_sources or [], indent=2),
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
        credentials_lookup_mode: str = "serial_per_opportunity",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
        confirmed_signal_evidence: Optional[List[SignalEvidence]] = None,
        phase3_candidates: Optional[List[PhaseOpportunity]] = None,
        allowed_sources: Optional[List[str]] = None,
    ) -> MDReport:
        """Parse LLM response into MDReport."""
        try:
            today = datetime.now().date()
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
                source_response = self._resolve_credentials_response(
                    opp_title=str(opp_data.get("title", "")),
                    original_opp=original_opp,
                    credentials=credentials,
                )
                lookup_status = source_response.lookup_status if source_response else "No Match"

                if source_response and lookup_status == "Matched" and source_response.matches:
                    # Canonical source of truth is parsed Credentials Agent output.
                    cred_matches = source_response.matches[:2]
                else:
                    # Do not consume LLM-provided credential stubs when canonical lookup is absent/no-match.
                    cred_matches = []

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
            
            parsed_phase2_signal_evidence = self._parse_phase2_signal_evidence(
                data.get("phase2_signal_evidence"),
                fallback=confirmed_signal_evidence,
            )
            parsed_phase3_opportunities = self._parse_phase3_opportunities(
                data.get("phase3_opportunities"),
                fallback=phase3_candidates,
            )
            parsed_phase3_opportunities = self._sanitize_phase3_opportunities(
                parsed_phase3_opportunities,
                today=today,
            )
            parsed_phase_sources = self._parse_phase_sources(
                data.get("phase_sources"),
                fallback=allowed_sources,
            )
            parsed_layout_version = data.get("layout_version")
            if not parsed_layout_version and (parsed_phase2_signal_evidence or parsed_phase3_opportunities):
                parsed_layout_version = "fs_evidence_locked_v1"

            normalized_executive_summary = self._normalize_executive_summary(
                summary=data.get("executive_summary", ""),
                top_opportunities=top_opps,
                research=research,
                credentials=credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
            )

            return MDReport(
                trigger_summary=data.get("trigger_summary", ""),
                executive_summary=normalized_executive_summary,
                top_opportunities=top_opps,
                signals_detected=data.get("signals_detected", [])[:5],
                recommended_actions=self._sanitize_recommended_actions(
                    data.get("recommended_actions", [])[:5],
                    today=today,
                ),
                generated_at=datetime.now(),
                confidence_note=data.get("confidence_note", ""),
                synthesis_status="synthesized",
                synthesis_fallback_reason=None,
                synthesis_error_message=None,
                credentials_evidence=self._build_credentials_evidence(credentials),
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                opportunities_extracted_count=opportunities_extracted_count,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=dict(credentials_status_counts),
                credentials_lookup_mode=credentials_lookup_mode,
                credentials_batch_diagnostics=credentials_batch_diagnostics,
                phase2_headline=data.get("phase2_headline"),
                phase2_signal_evidence=parsed_phase2_signal_evidence,
                phase2_footnotes=self._parse_phase2_footnotes(
                    data.get("phase2_footnotes"),
                    fallback_signal_evidence=parsed_phase2_signal_evidence,
                ),
                phase3_opportunities=parsed_phase3_opportunities,
                phase_sources=parsed_phase_sources,
                layout_version=parsed_layout_version,
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
                confirmed_signal_evidence=confirmed_signal_evidence,
                phase3_candidates=phase3_candidates,
                allowed_sources=allowed_sources,
                fallback_reason="parse_error",
                fallback_error_message=str(e),
            )
    
    def _find_opportunity(self, title: str, opportunities: list) -> Optional[Opportunity]:
        """Find original opportunity by title (fuzzy match)."""
        title_lower = title.lower()
        for opp in opportunities:
            if opp.title.lower() in title_lower or title_lower in opp.title.lower():
                return opp
        return None

    def _resolve_credentials_response(
        self,
        opp_title: str,
        original_opp: Optional[Opportunity],
        credentials: Dict[str, CredentialsResponse],
    ) -> Optional[CredentialsResponse]:
        """Resolve canonical credentials response even when synthesis rewrites/truncates titles."""
        candidates = [opp_title, original_opp.title if original_opp else ""]
        for candidate in candidates:
            if candidate and candidate in credentials:
                return credentials[candidate]

        signal_codes: List[str] = []
        for candidate in candidates:
            code = self._extract_signal_code(candidate)
            if code and code not in signal_codes:
                signal_codes.append(code)
        for signal_code in signal_codes:
            scoped = [
                (title, response)
                for title, response in credentials.items()
                if self._extract_signal_code(title) == signal_code
            ]
            if len(scoped) == 1:
                return scoped[0][1]
            if scoped:
                scoped.sort(key=lambda item: len(item[0]), reverse=True)
                return scoped[0][1]

        normalized_targets = [
            self._normalize_lookup_key(candidate)
            for candidate in candidates
            if candidate
        ]
        normalized_targets = [target for target in normalized_targets if target]
        if not normalized_targets:
            return None

        fuzzy_hits: List[tuple[str, CredentialsResponse]] = []
        for title, response in credentials.items():
            normalized_title = self._normalize_lookup_key(title)
            if not normalized_title:
                continue
            if any(
                normalized_title in normalized_target or normalized_target in normalized_title
                for normalized_target in normalized_targets
            ):
                fuzzy_hits.append((title, response))

        if len(fuzzy_hits) == 1:
            return fuzzy_hits[0][1]
        if fuzzy_hits:
            fuzzy_hits.sort(key=lambda item: len(item[0]), reverse=True)
            return fuzzy_hits[0][1]
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
        credentials_lookup_mode: str = "serial_per_opportunity",
        credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = None,
        confirmed_signal_evidence: Optional[List[SignalEvidence]] = None,
        phase3_candidates: Optional[List[PhaseOpportunity]] = None,
        allowed_sources: Optional[List[str]] = None,
        fallback_reason: str = "synthesis_error",
        fallback_error_message: Optional[str] = None,
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
            recommended_actions=self._sanitize_recommended_actions(
                research.recommended_actions[:5],
                today=datetime.now().date(),
            ),
            generated_at=datetime.now(),
            confidence_note=self._fallback_confidence_note(fallback_reason),
            synthesis_status="fallback",
            synthesis_fallback_reason=fallback_reason,
            synthesis_error_message=fallback_error_message,
            credentials_evidence=self._build_credentials_evidence(credentials),
            opportunity_extraction_status=opportunity_extraction_status,
            opportunity_extraction_reason=opportunity_extraction_reason,
            opportunities_extracted_count=opportunities_extracted_count,
            lookups_executed_count=lookups_executed_count,
            lookups_skipped_reason=lookups_skipped_reason,
            credentials_status_counts=dict(credentials_status_counts),
            credentials_lookup_mode=credentials_lookup_mode,
            credentials_batch_diagnostics=credentials_batch_diagnostics,
            phase2_headline=self._fallback_phase2_headline(confirmed_signal_evidence),
            phase2_signal_evidence=confirmed_signal_evidence or None,
            phase2_footnotes=self._fallback_phase2_footnotes(confirmed_signal_evidence),
            phase3_opportunities=self._sanitize_phase3_opportunities(
                phase3_candidates,
                today=datetime.now().date(),
            ),
            phase_sources=(list(allowed_sources) if allowed_sources else None),
            layout_version="fs_evidence_locked_v1" if confirmed_signal_evidence or phase3_candidates else None,
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
            ]

        combined_lines = []
        if research.recommended_actions:
            sanitized_actions = self._sanitize_recommended_actions(
                research.recommended_actions[:3],
                today=datetime.now().date(),
            )
            combined_lines.extend(f"- {action}" for action in sanitized_actions)
        else:
            combined_lines.append("- Continue targeted opportunity monitoring and refresh signals weekly.")
        if lookups_executed_count == 0 and opportunity_extraction_status == "Extraction Failed":
            combined_lines.append("- Re-run with a canonical opportunities section or improve opportunity extraction patterns before credentials validation.")
        if counts["No Match"] > 0 and lookups_executed_count > 0:
            combined_lines.append("- Prioritize opportunities with stronger internal proof or develop supporting credential narratives.")

        top_matches_line = self._format_top_matches_from_responses(credentials)
        summary_lines: List[str] = [
            "Deep Research Findings",
            deep_research_text,
            "",
            "Credentials Agent Findings",
            *credentials_lines,
        ]
        if top_matches_line:
            summary_lines.append(f"- Top matched credentials by opportunity: {top_matches_line}")
        summary_lines.extend(
            [
                "",
                "Combined Report & Action Items",
                *combined_lines,
            ]
        )
        return "\n".join(summary_lines)

    def _normalize_executive_summary(
        self,
        summary: str,
        top_opportunities: List[MDReportOpportunity],
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse],
        opportunity_extraction_status: str,
        opportunity_extraction_reason: Optional[str],
        lookups_executed_count: int,
        lookups_skipped_reason: Optional[str],
        credentials_status_counts: Dict[str, int],
    ) -> str:
        """Ensure executive summary includes stable three-block contract + credentials specifics."""
        parsed = self._split_three_block_summary(summary)
        if not parsed:
            return self._build_three_block_summary(
                research=research,
                credentials=credentials,
                opportunity_extraction_status=opportunity_extraction_status,
                opportunity_extraction_reason=opportunity_extraction_reason,
                lookups_executed_count=lookups_executed_count,
                lookups_skipped_reason=lookups_skipped_reason,
                credentials_status_counts=credentials_status_counts,
            )

        credentials_text = parsed["Credentials Agent Findings"]
        credentials_text = self._strip_failure_lines(credentials_text)
        credentials_text = self._ensure_credentials_counts_lines(
            credentials_text=credentials_text,
            credentials_status_counts=credentials_status_counts,
            lookups_executed_count=lookups_executed_count,
            lookups_skipped_reason=lookups_skipped_reason,
        )
        credentials_text = self._ensure_top_matched_line(
            credentials_text=credentials_text,
            top_opportunities=top_opportunities,
        )
        combined_text = self._strip_failure_lines(
            parsed["Combined Report & Action Items"],
            include_lookup_count_lines=False,
        )

        return "\n".join(
            [
                "Deep Research Findings",
                parsed["Deep Research Findings"],
                "",
                "Credentials Agent Findings",
                credentials_text,
                "",
                "Combined Report & Action Items",
                combined_text,
            ]
        ).strip()

    def _strip_failure_lines(
        self,
        text: str,
        include_lookup_count_lines: bool = True,
    ) -> str:
        """Remove failure-oriented demo-facing lines while keeping core summary context."""
        if not text:
            return ""

        blocked_tokens = [
            "failed lookups",
            "resolve credentials lookup failures",
            "credentials lookup failures",
        ]
        if include_lookup_count_lines:
            blocked_tokens.append("lookup failures")

        kept: List[str] = []
        for line in text.splitlines():
            lowered = line.strip().lower()
            if any(token in lowered for token in blocked_tokens):
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _split_three_block_summary(self, summary: str) -> Optional[Dict[str, str]]:
        """Split summary into required titled blocks if contract headings are present."""
        text = (summary or "").strip()
        headings = [
            "Deep Research Findings",
            "Credentials Agent Findings",
            "Combined Report & Action Items",
        ]
        positions = []
        start_cursor = 0
        for heading in headings:
            pos = text.find(heading, start_cursor)
            if pos < 0:
                return None
            positions.append(pos)
            start_cursor = pos + len(heading)

        sections: Dict[str, str] = {}
        for index, heading in enumerate(headings):
            section_start = positions[index] + len(heading)
            section_end = positions[index + 1] if index + 1 < len(positions) else len(text)
            sections[heading] = text[section_start:section_end].strip()
        return sections

    def _ensure_credentials_counts_lines(
        self,
        credentials_text: str,
        credentials_status_counts: Dict[str, int],
        lookups_executed_count: int,
        lookups_skipped_reason: Optional[str],
    ) -> str:
        """Inject deterministic counts lines when synthesis omitted them."""
        normalized = (credentials_text or "").strip()
        lowered = normalized.lower()

        required_markers = [
            "matched opportunities",
            "no-match opportunities",
        ]
        has_all_markers = all(marker in lowered for marker in required_markers)
        if has_all_markers:
            return normalized

        counts_lines: List[str] = []
        if lookups_executed_count == 0:
            counts_lines.append("- Lookups executed: 0")
            counts_lines.append(
                f"- Lookup skipped: {lookups_skipped_reason or 'No opportunities identified for credentials validation.'}"
            )
        else:
            counts_lines.extend(
                [
                    f"- Lookups executed: {lookups_executed_count}",
                    f"- Matched opportunities: {credentials_status_counts.get('Matched', 0)}",
                    f"- No-match opportunities: {credentials_status_counts.get('No Match', 0)}",
                ]
            )

        if not normalized:
            return "\n".join(counts_lines)
        return "\n".join([normalized, *counts_lines]).strip()

    def _ensure_top_matched_line(
        self,
        credentials_text: str,
        top_opportunities: List[MDReportOpportunity],
    ) -> str:
        """Inject top matched credentials line for validated opportunities when omitted."""
        normalized = (credentials_text or "").strip()
        if "top matched credentials by opportunity" in normalized.lower():
            return normalized

        details = self._format_top_matches_from_top_opportunities(top_opportunities)
        if not details:
            return normalized

        line = f"- Top matched credentials by opportunity: {details}"
        if not normalized:
            return line
        return "\n".join([normalized, line]).strip()

    def _format_top_matches_from_top_opportunities(
        self,
        top_opportunities: List[MDReportOpportunity],
    ) -> str:
        chunks: List[str] = []
        for item in top_opportunities:
            if item.credentials_lookup_status != "Matched" or not item.credentials:
                continue
            titles = [cred.title for cred in item.credentials[:2] if cred.title]
            if not titles:
                continue
            chunks.append(f"{item.opportunity.title} -> {', '.join(titles)}")
        return "; ".join(chunks)

    def _format_top_matches_from_responses(
        self,
        credentials: Dict[str, CredentialsResponse],
    ) -> str:
        chunks: List[str] = []
        for title, response in credentials.items():
            if response.lookup_status != "Matched" or not response.matches:
                continue
            match_titles = [match.title for match in response.matches[:2] if match.title]
            if not match_titles:
                continue
            chunks.append(f"{title} -> {', '.join(match_titles)}")
        return "; ".join(chunks)

    def _fallback_phase2_headline(
        self,
        signal_evidence: Optional[List[SignalEvidence]]
    ) -> Optional[str]:
        if not signal_evidence:
            return None
        confirmed = [item for item in signal_evidence if item.status == "Confirmed"]
        if confirmed:
            return (
                "Validated public evidence indicates governance and regulatory execution pressure "
                "across confirmed financial-services signals."
            )
        return "Available evidence did not produce confirmed financial-services signals in this run."

    def _fallback_phase2_footnotes(
        self,
        signal_evidence: Optional[List[SignalEvidence]]
    ) -> Optional[List[str]]:
        if not signal_evidence:
            return None
        normalized = self._normalize_phase2_footnotes(
            raw_footnotes=[],
            signal_evidence=signal_evidence,
        )
        return normalized or None

    def _format_structured_phase2_footnote(
        self,
        quote: str,
        source_title: str,
        canonical_url: str,
        evidentiary_linkage: str,
    ) -> str:
        return "\n".join(
            [
                f"Verbatim quote: {quote or '(Not provided)'}",
                f"Source title: {source_title or '(Not provided)'}",
                f"Canonical URL: {canonical_url or '(Not provided)'}",
                f"Evidentiary linkage: {evidentiary_linkage or '(Not provided)'}",
            ]
        )

    def _extract_structured_footnote_fields(self, footnote: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for line in (footnote or "").splitlines():
            raw = line.strip()
            if not raw:
                continue
            lowered = raw.lower()
            if lowered.startswith("verbatim quote:"):
                fields["quote"] = raw.split(":", 1)[1].strip()
            elif lowered.startswith("source title:"):
                fields["title"] = raw.split(":", 1)[1].strip()
            elif lowered.startswith("canonical url:"):
                fields["url"] = raw.split(":", 1)[1].strip()
            elif lowered.startswith("evidentiary linkage:"):
                fields["linkage"] = raw.split(":", 1)[1].strip()
        return fields

    def _default_evidentiary_linkage(self, item: SignalEvidence) -> str:
        analysis = (item.analysis or "").strip()
        if analysis:
            first_sentence = re.split(r"(?<=[.!?])\s+", analysis)[0].strip()
            if first_sentence:
                return first_sentence
        signal_label = item.signal_label or item.signal_code
        return f"Supports confirmed evidence for {signal_label}."

    def _normalize_phase2_footnotes(
        self,
        raw_footnotes: List[str],
        signal_evidence: Optional[List[SignalEvidence]],
    ) -> List[str]:
        confirmed = [item for item in (signal_evidence or []) if item.status == "Confirmed"]
        normalized: List[str] = []

        if confirmed:
            for index, item in enumerate(confirmed):
                raw_footnote = raw_footnotes[index] if index < len(raw_footnotes) else ""
                fields = self._extract_structured_footnote_fields(raw_footnote)
                quote = fields.get("quote") or (item.evidence_quote or "").strip() or "(Not provided)"
                source_title = fields.get("title") or (item.source_title or "").strip() or (item.source_url or "").strip() or "(Not provided)"
                canonical_url = fields.get("url") or (item.source_url or "").strip() or "(Not provided)"
                evidentiary_linkage = fields.get("linkage") or self._default_evidentiary_linkage(item)
                normalized.append(
                    self._format_structured_phase2_footnote(
                        quote=quote,
                        source_title=source_title,
                        canonical_url=canonical_url,
                        evidentiary_linkage=evidentiary_linkage,
                    )
                )
            return normalized

        for footnote in raw_footnotes:
            fields = self._extract_structured_footnote_fields(footnote)
            compact = (footnote or "").strip()
            normalized.append(
                self._format_structured_phase2_footnote(
                    quote=fields.get("quote", "(Not provided)"),
                    source_title=fields.get("title", "(Not provided)"),
                    canonical_url=fields.get("url", "(Not provided)"),
                    evidentiary_linkage=fields.get("linkage", compact or "(Not provided)"),
                )
            )
        return normalized

    def _parse_phase2_signal_evidence(
        self,
        raw: Any,
        fallback: Optional[List[SignalEvidence]]
    ) -> Optional[List[SignalEvidence]]:
        if isinstance(raw, list):
            parsed: List[SignalEvidence] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status", "Insufficient")).title()
                if status not in {"Confirmed", "Insufficient", "Rejected"}:
                    status = "Insufficient"
                signal_code = str(item.get("signal_code", "")).strip()
                signal_label = str(item.get("signal_label", "")).strip() or signal_code
                if not signal_code:
                    continue
                parsed.append(
                    SignalEvidence(
                        signal_code=signal_code,
                        signal_label=signal_label,
                        status=status,  # type: ignore[arg-type]
                        evidence_quote=str(item.get("evidence_quote", "")).strip(),
                        source_url=str(item.get("source_url", "")).strip(),
                        source_title=str(item.get("source_title", "")).strip() or None,
                        analysis=str(item.get("analysis", "")).strip(),
                    )
                )
            if parsed:
                return parsed
        return fallback or None

    def _parse_phase2_footnotes(
        self,
        raw: Any,
        fallback_signal_evidence: Optional[List[SignalEvidence]] = None,
    ) -> Optional[List[str]]:
        parsed: List[str] = []
        if isinstance(raw, list):
            parsed = [str(item).strip() for item in raw if str(item).strip()]
        normalized = self._normalize_phase2_footnotes(
            raw_footnotes=parsed,
            signal_evidence=fallback_signal_evidence,
        )
        if normalized:
            return normalized
        return self._fallback_phase2_footnotes(fallback_signal_evidence)

    def _parse_phase3_opportunities(
        self,
        raw: Any,
        fallback: Optional[List[PhaseOpportunity]]
    ) -> Optional[List[PhaseOpportunity]]:
        if isinstance(raw, list):
            parsed: List[PhaseOpportunity] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                derived_from_signal = str(item.get("derived_from_signal", "")).strip()
                if not derived_from_signal:
                    continue
                service_lines = item.get("relevant_service_lines")
                if isinstance(service_lines, list):
                    normalized_service_lines = [str(value).strip() for value in service_lines if str(value).strip()]
                else:
                    normalized_service_lines = []
                actions = item.get("recommended_actions")
                if isinstance(actions, list):
                    normalized_actions = [str(value).strip() for value in actions if str(value).strip()]
                else:
                    normalized_actions = []
                sources = item.get("sources")
                if isinstance(sources, list):
                    normalized_sources = [str(value).strip() for value in sources if str(value).strip()]
                else:
                    normalized_sources = []
                parsed.append(
                    PhaseOpportunity(
                        derived_from_signal=derived_from_signal,
                        overview=str(item.get("overview", "")).strip(),
                        technical_explanation=str(item.get("technical_explanation", "")).strip(),
                        layman_explanation=str(item.get("layman_explanation", "")).strip(),
                        relevant_service_lines=normalized_service_lines,
                        credentials_summary=str(item.get("credentials_summary", "")).strip(),
                        recommended_actions=normalized_actions,
                        sources=normalized_sources,
                    )
                )
            if parsed:
                return parsed
        return fallback or None

    def _sanitize_phase3_opportunities(
        self,
        opportunities: Optional[List[PhaseOpportunity]],
        today: date,
    ) -> Optional[List[PhaseOpportunity]]:
        if not opportunities:
            return opportunities

        sanitized: List[PhaseOpportunity] = []
        for item in opportunities:
            sanitized.append(
                item.model_copy(
                    update={
                        "recommended_actions": self._sanitize_recommended_actions(
                            item.recommended_actions,
                            today=today,
                        )
                    }
                )
            )
        return sanitized

    def _parse_phase_sources(self, raw: Any, fallback: Optional[List[str]]) -> Optional[List[str]]:
        merged: List[str] = []
        seen = set()

        for source in (fallback or []):
            normalized = str(source).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)

        if isinstance(raw, list):
            for source in raw:
                normalized = str(source).strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                merged.append(normalized)

        return merged or None

    def _sanitize_prompt_context(self, value: Optional[str], max_chars: int = 600) -> str:
        text = re.sub(r"\s+", " ", (value or "").strip())
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        truncated = text[: max_chars + 1]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        return truncated.rstrip()

    def _sanitize_recommended_actions(self, actions: List[str], today: date) -> List[str]:
        sanitized: List[str] = []
        current_quarter = ((today.month - 1) // 3) + 1
        month_lookup = {
            "jan": 1, "january": 1,
            "feb": 2, "february": 2,
            "mar": 3, "march": 3,
            "apr": 4, "april": 4,
            "may": 5,
            "jun": 6, "june": 6,
            "jul": 7, "july": 7,
            "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10,
            "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }
        temporal_prefixes = (
            "late ",
            "early ",
            "mid ",
            "by ",
            "in ",
            "during ",
            "through ",
            "from ",
            "before ",
        )

        quarter_range_pattern = re.compile(r"\bQ([1-4])\s*[-–]\s*Q([1-4])\s+(\d{4})\b", re.IGNORECASE)
        single_quarter_pattern = re.compile(r"\bQ([1-4])\s+(\d{4})\b", re.IGNORECASE)
        year_range_pattern = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})\b")
        month_year_pattern = re.compile(
            r"\b("
            r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
            r")\s+(\d{4})\b",
            re.IGNORECASE,
        )

        def _extend_start_for_prefix(source_text: str, start_index: int) -> int:
            lowered = source_text.lower()
            for prefix in temporal_prefixes:
                prefix_start = start_index - len(prefix)
                if prefix_start >= 0 and lowered[prefix_start:start_index] == prefix:
                    return prefix_start
            return start_index

        for action in actions:
            text = str(action or "").strip()
            if not text:
                continue

            stale_ranges: List[tuple[int, int]] = []

            def add_range(start: int, end: int) -> None:
                for existing_start, existing_end in stale_ranges:
                    if start < existing_end and existing_start < end:
                        return
                stale_ranges.append((start, end))

            for match in quarter_range_pattern.finditer(text):
                start_q = int(match.group(1))
                year = int(match.group(3))
                if year < today.year or (year == today.year and start_q < current_quarter):
                    add_range(_extend_start_for_prefix(text, match.start()), match.end())

            for match in single_quarter_pattern.finditer(text):
                quarter = int(match.group(1))
                year = int(match.group(2))
                if year < today.year or (year == today.year and quarter < current_quarter):
                    add_range(_extend_start_for_prefix(text, match.start()), match.end())

            for match in year_range_pattern.finditer(text):
                start_year = int(match.group(1))
                end_year = int(match.group(2))
                if start_year > end_year:
                    start_year, end_year = end_year, start_year
                # Any range beginning in the past is considered stale for action planning guidance.
                if start_year < today.year or end_year < today.year:
                    add_range(_extend_start_for_prefix(text, match.start()), match.end())

            for match in month_year_pattern.finditer(text):
                month_token = match.group(1).lower()
                year = int(match.group(2))
                month = month_lookup.get(month_token, month_lookup.get(month_token[:3], 0))
                if year < today.year or (year == today.year and month and month < today.month):
                    add_range(_extend_start_for_prefix(text, match.start()), match.end())

            for match in re.finditer(r"\b(19|20)\d{2}\b", text):
                year = int(match.group(0))
                if year < today.year:
                    add_range(_extend_start_for_prefix(text, match.start()), match.end())

            if stale_ranges:
                replacement = "within the next 30-90 days"
                for start, end in sorted(stale_ranges, key=lambda x: x[0], reverse=True):
                    text = f"{text[:start]}{replacement}{text[end:]}"
                text = re.sub(
                    r"\b(?:by|in|during|through|from|before)\s+within the next 30-90 days\b",
                    "within the next 30-90 days",
                    text,
                    flags=re.IGNORECASE,
                )
                text = re.sub(
                    r"\b(?:late|early|mid)\s+within the next 30-90 days\b",
                    "within the next 30-90 days",
                    text,
                    flags=re.IGNORECASE,
                )
                text = re.sub(r"\s{2,}", " ", text).strip()

            sanitized.append(text)

        return sanitized

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
