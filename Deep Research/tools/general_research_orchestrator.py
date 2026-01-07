"""
General Research Orchestrator - Handles non-company-specific research requests.

This module provides orchestration for general research tasks like market
overviews, industry analysis, regulatory updates, and other broad topics.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple
from models.schemas import Citation
from agents.bing_data_extraction_agent import BingDataExtractionAgent

logger = logging.getLogger(__name__)

class GeneralResearchOrchestrator:
    """Orchestrates general research tasks using Bing agent."""
    
    def __init__(self, bing_agent: BingDataExtractionAgent):
        self.bing_agent = bing_agent
        logger.info("GeneralResearchOrchestrator initialized")
    
    async def execute_general_research(self, target: str, parameters: Dict[str, Any] = None) -> Tuple[str, List[Citation]]:
        """
        Execute general research based on target and parameters.
        
        Args:
            target: The research target/topic
            parameters: Additional parameters for the research
            
        Returns:
            Tuple of (summary, citations)
        """
        parameters = parameters or {}
        logger.info(f"Executing general research: {target}")
        
        try:
            # Determine research strategy based on parameters
            strategy = self._determine_research_strategy(target, parameters)
            
            # Execute the research
            result = await self._execute_research_strategy(strategy, target, parameters)
            
            # Extract summary and citations
            summary = result.get("summary", "")
            citations = self._extract_citations(result.get("citations_md", ""))
            
            logger.info(f"General research completed - {len(citations)} citations found")
            return summary, citations
            
        except Exception as e:
            logger.exception("General research failed during strategy '%s' for target '%s'", strategy if 'strategy' in locals() else "unknown", target)
            return f"I couldn't complete the research on '{target}'. Please try rephrasing your question.", []
    
    def _determine_research_strategy(self, target: str, parameters: Dict[str, Any]) -> str:
        """Determine the best research strategy based on target and parameters."""
        scope = parameters.get("scope", "general")
        industry = parameters.get("industry")
        location = parameters.get("location")
        limit = parameters.get("limit", 10)
        
        # Market overview/ranking requests
        if scope == "market_overview" or "top" in target.lower() or "ranking" in target.lower():
            if industry and location:
                return "market_overview_location"
            elif industry:
                return "market_overview_industry"
            else:
                return "market_overview_general"
        
        # Industry analysis requests
        elif "industry" in target.lower() or "sector" in target.lower():
            return "industry_analysis"
        
        # Regulatory updates
        elif "regulatory" in target.lower() or "regulation" in target.lower():
            return "regulatory_updates"
        
        # Technology trends
        elif "technology" in target.lower() or "tech" in target.lower() or "AI" in target.lower():
            return "technology_trends"
        
        # Competitor analysis
        elif "competitor" in target.lower() or "competition" in target.lower():
            return "competitor_analysis"
        
        # General topic research
        else:
            return "general_topic"
    
    async def _execute_research_strategy(self, strategy: str, target: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the research using the determined strategy."""
        industry = (parameters.get("industry") or "").strip() or None
        location = self._infer_location(target, parameters.get("location"))
        limit = self._normalize_limit(parameters.get("limit"))

        if strategy == "market_overview_location":
            return self.bing_agent.search_financial_companies_by_location(location, limit)

        elif strategy == "market_overview_industry":
            return self.bing_agent.search_market_overview(industry, location, limit)

        elif strategy == "market_overview_general":
            category = parameters.get("category")
            if not category:
                category = self._infer_category(target)
            return self.bing_agent.search_market_rankings(category, location, limit)
        
        elif strategy == "industry_analysis":
            return self.bing_agent.search_industry_analysis(industry or target, location)
        
        elif strategy == "regulatory_updates":
            return self.bing_agent.search_regulatory_updates(industry or "financial services", location)
        
        elif strategy == "technology_trends":
            return self.bing_agent.search_technology_trends(industry)
        
        elif strategy == "competitor_analysis":
            # Extract company name from target if possible
            company = self._extract_company_from_target(target)
            if company:
                return self.bing_agent.search_competitor_analysis(company)
            else:
                return self.bing_agent.search_general_topic(target)
        
        else:  # general_topic
            return self.bing_agent.search_general_topic(target)

    def _extract_company_from_target(self, target: str) -> Optional[str]:
        """Extract company name from target string for competitor analysis."""
        # Simple extraction - look for common patterns
        import re
        
        # Look for "competitors of X" pattern
        match = re.search(r"competitors? of ([^,]+)", target, re.I)
        if match:
            return match.group(1).strip()
        
        # Look for "X competitors" pattern
        match = re.search(r"([^,]+) competitors?", target, re.I)
        if match:
            return match.group(1).strip()
        
        return None

    def _normalize_limit(self, value: Optional[Any], default: int = 10) -> int:
        if value is None:
            return default
        try:
            limit = int(value)
            return limit if limit > 0 else default
        except (TypeError, ValueError):
            return default

    def _infer_location(self, target: str, explicit_location: Optional[Any]) -> Optional[str]:
        if explicit_location:
            return str(explicit_location).strip()

        target_lower = target.lower()
        if " united states" in target_lower or " in the us" in target_lower or " in us" in target_lower:
            return "United States"
        if " in europe" in target_lower:
            return "Europe"
        if " in asia" in target_lower:
            return "Asia"
        return None

    def _infer_category(self, target: str) -> str:
        text = target.lower()
        if "bank holding" in text:
            return "bank holding companies"
        if "bank" in text:
            return "banks"
        if "insurance" in text:
            return "insurance companies"
        if "fintech" in text:
            return "fintech companies"
        return "companies"
    
    def _extract_citations(self, citations_md: str) -> List[Citation]:
        """Extract citations from markdown format."""
        citations = []
        if not citations_md:
            return citations
        
        import re
        for line in citations_md.splitlines():
            line = line.strip()
            if not line.startswith('- ['):
                continue
            
            # Match markdown format: - [title](url)
            match = re.match(r'^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)', line)
            if match:
                try:
                    citations.append(Citation(
                        title=match.group('title'),
                        url=match.group('url')
                    ))
                except Exception as e:
                    logger.warning(f"Failed to create citation: {e}")
                    continue
        
        return citations

# Global instance (will be initialized with bing_agent)
general_research_orchestrator = None

def initialize_general_research_orchestrator(bing_agent: BingDataExtractionAgent):
    """Initialize the global general research orchestrator."""
    global general_research_orchestrator
    general_research_orchestrator = GeneralResearchOrchestrator(bing_agent)
    logger.info("Global general research orchestrator initialized")
    return general_research_orchestrator
