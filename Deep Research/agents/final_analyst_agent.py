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
        credentials: Dict[str, CredentialsResponse]
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
        
        # Build prompt variables
        prompt_vars = self._build_prompt_variables(trigger, research, credentials)
        
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
            return self._parse_report(response_text, trigger, research, credentials)
            
        except Exception as e:
            logger.exception(f"Synthesis failed: {e}")
            # Return fallback report
            return self._fallback_report(trigger, research, credentials)
    
    def _build_prompt_variables(
        self,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse]
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
        
        # Opportunities JSON (top 5)
        opps_data = []
        for opp in research.opportunities[:5]:
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
                "no_matches_found": resp.no_matches_found
            }
        
        return {
            "trigger_summary": trigger_summary,
            "research_summary": research_summary,
            "opportunities_json": json.dumps(opps_data, indent=2),
            "credentials_json": json.dumps(creds_data, indent=2)
        }
    
    def _parse_report(
        self,
        response_text: str,
        trigger: BDTrigger,
        research: DeepResearchOutput,
        credentials: Dict[str, CredentialsResponse]
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
                
                top_opps.append(MDReportOpportunity(
                    opportunity=original_opp or Opportunity(
                        title=opp_data.get("title", "Unknown"),
                        scope=opp_data.get("scope", ""),
                        agency=opp_data.get("agency"),
                        estimated_value=opp_data.get("estimated_value"),
                        confidence="Medium"
                    ),
                    credentials=cred_matches,
                    validation_status=opp_data.get("validation_status", "No Internal Data")
                ))
            
            return MDReport(
                trigger_summary=data.get("trigger_summary", ""),
                executive_summary=data.get("executive_summary", ""),
                top_opportunities=top_opps,
                signals_detected=data.get("signals_detected", [])[:5],
                recommended_actions=data.get("recommended_actions", [])[:5],
                generated_at=datetime.now(),
                confidence_note=data.get("confidence_note", "")
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            return self._fallback_report(trigger, research, credentials)
    
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
        credentials: Dict[str, CredentialsResponse]
    ) -> MDReport:
        """Generate fallback report when LLM fails."""
        # Build opportunities from research
        top_opps = []
        for opp in research.opportunities[:3]:
            cred_resp = credentials.get(opp.title)
            validation = "No Internal Data"
            cred_matches = []
            
            if cred_resp and cred_resp.matches:
                validation = "Validated" if len(cred_resp.matches) >= 2 else "Partial"
                cred_matches = cred_resp.matches[:2]
            
            top_opps.append(MDReportOpportunity(
                opportunity=opp,
                credentials=cred_matches,
                validation_status=validation
            ))
        
        return MDReport(
            trigger_summary=f"{trigger.sector} research with {', '.join(trigger.signals)} signals",
            executive_summary=research.executive_summary or "Analysis complete. See opportunities below.",
            top_opportunities=top_opps,
            signals_detected=research.signals_detected[:5],
            recommended_actions=research.recommended_actions[:5],
            generated_at=datetime.now(),
            confidence_note="Report generated with fallback logic due to synthesis error."
        )
    
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
