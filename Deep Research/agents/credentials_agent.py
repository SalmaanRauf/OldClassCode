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
import re
import asyncio
import logging
from urllib.parse import urlparse
from time import perf_counter
from typing import Optional, List, Dict, Tuple, Set

from services.contextfree_client import ContextFreeClient, ContextFreeError
from models.bd_schemas import (
    Opportunity,
    CredentialMatch,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
)

logger = logging.getLogger(__name__)
MAX_SINGLE_MATCHES = 3


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
{search_context_block}

# Instructions
1. Search for up to {max_matches} credentials most relevant to this opportunity
2. Prioritize by: {ranking_priorities}
3. For each credential, provide:
   - Title: The credential title
   - Client Challenge: What problem the client faced
   - Value Provided: What value Protiviti delivered
   - iShare URL: Link to the full credential
{why_relevant_instruction}

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
            "why_relevant": "Short explanation of why this credential fits",
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
2. Prioritize relevance by: {ranking_priorities}.
3. Keep opportunity groupings separate by `opportunity_id`.
4. Do not combine or pool matches across opportunities.
5. Keep responses concise to avoid truncation:
   - `client_challenge`, `approach`, and `value_provided` each max ~220 characters.
   - `why_relevant` max ~180 characters when requested.
6. Do NOT output markdown code fences.
7. Do NOT truncate with ellipses (`...`).
8. Return result objects for all listed opportunities.
{why_relevant_instruction}

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
            "why_relevant": "Short explanation of why this credential fits",
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
        self._batch_timeout_retry_backoff_seconds = 1.0
    
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
        max_matches = self._max_matches_for_opportunity(opportunity)

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
                opportunity_id=self._opportunity_identity(opportunity),
                sector=sector,
                query_text=query,
                duration_ms=duration_ms,
                max_matches=max_matches,
            )
            
        except ContextFreeError as e:
            logger.error(f"Credentials lookup failed for '{opportunity.title}': {e}")
            return self._build_failure_response(
                opportunity_title=opportunity.title,
                opportunity_id=self._opportunity_identity(opportunity),
                sector=sector,
                query_text=query,
                error=e,
                duration_ms=(perf_counter() - start_time) * 1000
            )
        except Exception as e:
            logger.exception(f"Unexpected error in credentials lookup: {e}")
            return self._build_failure_response(
                opportunity_title=opportunity.title,
                opportunity_id=self._opportunity_identity(opportunity),
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

        effective_max_matches = self._max_matches_for_batch(requested, max_matches_per_opportunity)
        query = self._build_batch_query(requested, sector, effective_max_matches)
        try:
            raw_response = await self.client.ask(query, self.gpt_endpoint)
            duration_ms = (perf_counter() - start_time) * 1000
            return self._parse_batch_response(
                raw_response=raw_response,
                opportunities=requested,
                sector=sector,
                query_text=query,
                duration_ms=duration_ms,
                max_matches_per_opportunity=effective_max_matches,
            )
        except Exception as first_error:
            if not self._is_timeout_like_error(first_error):
                duration_ms = (perf_counter() - start_time) * 1000
                logger.error("Batch credentials lookup failed: %s", first_error)
                diagnostics = CredentialsBatchDiagnostics(
                    invoked=True,
                    lookup_count_requested=len(requested),
                    lookup_count_returned=0,
                    duration_ms=duration_ms,
                    query_text=query,
                    raw_response_text="",
                    parse_outcome="batch_lookup_failed",
                    error_type=type(first_error).__name__,
                    error_message=str(first_error),
                )
                return self._build_batch_failure_map(
                    requested,
                    sector,
                    query,
                    str(first_error),
                    f"batch_lookup_failed:{type(first_error).__name__}",
                    duration_ms,
                ), diagnostics

            logger.warning(
                "Batch credentials lookup timed out. Retrying once in %.1fs.",
                self._batch_timeout_retry_backoff_seconds,
            )
            await asyncio.sleep(self._batch_timeout_retry_backoff_seconds)
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
            except Exception as second_error:
                duration_ms = (perf_counter() - start_time) * 1000
                if self._is_timeout_like_error(second_error):
                    logger.warning(
                        "Batch credentials lookup timed out after retry; executing serial fallback."
                    )
                    response_map: Dict[str, CredentialsResponse] = {}
                    for idx, opportunity in enumerate(requested, 1):
                        key = self._batch_response_key(opportunity)
                        response = await self.find_credentials(
                            opportunity,
                            sector=sector,
                        )
                        response.opportunity_id = key
                        response_map[key] = response

                    diagnostics = CredentialsBatchDiagnostics(
                        invoked=True,
                        lookup_count_requested=len(requested),
                        lookup_count_returned=len(response_map),
                        duration_ms=duration_ms,
                        query_text=query,
                        raw_response_text="",
                        parse_outcome="batch_timeout_fallback_serial",
                        error_type=type(second_error).__name__,
                        error_message=(
                            "Batch credentials lookup timed out after retry; "
                            "serial fallback executed."
                        ),
                    )
                    return response_map, diagnostics

                logger.error("Batch credentials lookup failed after retry: %s", second_error)
                diagnostics = CredentialsBatchDiagnostics(
                    invoked=True,
                    lookup_count_requested=len(requested),
                    lookup_count_returned=0,
                    duration_ms=duration_ms,
                    query_text=query,
                    raw_response_text="",
                    parse_outcome="batch_lookup_failed",
                    error_type=type(second_error).__name__,
                    error_message=str(second_error),
                )
                return self._build_batch_failure_map(
                    requested,
                    sector,
                    query,
                    str(second_error),
                    f"batch_lookup_failed:{type(second_error).__name__}",
                    duration_ms,
                ), diagnostics

    def _build_query(self, opportunity: Opportunity, sector: str) -> str:
        """Build the query string from template and opportunity data."""
        requirements_str = self._extract_requirements(opportunity)
        max_matches = self._max_matches_for_opportunity(opportunity)
        ranking_priorities = self._ranking_priorities_for_opportunity(opportunity)
        search_context_block = self._build_search_context_block(opportunity)
        why_relevant_instruction = self._why_relevant_instruction(opportunity)
        return CREDENTIALS_QUERY_TEMPLATE.format(
            title=opportunity.title,
            scope=opportunity.scope,
            sector=sector,
            requirements=requirements_str,
            max_matches=max_matches,
            ranking_priorities=ranking_priorities,
            search_context_block=search_context_block,
            why_relevant_instruction=why_relevant_instruction,
        )

    def _build_batch_query(
        self,
        opportunities: List[Opportunity],
        sector: str,
        max_matches_per_opportunity: int
    ) -> str:
        """Build a single batch query for up to three opportunities."""
        effective_max_matches = self._max_matches_for_batch(opportunities, max_matches_per_opportunity)
        lines = []
        for idx, opportunity in enumerate(opportunities, 1):
            opp_id = self._opportunity_identity(opportunity, idx)
            requirements = self._extract_requirements(opportunity)
            truncated_scope = self._truncate_scope_for_batch(opportunity.scope)
            search_context = self._build_batch_search_context_line(opportunity)
            lines.extend(
                [
                    f"- opportunity_id: {opp_id}",
                    f"  title: {opportunity.title}",
                    f"  scope: {truncated_scope}",
                    f"  key_requirements: {requirements}",
                    *([f"  search_context: {search_context}"] if search_context else []),
                ]
            )

        return BATCH_CREDENTIALS_QUERY_TEMPLATE.format(
            sector=sector,
            max_matches=effective_max_matches,
            ranking_priorities=self._ranking_priorities_for_batch(opportunities),
            why_relevant_instruction=self._why_relevant_instruction_for_batch(opportunities),
            opportunities_block="\n".join(lines),
        )

    def _truncate_scope_for_batch(self, scope: str, max_chars: int = 350) -> str:
        text = (scope or "").strip()
        if len(text) <= max_chars:
            return text

        truncated = text[: max_chars + 1]
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        truncated = truncated.rstrip()
        if not truncated:
            truncated = text[:max_chars].rstrip()
        return f"{truncated}..."

    def _max_matches_for_opportunity(self, opportunity: Opportunity) -> int:
        return 2 if getattr(opportunity, "credential_search_context", None) else MAX_SINGLE_MATCHES

    def _max_matches_for_batch(
        self,
        opportunities: List[Opportunity],
        requested_max_matches: int,
    ) -> int:
        if opportunities and all(getattr(opportunity, "credential_search_context", None) for opportunity in opportunities):
            return min(requested_max_matches, 2)
        return requested_max_matches

    def _ranking_priorities_for_opportunity(self, opportunity: Opportunity) -> str:
        if getattr(opportunity, "credential_search_context", None):
            return (
                "industry/subindustry fit > role-family fit > buyer-priority fit > "
                "likely-client-need fit > challenge similarity > technology similarity"
            )
        return "industry match > technology match > challenge similarity"

    def _ranking_priorities_for_batch(self, opportunities: List[Opportunity]) -> str:
        if opportunities and all(getattr(opportunity, "credential_search_context", None) for opportunity in opportunities):
            return (
                "industry/subindustry fit > role-family fit > buyer-priority fit > "
                "likely-client-need fit > challenge similarity > technology similarity"
            )
        return "industry match > technology match > challenge similarity"

    def _why_relevant_instruction(self, opportunity: Opportunity) -> str:
        if not getattr(opportunity, "credential_search_context", None):
            return ""
        return (
            "   - Why Relevant: One sentence explaining why the credential fits the role, industry, "
            "and likely buying need\n"
        )

    def _why_relevant_instruction_for_batch(self, opportunities: List[Opportunity]) -> str:
        if not opportunities or not all(getattr(opportunity, "credential_search_context", None) for opportunity in opportunities):
            return ""
        return (
            "9. Include `why_relevant` for each credential with one sentence focused on role, industry, "
            "and likely buying need."
        )

    def _build_search_context_block(self, opportunity: Opportunity) -> str:
        search_context = getattr(opportunity, "credential_search_context", None)
        if not search_context:
            return ""
        priorities = ", ".join(list(getattr(search_context, "buyer_priorities", []) or [])[:5]) or "N/A"
        likely_needs = ", ".join(list(getattr(search_context, "likely_client_needs", []) or [])[:4]) or "N/A"
        account_signals = ", ".join(list(getattr(search_context, "account_signals", []) or [])[:5]) or "N/A"
        lines = [
            "",
            "**Structured Search Context:**",
            f"- Buyer/Person: {getattr(search_context, 'person_name', '')}",
            f"- Buyer Role: {getattr(search_context, 'person_title', '')}",
            f"- Company: {getattr(search_context, 'company_name', '')}",
            f"- Industry: {getattr(search_context, 'industry', '') or 'General'}",
        ]
        subindustry = str(getattr(search_context, "subindustry", "") or "").strip()
        if subindustry:
            lines.append(f"- Subindustry: {subindustry}")
        lines.extend(
            [
                f"- Role Family: {getattr(search_context, 'role_family', '') or 'general'}",
                f"- Buyer Priorities: {priorities}",
                f"- Likely Client Needs: {likely_needs}",
                f"- Account Signals: {account_signals}",
                f"- Selection Reason: {getattr(search_context, 'selection_reason', '') or 'Selected for movement credentials lookup'}",
            ]
        )
        return "\n".join(lines)

    def _build_batch_search_context_line(self, opportunity: Opportunity) -> str:
        search_context = getattr(opportunity, "credential_search_context", None)
        if not search_context:
            return ""
        parts = [
            f"buyer={str(getattr(search_context, 'person_name', '') or '').strip()}",
            f"role={str(getattr(search_context, 'person_title', '') or '').strip()}",
            f"industry={str(getattr(search_context, 'industry', '') or '').strip()}",
            f"subindustry={str(getattr(search_context, 'subindustry', '') or '').strip()}",
            f"role_family={str(getattr(search_context, 'role_family', '') or '').strip()}",
            "buyer_priorities=" + "; ".join(list(getattr(search_context, "buyer_priorities", []) or [])[:4]),
            "likely_client_needs=" + "; ".join(list(getattr(search_context, "likely_client_needs", []) or [])[:4]),
            "account_signals=" + "; ".join(list(getattr(search_context, "account_signals", []) or [])[:4]),
            f"selection_reason={str(getattr(search_context, 'selection_reason', '') or '').strip()}",
        ]
        return " | ".join(part for part in parts if part and not part.endswith("="))

    def _is_timeout_like_error(self, error: Exception) -> bool:
        message = str(error).lower()
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
            "internal server error",
            "internalservererror",
            "http error 500",
            "status code 500",
            "request failed with status code internalservererror",
            "unable to create chat session",
            "failed to create chat session",
        )
        return any(marker in message for marker in retryable_markers)

    def _extract_requirements(self, opportunity: Opportunity) -> str:
        requirements: List[str] = []
        normalized_cmmc = self._normalize_cmmc_requirement(opportunity.cmmc_level)
        if normalized_cmmc:
            requirements.append(normalized_cmmc)
        search_context = getattr(opportunity, "credential_search_context", None)
        if search_context:
            requirements.extend(list(getattr(search_context, "likely_client_needs", []) or [])[:2])
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
        normalized = []
        seen = set()
        for value in requirements:
            text = str(value or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            normalized.append(text)
        return ", ".join(normalized) if normalized else "N/A"

    def _normalize_cmmc_requirement(self, level: Optional[str]) -> Optional[str]:
        """Normalize CMMC requirement text to canonical Level formatting."""
        if level is None:
            return None

        raw = str(level).strip()
        if not raw:
            return None

        level_match = re.match(r"(?i)^level\s+(\d+)(.*)$", raw)
        if level_match:
            suffix = level_match.group(2).strip()
            return f"CMMC Level {level_match.group(1)}{f' {suffix}' if suffix else ''}"

        numeric_match = re.match(r"^(\d+)(.*)$", raw)
        if numeric_match:
            suffix = numeric_match.group(2).strip()
            return f"CMMC Level {numeric_match.group(1)}{f' {suffix}' if suffix else ''}"

        cmmc_level_match = re.match(r"(?i)^cmmc\s+level\s+(\d+)(.*)$", raw)
        if cmmc_level_match:
            suffix = cmmc_level_match.group(2).strip()
            return f"CMMC Level {cmmc_level_match.group(1)}{f' {suffix}' if suffix else ''}"

        cmmc_numeric_match = re.match(r"(?i)^cmmc\s+(\d+)(.*)$", raw)
        if cmmc_numeric_match:
            suffix = cmmc_numeric_match.group(2).strip()
            return f"CMMC Level {cmmc_numeric_match.group(1)}{f' {suffix}' if suffix else ''}"

        cmmc_prefixed_match = re.match(r"(?i)^cmmc\s+(.*)$", raw)
        if cmmc_prefixed_match:
            return f"CMMC {cmmc_prefixed_match.group(1).strip()}"

        return f"CMMC {raw}"

    def _parse_batch_response(
        self,
        raw_response: str,
        opportunities: List[Opportunity],
        sector: str,
        query_text: str,
        duration_ms: float,
        max_matches_per_opportunity: int
    ) -> Tuple[Dict[str, CredentialsResponse], CredentialsBatchDiagnostics]:
        id_to_opp = {self._opportunity_identity(opp, idx): opp for idx, opp in enumerate(opportunities, 1)}
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
                raw_response=raw_response or "",
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
                opp_id = str(entry.get("opportunity_id", "") or "").strip()
                opp = id_to_opp.get(opp_id)
                if opp is None:
                    continue
                returned += 1
                response_key = self._batch_response_key(opp)
                matches, filtered_invalid_url_count = self._coerce_matches(
                    entry.get("matches", []),
                    max_matches_per_opportunity,
                )
                has_matches = len(matches) > 0
                status = "Matched" if has_matches else "No Match"
                if has_matches and filtered_invalid_url_count > 0:
                    parse_outcome = "batch_json_parsed_with_matches_filtered_invalid_url"
                elif has_matches:
                    parse_outcome = "batch_json_parsed_with_matches"
                elif filtered_invalid_url_count > 0:
                    parse_outcome = "batch_json_parsed_all_matches_filtered_invalid_url"
                else:
                    parse_outcome = "batch_json_parsed_no_match"
                diagnostics = CredentialsLookupDiagnostics(
                    opportunity_id=opp_id,
                    opportunity_title=opp.title,
                    sector=sector,
                    query_text=query_text,
                    raw_response_text=raw_response,
                    parse_outcome=parse_outcome,
                    lookup_status=status,
                    error_message=(
                        f"filtered_invalid_url_count={filtered_invalid_url_count}"
                        if filtered_invalid_url_count > 0 and not has_matches
                        else None
                    ),
                    duration_ms=duration_ms,
                    match_count=len(matches),
                )
                response_map[response_key] = CredentialsResponse(
                    opportunity_id=response_key,
                    opportunity_title=opp.title,
                    matches=matches,
                    no_matches_found=entry.get("no_matches_found", not has_matches),
                    lookup_status=status,
                    diagnostics=diagnostics,
                )

            for idx, opp in enumerate(opportunities, 1):
                opp_id = self._opportunity_identity(opp, idx)
                response_key = self._batch_response_key(opp)
                if response_key in response_map:
                    continue
                diagnostics = CredentialsLookupDiagnostics(
                    opportunity_id=response_key,
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
                response_map[response_key] = CredentialsResponse(
                    opportunity_id=response_key,
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
                recovered_ids = {str(entry.get("opportunity_id", "") or "").strip() for entry in recovered_results}
                for entry in recovered_results:
                    opp_id = str(entry.get("opportunity_id", "") or "").strip()
                    opp = id_to_opp.get(opp_id)
                    if opp is None:
                        continue
                    response_key = self._batch_response_key(opp)
                    matches, filtered_invalid_url_count = self._coerce_matches(
                        entry.get("matches", []),
                        max_matches_per_opportunity,
                    )
                    has_matches = len(matches) > 0
                    status = "Matched" if has_matches else "No Match"
                    if has_matches and filtered_invalid_url_count > 0:
                        parse_outcome = "batch_json_parsed_with_matches_filtered_invalid_url"
                    elif has_matches:
                        parse_outcome = "batch_partial_recovery"
                    elif filtered_invalid_url_count > 0:
                        parse_outcome = "batch_json_parsed_all_matches_filtered_invalid_url"
                    else:
                        parse_outcome = "batch_partial_recovery"
                    diagnostics = CredentialsLookupDiagnostics(
                        opportunity_id=opp_id,
                        opportunity_title=opp.title,
                        sector=sector,
                        query_text=query_text,
                        raw_response_text=raw_response,
                        parse_outcome=parse_outcome,
                        lookup_status=status,
                        error_message=(
                            f"filtered_invalid_url_count={filtered_invalid_url_count}"
                            if filtered_invalid_url_count > 0 and not has_matches
                            else None
                        ),
                        duration_ms=duration_ms,
                        match_count=len(matches),
                    )
                    response_map[response_key] = CredentialsResponse(
                        opportunity_id=response_key,
                        opportunity_title=opp.title,
                        matches=matches,
                        no_matches_found=entry.get("no_matches_found", not has_matches),
                        lookup_status=status,
                        diagnostics=diagnostics,
                    )

                for idx, opp in enumerate(opportunities, 1):
                    opp_id = self._opportunity_identity(opp, idx)
                    response_key = self._batch_response_key(opp)
                    if opp_id in recovered_ids or response_key in response_map:
                        continue
                    diagnostics = CredentialsLookupDiagnostics(
                        opportunity_id=response_key,
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
                    response_map[response_key] = CredentialsResponse(
                        opportunity_id=response_key,
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

    def _coerce_matches(self, raw_matches: object, max_matches: int) -> Tuple[List[CredentialMatch], int]:
        matches: List[CredentialMatch] = []
        filtered_invalid_url_count = 0
        seen_urls: Set[str] = set()
        if not isinstance(raw_matches, list):
            return matches, filtered_invalid_url_count
        for match_data in raw_matches:
            if not isinstance(match_data, dict):
                continue
            url = str(match_data.get("url", "")).strip()
            if not self._is_valid_credential_url(url):
                filtered_invalid_url_count += 1
                continue
            normalized_url = url.lower()
            if normalized_url in seen_urls:
                continue
            try:
                matches.append(
                    CredentialMatch(
                        title=match_data.get("title", "Unknown"),
                        client_challenge=match_data.get("client_challenge", ""),
                        approach=match_data.get("approach", ""),
                        value_provided=match_data.get("value_provided", ""),
                        industry=match_data.get("industry", ""),
                        technologies_used=self._coerce_technologies_used(
                            match_data.get("technologies_used", [])
                        ),
                        emd=match_data.get("emd"),
                        why_relevant=str(match_data.get("why_relevant", "") or "").strip() or None,
                        url=url,
                    )
                )
                seen_urls.add(normalized_url)
            except Exception as e:
                logger.warning("Failed to parse batch credential match: %s", e)
            if len(matches) >= max_matches:
                break
        return matches, filtered_invalid_url_count

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
        for idx, opp in enumerate(opportunities, 1):
            opp_id = self._batch_response_key(opp)
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_id=opp_id,
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
            results[opp_id] = CredentialsResponse(
                opportunity_id=opp_id,
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
        opportunity_id: Optional[str] = None,
        sector: str = "General",
        query_text: str = "",
        duration_ms: float = 0.0,
        max_matches: int = MAX_SINGLE_MATCHES,
    ) -> CredentialsResponse:
        """Parse GPT response into CredentialsResponse.
        
        Handles both JSON responses and natural language fallback.
        """
        if not raw or not raw.strip():
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_id=opportunity_id,
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
                opportunity_id=opportunity_id,
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True,
                lookup_status="No Match",
                diagnostics=diagnostics
            )
        
        # Try to parse as JSON
        try:
            data = self._parse_single_response_payload(raw)
            matches, filtered_invalid_url_count = self._coerce_matches(
                data.get("matches", []),
                max_matches,
            )

            has_matches = len(matches) > 0
            lookup_status = "Matched" if has_matches else "No Match"
            if has_matches and filtered_invalid_url_count > 0:
                parse_outcome = "json_parsed_with_matches_filtered_invalid_url"
            elif has_matches:
                parse_outcome = "json_parsed_with_matches"
            elif filtered_invalid_url_count > 0:
                parse_outcome = "json_parsed_all_matches_filtered_invalid_url"
            else:
                parse_outcome = "json_parsed_no_matches"

            if data.get("no_matches_found", False) and filtered_invalid_url_count == 0:
                parse_outcome = "json_explicit_no_match"

            diagnostics = CredentialsLookupDiagnostics(
                opportunity_id=opportunity_id,
                opportunity_title=opportunity_title,
                sector=sector,
                query_text=query_text,
                raw_response_text=raw,
                parse_outcome=parse_outcome,
                lookup_status=lookup_status,
                error_message=(
                    f"filtered_invalid_url_count={filtered_invalid_url_count}"
                    if filtered_invalid_url_count > 0 and not has_matches
                    else None
                ),
                duration_ms=duration_ms,
                match_count=len(matches)
            )

            return CredentialsResponse(
                opportunity_id=opportunity_id,
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
                    opportunity_id=opportunity_id,
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
                    opportunity_id=opportunity_id,
                    opportunity_title=opportunity_title,
                    matches=[],
                    no_matches_found=True,
                    lookup_status="No Match",
                    diagnostics=diagnostics
                )
            
            # Can't parse - log and return empty
            logger.warning(f"Could not parse credentials response: {raw[:200]}...")
            diagnostics = CredentialsLookupDiagnostics(
                opportunity_id=opportunity_id,
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
                opportunity_id=opportunity_id,
                opportunity_title=opportunity_title,
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Could not parse credentials response as JSON.",
                diagnostics=diagnostics
            )

    def _parse_single_response_payload(self, raw: str) -> Dict[str, object]:
        """Parse response payload for single-opportunity lookups with salvage fallback."""
        primary_candidate = self._extract_json(raw)
        parse_error: Optional[json.JSONDecodeError] = None
        try:
            payload = json.loads(primary_candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError as e:
            parse_error = e

        recovered = self._extract_first_valid_json_object(raw, required_key="matches")
        if recovered is not None:
            return recovered

        if parse_error is not None:
            raise parse_error

        raise json.JSONDecodeError("Could not locate JSON object in response.", raw, 0)

    def _build_failure_response(
        self,
        opportunity_title: str,
        opportunity_id: Optional[str],
        sector: str,
        query_text: str,
        error: Exception,
        duration_ms: float
    ) -> CredentialsResponse:
        """Build a deterministic lookup failure response with diagnostics."""
        diagnostics = CredentialsLookupDiagnostics(
            opportunity_id=opportunity_id,
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
            opportunity_id=opportunity_id,
            opportunity_title=opportunity_title,
            matches=[],
            no_matches_found=True,
            lookup_status="Lookup Failed",
            failure_reason=str(error),
            diagnostics=diagnostics
        )

    def _opportunity_identity(self, opportunity: Opportunity, index: Optional[int] = None) -> str:
        candidate = str(getattr(opportunity, "opportunity_id", "") or "").strip()
        if candidate:
            return candidate
        if index is not None:
            return f"opp_{index}"
        return opportunity.title

    def _batch_response_key(self, opportunity: Opportunity) -> str:
        return self._opportunity_identity(opportunity, None)
    
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

    def _extract_first_valid_json_object(
        self,
        text: str,
        required_key: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        """Extract the first valid JSON object from arbitrary text."""
        if not text:
            return None

        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            candidate = self._extract_balanced_json_object(text, idx)
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if required_key and required_key not in payload:
                continue
            return payload
        return None

    def _extract_balanced_json_object(self, text: str, start_index: int) -> Optional[str]:
        """Return a balanced JSON object substring starting at start_index."""
        if start_index < 0 or start_index >= len(text) or text[start_index] != "{":
            return None

        depth = 0
        in_string = False
        escape = False
        for idx in range(start_index, len(text)):
            ch = text[idx]
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
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index:idx + 1]
        return None

    def _is_valid_credential_url(self, url: object) -> bool:
        if not isinstance(url, str):
            return False
        raw = url.strip()
        if not raw:
            return False

        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            return False
        if not parsed.netloc:
            return False

        host = parsed.netloc.lower()
        if host not in {"roberthalf.sharepoint.com", "ishare.protiviti.com"}:
            return False

        if host == "roberthalf.sharepoint.com":
            path = (parsed.path or "").lower()
            if "credential-details.aspx" not in path:
                return False

        return True

    def _coerce_technologies_used(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"not specified", "n/a", "none"}:
                return []
            return [text]
        return []
