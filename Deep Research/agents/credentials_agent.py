"""
Credentials Agent for validating opportunities with internal credentials.

This agent uses the ContextFree API to query the Credentials GPT, which
searches Protiviti's vetted marketing documents for relevant credentials.

Based on the Credentials Agent identity from NextSteps_POC.md:
- Searches approved credentials database
- Provides detailed summaries of matching credentials
- Returns iShare URLs for detail
- Never reveals client names
"""
import os
import json
import logging
from typing import Optional, List

from services.contextfree_client import ContextFreeClient, ContextFreeError
from models.bd_schemas import (
    Opportunity,
    CredentialMatch,
    CredentialsResponse
)

logger = logging.getLogger(__name__)


# =============================================================================
# Prompt Template
# =============================================================================

CREDENTIALS_QUERY_TEMPLATE = """
# Role
You are Protiviti's Credentials Agent, an expert at finding relevant internal credentials.

# Context
I need to validate the following opportunity with Protiviti's internal experience:

**Opportunity Details:**
- Title: {title}
- Scope: {scope}
- Sector/Industry: {sector}
- Key Requirements: {requirements}

# Instructions
1. Search for up to 3 credentials most relevant to this opportunity
2. Prioritize by: industry match > technology match > challenge similarity
3. For each credential, provide:
   - Title: The credential title
   - Client Challenge: What problem the client faced
   - Value Provided: What value Protiviti delivered
   - iShare URL: Link to the full credential

# Constraints
- Never reveal client names (they are confidential)
- Only return approved, vetted credentials
- Do not provide database queries or counts
- Do not make up credentials that don't exist

# Output Format
Respond with a JSON object:
{{
    "matches": [
        {{
            "title": "Credential title",
            "client_challenge": "Problem description",
            "approach": "How it was approached",
            "value_provided": "Value delivered",
            "industry": "Industry sector",
            "technologies_used": ["tech1", "tech2"],
            "url": "https://ishare.protiviti.com/..."
        }}
    ],
    "no_matches_found": false
}}

If no relevant credentials exist, respond with:
{{
    "matches": [],
    "no_matches_found": true
}}
"""


class CredentialsAgent:
    """Agent for finding relevant Protiviti credentials.
    
    Wraps ContextFreeClient to query the Credentials GPT with structured
    prompts and parse responses into typed models.
    
    Example:
        agent = CredentialsAgent.from_env()
        response = await agent.find_credentials(opportunity, sector="Defense")
    """
    
    def __init__(
        self,
        contextfree_client: ContextFreeClient,
        gpt_endpoint: str
    ):
        """Initialize the Credentials Agent.
        
        Args:
            contextfree_client: Client for ContextFree API
            gpt_endpoint: Credentials GPT endpoint URL
        """
        self.client = contextfree_client
        self.gpt_endpoint = gpt_endpoint
    
    @classmethod
    def from_env(cls) -> "CredentialsAgent":
        """Create agent from environment variables."""
        client = ContextFreeClient.from_env()
        gpt_endpoint = os.getenv(
            "CREDENTIALS_GPT_ENDPOINT",
            "https://as-assistant-api.azurewebsites.net/assistantapi/api/OmniInterface/asst_pI1owz6P7CGTuN0nfk0hwXii"
        )
        return cls(client, gpt_endpoint)
    
    async def find_credentials(
        self,
        opportunity: Opportunity,
        sector: str = "General"
    ) -> CredentialsResponse:
        """Find credentials relevant to an opportunity.
        
        Args:
            opportunity: The opportunity to validate
            sector: Industry sector for context
            
        Returns:
            CredentialsResponse with matching credentials or no_matches_found=True
        """
        # Build query from template
        query = self._build_query(opportunity, sector)
        
        try:
            # Query Credentials GPT via ContextFree
            raw_response = await self.client.ask(query, self.gpt_endpoint)
            
            # Parse response
            return self._parse_response(raw_response, opportunity.title)
            
        except ContextFreeError as e:
            logger.error(f"Credentials lookup failed for '{opportunity.title}': {e}")
            # Return graceful failure
            return CredentialsResponse(
                opportunity_title=opportunity.title,
                matches=[],
                no_matches_found=True
            )
        except Exception as e:
            logger.exception(f"Unexpected error in credentials lookup: {e}")
            return CredentialsResponse(
                opportunity_title=opportunity.title,
                matches=[],
                no_matches_found=True
            )
    
    def _build_query(self, opportunity: Opportunity, sector: str) -> str:
        """Build the query string from template and opportunity data."""
        # Extract requirements (CMMC level, compliance, etc.)
        requirements = []
        if opportunity.cmmc_level:
            requirements.append(f"CMMC {opportunity.cmmc_level}")
        if opportunity.scope:
            # Extract key technology terms from scope
            scope_lower = opportunity.scope.lower()
            if "cybersecurity" in scope_lower:
                requirements.append("Cybersecurity")
            if "cloud" in scope_lower:
                requirements.append("Cloud")
            if "compliance" in scope_lower:
                requirements.append("Compliance")
            if "risk" in scope_lower:
                requirements.append("Risk Management")
        
        requirements_str = ", ".join(requirements) if requirements else "N/A"
        
        return CREDENTIALS_QUERY_TEMPLATE.format(
            title=opportunity.title,
            scope=opportunity.scope,
            sector=sector,
            requirements=requirements_str
        )
    
    def _parse_response(self, raw: str, opportunity_title: str) -> CredentialsResponse:
        """Parse GPT response into CredentialsResponse.
        
        Handles both JSON responses and natural language fallback.
        """
        if not raw or not raw.strip():
            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True
            )
        
        # Try to parse as JSON
        try:
            # Handle JSON embedded in markdown code blocks
            json_str = self._extract_json(raw)
            data = json.loads(json_str)
            
            matches = []
            for match_data in data.get("matches", []):
                try:
                    match = CredentialMatch(
                        title=match_data.get("title", "Unknown"),
                        client_challenge=match_data.get("client_challenge", ""),
                        approach=match_data.get("approach", ""),
                        value_provided=match_data.get("value_provided", ""),
                        industry=match_data.get("industry", ""),
                        technologies_used=match_data.get("technologies_used", []),
                        emd=match_data.get("emd"),
                        url=match_data.get("url", "")
                    )
                    matches.append(match)
                except Exception as e:
                    logger.warning(f"Failed to parse credential match: {e}")
                    continue
            
            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=matches,
                no_matches_found=data.get("no_matches_found", len(matches) == 0)
            )
            
        except json.JSONDecodeError:
            # Fallback: check for "no matching credentials" in natural language
            raw_lower = raw.lower()
            if "no matching" in raw_lower or "no relevant" in raw_lower or "could not find" in raw_lower:
                return CredentialsResponse(
                    opportunity_title=opportunity_title,
                    matches=[],
                    no_matches_found=True
                )
            
            # Can't parse - log and return empty
            logger.warning(f"Could not parse credentials response: {raw[:200]}...")
            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True
            )
    
    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, handling markdown code blocks."""
        text = text.strip()
        
        # Remove markdown code block if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Skip first line (```json) and last line (```)
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        
        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        
        if start >= 0 and end > start:
            return text[start:end]
        
        return text
