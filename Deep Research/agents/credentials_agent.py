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
from time import perf_counter
from typing import Optional, List, Dict, Tuple

from services.contextfree_client import ContextFreeClient, ContextFreeError
from models.bd_schemas import (
    Opportunity,
    CredentialMatch,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
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

BATCH_CREDENTIALS_QUERY_TEMPLATE = """
# Role
You are Protiviti's Credentials Agent, an expert at finding relevant internal credentials.

# Context
I need to validate multiple opportunities with Protiviti's internal experience.

Sector/Industry: {sector}
Max matches per opportunity: {max_matches}

Opportunities:
{opportunities_block}

# Instructions
1. For each opportunity, search up to {max_matches} credentials most relevant to that specific opportunity.
2. Prioritize relevance by: industry match > technology match > challenge similarity.
3. Keep opportunity groupings separate by `opportunity_id`.
4. Do not combine or pool matches across opportunities.
5. Keep responses concise to avoid truncation:
   - `client_challenge`, `approach`, and `value_provided` each max ~220 characters.
6. Do NOT output markdown code fences.
7. Do NOT truncate with ellipses (`...`).
8. Return result objects for all listed opportunities.

# Constraints
- Never reveal client names.
- Only return approved, vetted credentials.
- Do not provide database queries or counts.
- Do not fabricate credentials.

# Output Format
Respond ONLY with valid JSON:
{{
  "results": [
    {{
      "opportunity_id": "opp_1",
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
  ]
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
        start_time = perf_counter()

        # Build query from template
        query = self._build_query(opportunity, sector)
        
        try:
            # Query Credentials GPT via ContextFree
            raw_response = await self.client.ask(query, self.gpt_endpoint)
            
            # Parse response
            duration_ms = (perf_counter() - start_time) * 1000
            return self._parse_response(
                raw_response,
                opportunity.title,
                sector=sector,
                query_text=query,
                duration_ms=duration_ms
            )
            
        except ContextFreeError as e:
            logger.error(f"Credentials lookup failed for '{opportunity.title}': {e}")
            return self._build_failure_response(
                opportunity_title=opportunity.title,
                sector=sector,
                query_text=query,
                error=e,
                duration_ms=(perf_counter() - start_time) * 1000
            )
        except Exception as e:
            logger.exception(f"Unexpected error in credentials lookup: {e}")
            return self._build_failure_response(
                opportunity_title=opportunity.title,
                sector=sector,
                query_text=query,
                error=e,
                duration_ms=(perf_counter() - start_time) * 1000
            )

    async def find_credentials_batch(
        self,
        opportunities: List[Opportunity],
        sector: str,
        max_matches_per_opportunity: int = 3
    ) -> Tuple[Dict[str, CredentialsResponse], CredentialsBatchDiagnostics]:
        """Run one batched credentials lookup for multiple opportunities."""
        requested = opportunities[:3]
        start_time = perf_counter()
        if not requested:
            diagnostics = CredentialsBatchDiagnostics(
                invoked=False,
                lookup_count_requested=0,
                lookup_count_returned=0,
                parse_outcome="no_opportunities",
            )
            return {}, diagnostics

        query = self._build_batch_query(requested, sector, max_matches_per_opportunity)
        try:
            raw_response = await self.client.ask(query, self.gpt_endpoint)
            duration_ms = (perf_counter() - start_time) * 1000
            return self._parse_batch_response(
                raw_response=raw_response,
                opportunities=requested,
                sector=sector,
                query_text=query,
                duration_ms=duration_ms,
                max_matches_per_opportunity=max_matches_per_opportunity,
            )
        except Exception as e:
            duration_ms = (perf_counter() - start_time) * 1000
            logger.error("Batch credentials lookup failed: %s", e)
            diagnostics = CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=len(requested),
                lookup_count_returned=0,
                duration_ms=duration_ms,
                query_text=query,
                raw_response_text="",
                parse_outcome="batch_lookup_failed",
                error_type=type(e).__name__,
                error_message=str(e),
            )
            return self._build_batch_failure_map(
                requested,
                sector,
                query,
                str(e),
                f"batch_lookup_failed:{type(e).__name__}",
                duration_ms,
            ), diagnostics

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

    def _build_batch_query(
        self,
        opportunities: List[Opportunity],
        sector: str,
        max_matches_per_opportunity: int
    ) -> str:
        """Build a single batch query for up to three opportunities."""
        lines = []
        for idx, opportunity in enumerate(opportunities, 1):
            opp_id = f"opp_{idx}"
            requirements = self._extract_requirements(opportunity)
            lines.extend(
                [
                    f"- opportunity_id: {opp_id}",
                    f"  title: {opportunity.title}",
                    f"  scope: {opportunity.scope}",
                    f"  key_requirements: {requirements}",
                ]
            )

        return BATCH_CREDENTIALS_QUERY_TEMPLATE.format(
            sector=sector,
            max_matches=max_matches_per_opportunity,
            opportunities_block="\n".join(lines),
        )

    def _extract_requirements(self, opportunity: Opportunity) -> str:
        requirements: List[str] = []
        if opportunity.cmmc_level:
            requirements.append(f"CMMC {opportunity.cmmc_level}")
        if opportunity.scope:
            scope_lower = opportunity.scope.lower()
            if "cybersecurity" in scope_lower:
                requirements.append("Cybersecurity")
            if "cloud" in scope_lower:
                requirements.append("Cloud")
            if "compliance" in scope_lower:
                requirements.append("Compliance")
            if "risk" in scope_lower:
                requirements.append("Risk Management")
        return ", ".join(requirements) if requirements else "N/A"

    def _parse_batch_response(
        self,
        raw_response: str,
        opportunities: List[Opportunity],
        sector: str,
        query_text: str,
        duration_ms: float,
        max_matches_per_opportunity: int
    ) -> Tuple[Dict[str, CredentialsResponse], CredentialsBatchDiagnostics]:
        id_to_opp = {f"opp_{idx}": opp for idx, opp in enumerate(opportunities, 1)}
        if not raw_response or not raw_response.strip():
            diagnostics = CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=len(opportunities),
                lookup_count_returned=0,
                duration_ms=duration_ms,
                query_text=query_text,
                raw_response_text=raw_response or "",
                parse_outcome="empty_response",
            )
            return self._build_batch_failure_map(
                opportunities,
                sector,
                query_text,
                "Batch credentials response was empty.",
                "batch_empty_response",
                duration_ms,
            ), diagnostics

        try:
            payload = json.loads(self._extract_json(raw_response))
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise json.JSONDecodeError("results must be a list", raw_response, 0)

            response_map: Dict[str, CredentialsResponse] = {}
            returned = 0
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                opp_id = entry.get("opportunity_id")
                opp = id_to_opp.get(opp_id)
                if opp is None:
                    continue
                returned += 1
                matches = self._coerce_matches(entry.get("matches", []), max_matches_per_opportunity)
                has_matches = len(matches) > 0
                status = "Matched" if has_matches else "No Match"
                parse_outcome = "batch_json_parsed_with_matches" if has_matches else "batch_json_parsed_no_match"
                diagnostics = CredentialsLookupDiagnostics(
                    opportunity_title=opp.title,
                    sector=sector,
                    query_text=query_text,
                    raw_response_text=raw_response,
                    parse_outcome=parse_outcome,
                    lookup_status=status,
                    duration_ms=duration_ms,
                    match_count=len(matches),
                )
                response_map[opp.title] = CredentialsResponse(
                    opportunity_title=opp.title,
                    matches=matches,
                    no_matches_found=entry.get("no_matches_found", not has_matches),
                    lookup_status=status,
                    diagnostics=diagnostics,
                )

            for opp in opportunities:
                if opp.title in response_map:
                    continue
                diagnostics = CredentialsLookupDiagnostics(
                    opportunity_title=opp.title,
                    sector=sector,
                    query_text=query_text,
                    raw_response_text=raw_response,
                    parse_outcome="batch_missing_opportunity_result",
                    lookup_status="Lookup Failed",
                    error_message="Missing result for opportunity in batch response.",
                    duration_ms=duration_ms,
                    match_count=0,
                )
                response_map[opp.title] = CredentialsResponse(
                    opportunity_title=opp.title,
                    matches=[],
                    no_matches_found=True,
                    lookup_status="Lookup Failed",
                    failure_reason="Missing result for opportunity in batch response.",
                    diagnostics=diagnostics,
                )

            batch_diagnostics = CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=len(opportunities),
                lookup_count_returned=returned,
                duration_ms=duration_ms,
                query_text=query_text,
                raw_response_text=raw_response,
                parse_outcome="batch_json_parsed",
            )
            return response_map, batch_diagnostics
        except json.JSONDecodeError as e:
            recovered_results = self._recover_batch_results(raw_response)
            if recovered_results:
                logger.warning(
                    "Recovered %d partial batch results after JSON parse failure.",
                    len(recovered_results),
                )
                response_map: Dict[str, CredentialsResponse] = {}
                id_to_opp = {f"opp_{idx}": opp for idx, opp in enumerate(opportunities, 1)}
                for entry in recovered_results:
                    opp_id = entry.get("opportunity_id")
                    opp = id_to_opp.get(opp_id)
                    if opp is None:
                        continue
                    matches = self._coerce_matches(entry.get("matches", []), max_matches_per_opportunity)
                    has_matches = len(matches) > 0
                    status = "Matched" if has_matches else "No Match"
                    diagnostics = CredentialsLookupDiagnostics(
                        opportunity_title=opp.title,
                        sector=sector,
                        query_text=query_text,
                        raw_response_text=raw_response,
                        parse_outcome="batch_partial_recovery",
                        lookup_status=status,
                        duration_ms=duration_ms,
                        match_count=len(matches),
                    )
                    response_map[opp.title] = CredentialsResponse(
                        opportunity_title=opp.title,
                        matches=matches,
                        no_matches_found=entry.get("no_matches_found", not has_matches),
                        lookup_status=status,
                        diagnostics=diagnostics,
                    )

                for opp in opportunities:
                    if opp.title in response_map:
                        continue
                    diagnostics = CredentialsLookupDiagnostics(
                        opportunity_title=opp.title,
                        sector=sector,
                        query_text=query_text,
                        raw_response_text=raw_response,
                        parse_outcome="batch_partial_recovery_missing_opportunity",
                        lookup_status="Lookup Failed",
                        error_message="Batch response was truncated before this opportunity result completed.",
                        duration_ms=duration_ms,
                        match_count=0,
                    )
                    response_map[opp.title] = CredentialsResponse(
                        opportunity_title=opp.title,
                        matches=[],
                        no_matches_found=True,
                        lookup_status="Lookup Failed",
                        failure_reason="Batch response was truncated before this opportunity result completed.",
                        diagnostics=diagnostics,
                    )

                diagnostics = CredentialsBatchDiagnostics(
                    invoked=True,
                    lookup_count_requested=len(opportunities),
                    lookup_count_returned=len(recovered_results),
                    duration_ms=duration_ms,
                    query_text=query_text,
                    raw_response_text=raw_response,
                    parse_outcome="batch_partial_recovery",
                    error_type="JSONDecodeError",
                    error_message=str(e),
                )
                return response_map, diagnostics

            diagnostics = CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=len(opportunities),
                lookup_count_returned=0,
                duration_ms=duration_ms,
                query_text=query_text,
                raw_response_text=raw_response,
                parse_outcome="batch_json_parse_error",
                error_type="JSONDecodeError",
                error_message=str(e),
            )
            return self._build_batch_failure_map(
                opportunities,
                sector,
                query_text,
                "Could not parse batch credentials response as JSON.",
                "batch_json_parse_error",
                duration_ms,
                raw_response=raw_response,
            ), diagnostics

    def _recover_batch_results(self, raw_response: str) -> List[Dict[str, object]]:
        """Recover fully-formed result objects from a partially truncated JSON payload."""
        extracted = self._extract_json(raw_response)
        if not extracted:
            return []

        results_idx = extracted.find('"results"')
        if results_idx < 0:
            return []
        array_start = extracted.find("[", results_idx)
        if array_start < 0:
            return []

        recovered: List[Dict[str, object]] = []
        in_string = False
        escape = False
        object_depth = 0
        object_start: Optional[int] = None

        for idx in range(array_start + 1, len(extracted)):
            ch = extracted[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                if object_depth == 0:
                    object_start = idx
                object_depth += 1
                continue

            if ch == "}":
                if object_depth > 0:
                    object_depth -= 1
                if object_depth == 0 and object_start is not None:
                    candidate = extracted[object_start:idx + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            recovered.append(parsed)
                    except json.JSONDecodeError:
                        pass
                    object_start = None
                continue

            if ch == "]" and object_depth == 0:
                break

        return recovered

    def _coerce_matches(self, raw_matches: object, max_matches: int) -> List[CredentialMatch]:
        matches: List[CredentialMatch] = []
        if not isinstance(raw_matches, list):
            return matches
        for match_data in raw_matches:
            if not isinstance(match_data, dict):
                continue
            try:
                matches.append(
                    CredentialMatch(
                        title=match_data.get("title", "Unknown"),
                        client_challenge=match_data.get("client_challenge", ""),
                        approach=match_data.get("approach", ""),
                        value_provided=match_data.get("value_provided", ""),
                        industry=match_data.get("industry", ""),
                        technologies_used=match_data.get("technologies_used", []),
                        emd=match_data.get("emd"),
                        url=match_data.get("url", ""),
                    )
                )
            except Exception as e:
                logger.warning("Failed to parse batch credential match: %s", e)
            if len(matches) >= max_matches:
                break
        return matches

    def _build_batch_failure_map(
        self,
        opportunities: List[Opportunity],
        sector: str,
        query_text: str,
        failure_reason: str,
        parse_outcome: str,
        duration_ms: float,
        raw_response: str = "",
    ) -> Dict[str, CredentialsResponse]:
        results: Dict[str, CredentialsResponse] = {}
        for opp in opportunities:
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_title=opp.title,
                sector=sector,
                query_text=query_text,
                raw_response_text=raw_response,
                parse_outcome=parse_outcome,
                lookup_status="Lookup Failed",
                error_message=failure_reason,
                duration_ms=duration_ms,
                match_count=0,
            )
            results[opp.title] = CredentialsResponse(
                opportunity_title=opp.title,
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason=failure_reason,
                diagnostics=diagnostics,
            )
        return results
    
    def _parse_response(
        self,
        raw: str,
        opportunity_title: str,
        sector: str = "General",
        query_text: str = "",
        duration_ms: float = 0.0
    ) -> CredentialsResponse:
        """Parse GPT response into CredentialsResponse.
        
        Handles both JSON responses and natural language fallback.
        """
        if not raw or not raw.strip():
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_title=opportunity_title,
                sector=sector,
                query_text=query_text,
                raw_response_text=raw or "",
                parse_outcome="empty_response",
                lookup_status="No Match",
                duration_ms=duration_ms,
                match_count=0
            )
            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True,
                lookup_status="No Match",
                diagnostics=diagnostics
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

            has_matches = len(matches) > 0
            lookup_status = "Matched" if has_matches else "No Match"
            parse_outcome = "json_parsed_with_matches" if has_matches else "json_parsed_no_matches"

            if data.get("no_matches_found", False):
                parse_outcome = "json_explicit_no_match"

            diagnostics = CredentialsLookupDiagnostics(
                opportunity_title=opportunity_title,
                sector=sector,
                query_text=query_text,
                raw_response_text=raw,
                parse_outcome=parse_outcome,
                lookup_status=lookup_status,
                duration_ms=duration_ms,
                match_count=len(matches)
            )

            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=matches,
                no_matches_found=data.get("no_matches_found", len(matches) == 0),
                lookup_status=lookup_status,
                diagnostics=diagnostics
            )
            
        except json.JSONDecodeError:
            # Fallback: check for "no matching credentials" in natural language
            raw_lower = raw.lower()
            if "no matching" in raw_lower or "no relevant" in raw_lower or "could not find" in raw_lower:
                diagnostics = CredentialsLookupDiagnostics(
                    opportunity_title=opportunity_title,
                    sector=sector,
                    query_text=query_text,
                    raw_response_text=raw,
                    parse_outcome="natural_language_no_match",
                    lookup_status="No Match",
                    duration_ms=duration_ms,
                    match_count=0
                )
                return CredentialsResponse(
                    opportunity_title=opportunity_title,
                    matches=[],
                    no_matches_found=True,
                    lookup_status="No Match",
                    diagnostics=diagnostics
                )
            
            # Can't parse - log and return empty
            logger.warning(f"Could not parse credentials response: {raw[:200]}...")
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_title=opportunity_title,
                sector=sector,
                query_text=query_text,
                raw_response_text=raw,
                parse_outcome="json_parse_error",
                lookup_status="Lookup Failed",
                error_type="JSONDecodeError",
                error_message="Could not parse credentials response as JSON.",
                duration_ms=duration_ms,
                match_count=0
            )
            return CredentialsResponse(
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Could not parse credentials response as JSON.",
                diagnostics=diagnostics
            )

    def _build_failure_response(
        self,
        opportunity_title: str,
        sector: str,
        query_text: str,
        error: Exception,
        duration_ms: float
    ) -> CredentialsResponse:
        """Build a deterministic lookup failure response with diagnostics."""
        diagnostics = CredentialsLookupDiagnostics(
            opportunity_title=opportunity_title,
            sector=sector,
            query_text=query_text,
            raw_response_text="",
            parse_outcome="lookup_failed",
            lookup_status="Lookup Failed",
            error_type=type(error).__name__,
            error_message=str(error),
            duration_ms=duration_ms,
            match_count=0
        )
        return CredentialsResponse(
            opportunity_title=opportunity_title,
            matches=[],
            no_matches_found=True,
            lookup_status="Lookup Failed",
            failure_reason=str(error),
            diagnostics=diagnostics
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
