from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from azure.identity.aio import DefaultAzureCredential
from azure.core.exceptions import AzureError
from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.models import (
    DeepResearchToolDefinition,
    DeepResearchDetails,
    DeepResearchBingGroundingConnection,
    MessageRole,
)

from config.config import AppConfig
from services.runtime_policy import get_runtime_policy


logger = logging.getLogger(__name__)


@dataclass
class DeepResearchCitation:
    title: str
    url: str
    origin_type: str = "media"


@dataclass
class DeepResearchSection:
    heading: str
    content: str
    citations: List[DeepResearchCitation]


@dataclass
class DeepResearchReport:
    summary: str
    sections: List[DeepResearchSection]
    citations: List[DeepResearchCitation]
    metadata: Dict[str, Any]


class DeepResearchClient:
    """
    Handles interaction with Azure AI Deep Research tool.
    Combines robust streaming from demo_run.py with dynamic industry prompts.
    """

    def __init__(self, industry: str = "general") -> None:
        if not (AppConfig.PROJECT_ENDPOINT and AppConfig.MODEL_DEPLOYMENT_NAME):
            raise RuntimeError("Project endpoint and model deployment must be configured")
        if not (AppConfig.DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME and AppConfig.BING_CONNECTION_NAME):
            raise RuntimeError("Deep Research configuration missing")

        self._project_endpoint = AppConfig.PROJECT_ENDPOINT
        self._primary_model = AppConfig.MODEL_DEPLOYMENT_NAME
        self._deep_model = AppConfig.DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME
        self._bing_connection = AppConfig.BING_CONNECTION_NAME
        self._industry = industry
        self._runtime_policy = get_runtime_policy()

        self._credential: Optional[DefaultAzureCredential] = None
        self._client: Optional[AIProjectClient] = None
        self._agent_id: Optional[str] = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> None:
        if self._client:
            return
        async with self._lock:
            if self._client:
                return
            credential = DefaultAzureCredential()
            client = AIProjectClient(endpoint=self._project_endpoint, credential=credential)
            self._credential = credential
            self._client = client
            await self._ensure_agent()

    async def _ensure_agent(self) -> None:
        if self._agent_id or not self._client:
            return
        
        try:
            # Load industry-specific prompt with runtime source-policy guidance.
            from services.prompt_loader import PromptLoader
            loader = PromptLoader()
            
            try:
                base_instructions = loader.load_prompt(self._industry)
                prompt_meta = loader.get_prompt_metadata(self._industry)
                logger.info(
                    f"Loaded {prompt_meta['display_name']} prompt "
                    f"(v{prompt_meta['version']})"
                )
            except Exception as e:
                logger.warning(f"Failed to load {self._industry} prompt, using general: {e}")
                base_instructions = loader.load_prompt("general")
            
            enhanced_instructions = base_instructions + self._source_policy_instructions()
            
            deep_tool = DeepResearchToolDefinition(
                deep_research=DeepResearchDetails(
                    deep_research_model=self._deep_model,
                    deep_research_bing_grounding_connections=[
                        DeepResearchBingGroundingConnection(connection_id=self._bing_connection)
                    ],
                )
            )
            logger.info(
                "Creating Deep Research agent with %s industry focus (%s source policy)",
                self._industry,
                self._runtime_policy.source_policy_mode,
            )
            agent = await self._client.agents.create_agent(
                model=self._primary_model,
                name=f"deep-research-{self._industry}",
                instructions=enhanced_instructions,
                tools=[deep_tool],
            )
            self._agent_id = agent.id
            logger.info("Deep Research agent created: %s", agent.id)
            
        except TypeError as e:
            logger.error("Deep Research agent creation failed due to SDK parameter mismatch")
            logger.error("SDK Error: %s", str(e))
            try:
                import azure.ai.agents
                sdk_version = getattr(azure.ai.agents, '__version__', 'unknown')
                logger.error("Installed azure-ai-agents version: %s", sdk_version)
            except Exception:
                logger.error("Could not determine azure-ai-agents version")
            logger.error("Configuration used:")
            logger.error("  - Primary model: %s", self._primary_model)
            logger.error("  - Deep Research model: %s", self._deep_model)
            logger.error("  - Bing connection: %s", self._bing_connection[:20] + "..." if len(self._bing_connection) > 20 else self._bing_connection)
            raise RuntimeError(
                "Failed to create Deep Research agent due to SDK parameter mismatch. "
                "The code has been updated to use the correct parameter names. "
                "Check logs for details."
            ) from e
        except Exception as e:
            logger.error("Unexpected error creating Deep Research agent: %s", str(e))
            raise

    def _extract_text_from_message(self, msg) -> Optional[str]:
        """Safely extract text content from a message object."""
        try:
            content_items = getattr(msg, 'content', [])
            if not content_items:
                return None
            
            text_parts = []
            for content in content_items:
                content_type = getattr(content, 'type', None)
                if content_type == "text":
                    text_obj = getattr(content, 'text', None)
                    if text_obj:
                        text_val = getattr(text_obj, 'value', None)
                        if text_val:
                            text_parts.append(text_val)
            
            return "\n".join(text_parts) if text_parts else None
        except Exception as e:
            logger.debug(f"extract_text_from_message error: {e}")
            return None

    def _extract_citations_from_message(self, msg) -> Set[str]:
        """Extract unique URLs from message annotations (legacy + nested shapes)."""
        unique_urls = set()
        try:
            content_items = getattr(msg, 'content', [])
            for content in content_items:
                content_type = getattr(content, 'type', None)
                if content_type == "text":
                    text_obj = getattr(content, 'text', None)
                    if text_obj:
                        annotations = getattr(text_obj, 'annotations', [])
                        for ann in annotations:
                            for title, url in self._extract_annotation_citations(ann):
                                if url:
                                    unique_urls.add(url)
            for ann in getattr(msg, "url_citation_annotations", []) or []:
                for title, url in self._extract_annotation_citations(ann):
                    if url:
                        unique_urls.add(url)
        except Exception:
            pass  # Silent fail for citation extraction
        
        return unique_urls

    def _extract_annotation_citations(self, annotation) -> List[tuple[Optional[str], str]]:
        """Handle citation extraction across Azure SDK annotation shapes."""
        citations: List[tuple[Optional[str], str]] = []
        if annotation is None:
            return citations

        # Newer shape: annotation.citations = [{title,url}, ...]
        nested = getattr(annotation, "citations", None)
        if nested:
            for item in nested:
                url = getattr(item, "url", None)
                title = getattr(item, "title", None)
                if url:
                    citations.append((title, url))

        # Legacy shape: annotation.url_citation
        url_citation_obj = getattr(annotation, "url_citation", None)
        if url_citation_obj is not None:
            url = getattr(url_citation_obj, "url", None)
            title = getattr(url_citation_obj, "title", None)
            if url:
                citations.append((title, url))

        # Legacy URI shape: annotation.uri_citation
        uri_citation_obj = getattr(annotation, "uri_citation", None)
        if uri_citation_obj is not None:
            url = getattr(uri_citation_obj, "uri", None)
            title = getattr(uri_citation_obj, "title", None)
            if url:
                citations.append((title, url))

        return citations

    def _collect_agent_citations(self, messages: List[Any]) -> Set[str]:
        """Collect unique citations from all assistant messages."""
        collected: Set[str] = set()
        for message in messages or []:
            if not self._is_agent_message(message):
                continue
            collected.update(self._extract_citations_from_message(message))
        return collected

    def _source_policy_instructions(self) -> str:
        mode = (self._runtime_policy.source_policy_mode or "quality_first").strip().lower()
        if mode == "volume_first":
            return """

## Source Policy (Volume-First)
- Prioritize broad source coverage while maintaining relevance.
- Keep domain diversity (no single domain should dominate).
- Prefer direct publisher/issuer URLs and avoid search wrapper links.
- Use quality checks to avoid low-confidence or repetitive citations.
- For executive movement signals, preserve all material discovered movements (including lower-confidence but valid sources); prioritization happens in synthesis.
"""
        if mode == "balanced":
            return """

## Source Policy (Balanced)
- Balance source volume and source quality.
- Cover each material signal with at least one credible source when available.
- Keep domain diversity (no single domain should dominate).
- Prefer direct publisher/issuer URLs and avoid search wrapper links.
- For executive movement signals, preserve all material discovered movements (including lower-confidence but valid sources); prioritization happens in synthesis.
"""
        return """

## Source Policy (Quality-First)
- Prioritize authoritative evidence over citation volume.
- Cover each material signal with the strongest available source(s), especially regulatory and issuer disclosures.
- Maintain source diversity (avoid over-reliance on a single domain).
- Prefer direct publisher/issuer URLs and avoid search wrapper links.
- If a high-quality source is unavailable, use the best available source and note evidence limits.
- For executive movement signals, preserve all material discovered movements (including lower-confidence but valid sources); prioritization happens in synthesis.
"""

    def _extract_company_focus(self, query: str) -> str:
        text = (query or "").strip()
        if not text:
            return ""
        match = re.search(
            r"\bfor\s+([A-Za-z0-9][A-Za-z0-9&\-\s]{1,79}?)(?:\s+focusing|\s+with|\s+across|\s+within|\s+in\b|$)",
            text,
            re.IGNORECASE,
        )
        if not match:
            return ""
        return match.group(1).strip()

    def _extract_fs_signal_codes_from_query(self, query: str) -> List[str]:
        try:
            from services.signal_registry_service import get_signal_registry_service

            service = get_signal_registry_service()
            tokens: List[str] = []
            lowered = (query or "").lower()
            normalized_query = service._normalize_signal_token(query or "")
            aliases = sorted(service.FS_ALIAS_MAP.keys(), key=len, reverse=True)
            seen = set()
            for alias in aliases:
                raw_pattern = r"\b" + re.escape(alias).replace(r"\ ", r"\s+") + r"\b"
                normalized_alias = service._normalize_signal_token(alias)
                normalized_pattern = (
                    r"\b" + re.escape(normalized_alias).replace(r"\ ", r"\s+") + r"\b"
                    if normalized_alias
                    else None
                )
                if re.search(raw_pattern, lowered) or (
                    normalized_pattern and re.search(normalized_pattern, normalized_query)
                ):
                    if alias not in seen:
                        tokens.append(alias)
                        seen.add(alias)

            canonical = service.canonicalize_fs_signals(tokens)
            if canonical:
                return canonical
            if re.search(r"\ball(?:\s+relevant)?\s+signals?\b", query or "", re.IGNORECASE):
                return service.get_fs_signal_codes()
            return []
        except Exception:
            return []

    def _build_fs_task_appendix(self, query: str) -> str:
        requested_codes = self._extract_fs_signal_codes_from_query(query)
        company_focus = self._extract_company_focus(query)
        if not requested_codes and not company_focus:
            return ""

        signal_playbooks = {
            "FS.CONSUMER.LITIGATION_SETTLEMENT": (
                "- Settlement / enforcement: capture consumer litigation, penalties, remediation obligations, and dated deadlines."
            ),
            "FS.MODEL_RISK.FINDINGS": (
                "- Model risk: capture SR 11-7 / model governance findings, validation gaps, and remediation expectations."
            ),
            "FS.EXEC.TRANSITION": (
                "- Executive transition: capture all material target-company executive, regional risk/regulatory, and board/committee moves."
            ),
            "FS.STRESS_TEST.ISSUES": (
                "- Stress test: capture CCAR/DFAST outcomes, SCB implications, and related supervisory commentary."
            ),
            "FS.REGULATORY.DEADLINE": (
                "- Regulatory deadlines: capture explicit dates, required deliverables, and implementation milestones."
            ),
            "FS.AML.BSA_FINDINGS": (
                "- AML/BSA: capture deficiencies, enforcement actions, and required control enhancements."
            ),
            "FS.CECL.IMPLEMENTATION": (
                "- CECL: capture accounting standard updates, implementation implications, and control/reporting impacts."
            ),
        }

        lines = [
            "Execution Policy (signal-scoped):",
        ]
        if company_focus:
            lines.append(
                f"- Keep findings anchored to {company_focus} and directly related entities; exclude unrelated peer-company personnel moves."
            )
        if requested_codes:
            lines.append("- Requested signals:")
            for code in requested_codes:
                playbook = signal_playbooks.get(code)
                if playbook:
                    lines.append(playbook)

        if "FS.EXEC.TRANSITION" in requested_codes:
            lines.extend(
                [
                    "- Always run a dedicated people-movement sweep for the target company.",
                    "- People-movement query stack must include issuer/newsroom/filings, FinTech Magazine People Moves, and corroborating LinkedIn self-disclosures when available.",
                    "- Preserve all material target-company movements in findings; prioritize top sources only during synthesis.",
                ]
            )

        return "\n".join(lines).strip()

    def _build_run_query(self, query: str) -> str:
        base_query = (query or "").strip()
        if self._industry != "financial_services":
            return base_query
        appendix = self._build_fs_task_appendix(base_query)
        if not appendix:
            return base_query
        return f"{base_query}\n\n{appendix}".strip()

    def _classify_source_origin(self, url: str) -> str:
        normalized = (url or "").strip().lower()
        if not normalized:
            return "media"
        try:
            parsed = urlparse(normalized)
            host = parsed.netloc.removeprefix("www.")
            path = parsed.path or ""
            query = parsed.query or ""
        except Exception:
            return "media"

        if host.endswith("bing.com") and path.startswith("/search"):
            return "search-wrapper filtered"
        if host.endswith("google.com") and path.startswith("/search"):
            return "search-wrapper filtered"
        if host.endswith("yahoo.com") and path.startswith("/search"):
            return "search-wrapper filtered"
        if "search?" in normalized and ("q=" in query or "query=" in query):
            return "search-wrapper filtered"

        if host.endswith((".gov", ".mil")) or host.endswith("sec.gov"):
            return "regulatory"
        if host.startswith("investor.") or host.startswith("ir.") or ".gcs-web.com" in host:
            return "issuer"
        if host.endswith("linkedin.com") or host.endswith("x.com") or host.endswith("twitter.com"):
            return "social"
        return "media"

    def _canonicalize_url(self, url: str) -> str:
        normalized = (url or "").strip()
        if not normalized.startswith(("http://", "https://")):
            return ""

        try:
            parsed = urlparse(normalized)
        except Exception:
            return ""

        scheme = parsed.scheme.lower()
        host = parsed.netloc.lower()
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        if not path.startswith("/"):
            path = f"/{path}"

        # Remove common tracking parameters while preserving business-relevant query keys.
        tracking_prefixes = ("utm_",)
        tracking_keys = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "source"}
        query_items = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            key_lower = key.lower()
            if key_lower in tracking_keys or any(key_lower.startswith(prefix) for prefix in tracking_prefixes):
                continue
            query_items.append((key, value))

        canonical_query = urlencode(query_items, doseq=True)
        fragment = ""
        return urlunparse((scheme, host, path, "", canonical_query, fragment)).strip()

    def _build_source_provenance_counts(self, citations: List[DeepResearchCitation]) -> Dict[str, int]:
        counts = {
            "regulatory": 0,
            "issuer": 0,
            "media": 0,
            "social": 0,
            "search-wrapper filtered": 0,
        }
        for citation in citations:
            origin = (citation.origin_type or "media").strip().lower()
            if origin in counts:
                counts[origin] += 1
            else:
                counts["media"] += 1
        return counts

    def _soft_citation_target(self, query: str) -> int:
        """
        Soft citation target for quality-first logging.
        This is advisory only and never used as a hard gate.
        """
        normalized_query = (query or "").lower()
        if self._industry == "financial_services":
            if "all relevant signals" in normalized_query:
                return 12
            if "exec.transition" in normalized_query or "people movement" in normalized_query:
                return 10
            return 9
        if self._industry in {"defense", "energy", "healthcare", "technology"}:
            return 8
        return 6

    def _extract_urls_from_text(self, text: str) -> List[str]:
        """Extract URLs from plain text when annotation citations are incomplete."""
        if not text:
            return []
        urls = re.findall(r"https?://[^\s\]\)>,]+", text)
        normalized: List[str] = []
        seen = set()
        for url in urls:
            cleaned = url.strip().rstrip(".,;)")
            canonical = self._canonicalize_url(cleaned)
            if canonical and self._is_displayable_source_url(canonical) and canonical not in seen:
                seen.add(canonical)
                normalized.append(canonical)
        return normalized

    def _is_displayable_source_url(self, url: str) -> bool:
        """Exclude search wrapper URLs so canonical/source links stay user-meaningful."""
        normalized = (url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        return self._classify_source_origin(normalized) != "search-wrapper filtered"

    def _dedupe_citations(self, citations: List[DeepResearchCitation]) -> List[DeepResearchCitation]:
        """Deduplicate citations by normalized URL while preserving first title encountered."""
        deduped: List[DeepResearchCitation] = []
        seen = set()
        for citation in citations:
            url = self._canonicalize_url(citation.url or "")
            if not url:
                continue
            if not self._is_displayable_source_url(url):
                continue
            key = url.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(
                DeepResearchCitation(
                    title=(citation.title or url).strip(),
                    url=url,
                    origin_type=self._classify_source_origin(url),
                )
            )
        return deduped

    def _normalize_source_urls(
        self,
        urls: Iterable[str],
        include_search_wrappers: bool,
    ) -> List[str]:
        """Canonicalize and dedupe source URLs with optional wrapper retention."""
        normalized: List[str] = []
        seen = set()
        for raw in urls:
            canonical = self._canonicalize_url(str(raw or "").strip())
            if not canonical:
                continue
            if not include_search_wrappers and not self._is_displayable_source_url(canonical):
                continue
            key = canonical.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(canonical)
        return normalized

    def _merge_streamed_citations(
        self,
        report: DeepResearchReport,
        streamed_urls: Set[str],
    ) -> DeepResearchReport:
        """Merge all streamed URLs into report citations so discovered sources are not dropped."""
        merged = list(report.citations)
        for url in sorted(streamed_urls):
            clean = self._canonicalize_url(str(url or "").strip())
            if not clean or not self._is_displayable_source_url(clean):
                continue
            merged.append(
                DeepResearchCitation(
                    title=clean,
                    url=clean,
                    origin_type=self._classify_source_origin(clean),
                )
            )

        report.citations = self._dedupe_citations(merged)
        return report

    def _is_agent_message(self, msg) -> bool:
        """Check if a message is from the agent/assistant."""
        try:
            msg_role = getattr(msg, 'role', None)
            if msg_role is None:
                return False
            
            role_str = str(msg_role).lower()
            agent_keywords = ['agent', 'assistant', 'bot']
            return any(keyword in role_str for keyword in agent_keywords)
        except Exception:
            return False
    
    def _extract_step_info(self, step) -> Optional[str]:
        """Extract human-readable step information (like demo_run.py)."""
        try:
            step_type = getattr(step, 'type', None)
            
            if step_type == "tool_calls":
                step_details = getattr(step, 'step_details', None)
                if step_details:
                    tool_calls = getattr(step_details, 'tool_calls', [])
                    for tool_call in tool_calls:
                        tool_type = getattr(tool_call, 'type', '')
                        
                        # Bing Grounding search
                        if tool_type == 'bing_grounding':
                            bing_grounding = getattr(tool_call, 'bing_grounding', None)
                            if bing_grounding:
                                query = getattr(bing_grounding, 'query', 'Unknown query')
                                return f"[BING SEARCH] {query}"
                        
                        # Deep Research tool invocation
                        elif 'deep_research' in tool_type.lower():
                            return "[DEEP RESEARCH] Planning next research phase..."
                        
                        # Generic function call
                        elif getattr(tool_call, 'function', None):
                            func_name = getattr(tool_call.function, 'name', 'unknown')
                            return f"[TOOL CALL] {func_name}"
            
            elif step_type == "message_creation":
                return "[AGENT] Synthesizing findings..."
            
        except Exception as e:
            logger.debug(f"Error extracting step info: {e}")
        
        return None

    async def run(
        self, 
        query: str,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> DeepResearchReport:
        """
        Execute Deep Research with optional progress streaming.
        
        Args:
            query: Research query
            progress_callback: Optional callback function(message_text, metadata)
                              called for each new agent message during research
        
        Returns:
            DeepResearchReport with findings and citations
        """
        try:
            await self._ensure_client()
        except Exception as e:
            logger.error("Failed to initialize Deep Research client: %s", str(e))
            raise RuntimeError(
                "Deep Research client initialization failed. "
                "Verify your Azure configuration:\n"
                "  1. PROJECT_ENDPOINT is set and accessible\n"
                "  2. MODEL_DEPLOYMENT_NAME points to a gpt-4o deployment\n"
                "  3. DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME points to o3-deep-research\n"
                "  4. BING_CONNECTION_NAME is the connection ID (not name)\n"
                "  5. All resources are in the same region (West US or Norway East)\n"
                f"Original error: {str(e)}"
            ) from e
        
        assert self._client and self._agent_id

        logger.info("Deep Research run started", extra={"query": query, "industry": self._industry})
        run_query = self._build_run_query(query)

        thread = await self._client.agents.threads.create()
        await self._client.agents.messages.create(
            thread_id=thread.id,
            role=MessageRole.USER,
            content=run_query,
        )

        # Start the run
        try:
            run = await self._client.agents.runs.create(
                thread_id=thread.id,
                agent_id=self._agent_id,
            )
        except AzureError as exc:
            logger.exception("Deep Research run failed to start: %s", exc)
            error_msg = str(exc)
            if "unsupported_tool" in error_msg.lower():
                raise RuntimeError(
                    "Deep Research tool not supported in this configuration. "
                    "Common causes:\n"
                    "  1. Resource region mismatch (must all be in West US or Norway East)\n"
                    "  2. o3-deep-research model not deployed in the same region as AI Project\n"
                    "  3. gpt-4o model not deployed in the same region\n"
                    "  4. Bing connection not properly linked to AI Project\n"
                    f"Azure error: {error_msg}"
                ) from exc
            raise

        # Pseudo-streaming: poll for messages while run is in progress
        printed_message_ids: Set[str] = set()
        processed_step_ids: Set[str] = set()
        all_citations: Set[str] = set()
        all_activity: List[str] = []  # Track all activity for display
        last_status = None
        poll_count = 0

        while run.status in ["queued", "in_progress", "requires_action"]:
            poll_count += 1
            
            # Log status changes
            if run.status != last_status:
                logger.info(f"Run status: {run.status}")
                last_status = run.status
            
            # Show periodic progress
            if poll_count % 5 == 0:
                logger.debug(f"Poll #{poll_count} | Messages tracked: {len(printed_message_ids)} | Citations: {len(all_citations)}")
            
            # Fetch and process steps (like demo_run.py)
            try:
                steps = self._client.agents.runs.list_steps(thread_id=thread.id, run_id=run.id)
                
                # Handle different response formats
                steps_list = []
                async for step in steps:
                    steps_list.append(step)
                
                # Sort chronologically
                sorted_steps = sorted(steps_list, key=lambda x: getattr(x, 'created_at', 0))
                
                for step in sorted_steps:
                    step_id = getattr(step, 'id', None)
                    if step_id and step_id not in processed_step_ids:
                        # Extract step details
                        step_info = self._extract_step_info(step)
                        if step_info:
                            all_activity.append(step_info)
                            logger.info(f"Step: {step_info}")
                        processed_step_ids.add(step_id)
                        
            except Exception as e:
                # Steps API may not be available in all SDK versions
                logger.debug(f"Could not fetch steps: {e}")
            
            try:
                # Fetch messages (iterate directly, don't await AsyncItemPaged)
                messages = self._client.agents.messages.list(
                    thread_id=thread.id,
                    order="asc",
                    limit=100
                )
                
                # Process new messages
                async for msg in messages:
                    if msg.id in printed_message_ids:
                        continue
                    
                    if self._is_agent_message(msg):
                        # Extract text and citations
                        msg_text = self._extract_text_from_message(msg)
                        msg_citations = self._extract_citations_from_message(msg)
                        
                        if msg_citations:
                            all_citations.update(msg_citations)
                            logger.info(f"Running citation count: {len(all_citations)} sources")
                        
                        # Call progress callback if provided
                        if progress_callback:
                            metadata = {
                                'citation_count': len(all_citations),
                                'status': run.status,
                                'poll_count': poll_count,
                                'activity_log': all_activity.copy(),  # Include all activity
                                'latest_text': msg_text
                            }
                            # Extract metadata from message if available
                            msg_metadata = getattr(msg, 'metadata', {})
                            if msg_metadata:
                                metadata.update(msg_metadata)
                            
                            try:
                                await progress_callback(msg_text or "", metadata)
                            except Exception as e:
                                logger.warning(f"Progress callback error: {e}")
                    
                    printed_message_ids.add(msg.id)
                    break  # Process one at a time to avoid blocking
                
                # Refresh run status
                run = await self._client.agents.runs.get(thread_id=thread.id, run_id=run.id)
                
            except Exception as e:
                error_msg = str(e)
                if "ASSISTANT" not in error_msg:  # Don't spam known enum errors
                    logger.warning(f"Polling error: {error_msg[:100]}")
            
            # Poll every 1.5 seconds
            await asyncio.sleep(1.5)

        # Check completion status
        if run.status != "completed":
            logger.error("Deep Research run ended with status %s", run.status)
            error_details = getattr(run, 'last_error', None)
            if error_details:
                logger.error("Run error details: %s", error_details)
            raise RuntimeError(
                f"Deep Research run incomplete: {run.status}\n"
                f"Details: {error_details if error_details else 'No additional details available'}"
            )

        logger.info(f"Deep Research completed after {poll_count} polls with {len(all_citations)} citations")

        # Get the final response
        messages = []
        async for message in self._client.agents.messages.list(
            thread_id=thread.id,
            order="desc",
        ):
            messages.append(message)

        # Completion sweep: collect citations from all assistant messages in case
        # polling loop skipped late-arriving message citations.
        all_citations.update(self._collect_agent_citations(messages))
        
        agent_message = next(
            (m for m in messages if self._is_agent_message(m)),
            None,
        )
        if not agent_message:
            raise RuntimeError("Deep Research produced no assistant message")

        # Parse the final report
        report = self._parse_message(agent_message)
        
        # CORRECTIVE URL SEARCH: Check for missing URLs
        if not report.citations or self._has_placeholder_citations(report):
            logger.warning("Deep Research returned no proper URLs, attempting corrective URL search")
            
            url_followup_query = (
                "IMPORTANT: Please provide the complete URLs for all sources referenced in your research. "
                "I need the actual web addresses (starting with http:// or https://) for verification."
            )
            
            await self._client.agents.messages.create(
                thread_id=thread.id,
                role=MessageRole.USER,
                content=url_followup_query,
            )

            try:
                url_run = await self._client.agents.runs.create_and_process(
                    thread_id=thread.id,
                    agent_id=self._agent_id,
                )

                if url_run.status == "completed":
                    url_messages = []
                    async for message in self._client.agents.messages.list(thread_id=thread.id):
                        url_messages.append(message)
                    
                    url_agent_message = next(
                        (m for m in url_messages if self._is_agent_message(m) and m.id != agent_message.id),
                        None,
                    )
                    
                    if url_agent_message:
                        logger.info("Corrective URL search completed")
                        url_report = self._parse_message(url_agent_message)
                        
                        if url_report.citations and any(c.url.startswith(('http://', 'https://')) for c in url_report.citations):
                            report.citations = url_report.citations
                            logger.info(f"Added {len(url_report.citations)} URLs from corrective search")
                else:
                    logger.warning("Corrective URL search failed with status: %s", url_run.status)
                    
            except Exception as e:
                logger.warning("Corrective URL search failed, continuing with original report: %s", e)

        # Merge all streamed citations, even if they did not make the final narrative body.
        report = self._merge_streamed_citations(report, all_citations)
        display_source_urls = self._normalize_source_urls(
            [citation.url for citation in report.citations],
            include_search_wrappers=False,
        )
        discovery_source_urls = self._normalize_source_urls(
            list(all_citations) + display_source_urls,
            include_search_wrappers=True,
        )
        confirmation_source_urls = self._normalize_source_urls(
            discovery_source_urls,
            include_search_wrappers=False,
        )
        provenance_counts = self._build_source_provenance_counts(report.citations)
        filtered_search_wrapper_count = sum(
            1 for url in discovery_source_urls
            if self._classify_source_origin(url) == "search-wrapper filtered"
        )

        # Add metadata
        report.metadata.update({
            "thread_id": thread.id,
            "run_id": run.id,
            "industry": self._industry,
            "poll_count": poll_count,
            "citation_count": len(report.citations),
            "source_policy_mode": self._runtime_policy.source_policy_mode,
            "source_provenance_counts": provenance_counts,
            "filtered_search_wrapper_count": filtered_search_wrapper_count,
            "discovery_source_count": len(discovery_source_urls),
            "confirmation_source_count": len(confirmation_source_urls),
            "display_source_count": len(display_source_urls),
            "discovery_sources": discovery_source_urls,
            "confirmation_sources": confirmation_source_urls,
            "display_sources": display_source_urls,
            "run_query_length": len(run_query),
        })
        
        # Final citation audit
        citation_count = len(report.citations)
        has_urls = any(c.url.startswith(('http://', 'https://')) for c in report.citations) if report.citations else False
        
        logger.info(
            f"Deep Research complete: {citation_count} citations, URLs present: {has_urls}"
        )
        
        soft_target = self._soft_citation_target(query)
        if citation_count < soft_target:
            logger.warning(
                "Below soft citation target: %s/%s sources (quality-first advisory only).",
                citation_count,
                soft_target,
            )
        else:
            logger.info(
                "Soft citation target met: %s/%s sources (mode=%s).",
                citation_count,
                soft_target,
                self._runtime_policy.source_policy_mode,
            )

        return report

    def _has_placeholder_citations(self, report: DeepResearchReport) -> bool:
        """Check if the report contains placeholder citations instead of real URLs."""
        if not report.citations:
            return True
        
        for citation in report.citations:
            if citation.url.startswith(('http://', 'https://')):
                return False
        
        return True

    def _parse_message(self, message) -> DeepResearchReport:
        """Parse message into structured report format."""
        contents = getattr(message, "content", []) or []
        text_blocks = [block for block in contents if getattr(block, "type", "") == "text"]

        # Collect message-level URL citations
        message_level_citations: List[DeepResearchCitation] = []
        for ann in getattr(message, "url_citation_annotations", []) or []:
            for title, url in self._extract_annotation_citations(ann):
                message_level_citations.append(
                    DeepResearchCitation(title=(title or url or "Source"), url=url)
                )

        if not text_blocks:
            summary = getattr(message, "text", "") or ""
            for url in self._extract_urls_from_text(summary):
                message_level_citations.append(DeepResearchCitation(title=url, url=url))
            return DeepResearchReport(
                summary=summary,
                sections=[],
                citations=self._dedupe_citations(message_level_citations),
                metadata={},
            )

        primary = text_blocks[0]
        primary_text_obj = getattr(primary, "text", None)
        if primary_text_obj:
            summary = getattr(primary_text_obj, "value", "") or str(primary_text_obj)
            annotations = getattr(primary_text_obj, "annotations", []) or []
        else:
            summary = ""
            annotations = []

        citations: List[DeepResearchCitation] = list(message_level_citations)

        # Extract citations from annotations
        for annotation in annotations:
            for title, url in self._extract_annotation_citations(annotation):
                citations.append(DeepResearchCitation(title=title or url, url=url))

        # Fallback URL capture from plain text when annotations are sparse.
        for url in self._extract_urls_from_text(summary):
            citations.append(DeepResearchCitation(title=url, url=url))

        # Parse sections
        sections: List[DeepResearchSection] = []
        for block in contents[1:]:
            if getattr(block, "type", "") != "text":
                continue
            heading = getattr(block, "name", "") or "Additional Findings"
            
            block_text_obj = getattr(block, "text", None)
            if block_text_obj:
                block_content = getattr(block_text_obj, "value", "") or str(block_text_obj)
                block_annotations = getattr(block_text_obj, "annotations", []) or []
            else:
                block_content = ""
                block_annotations = []
            
            block_citations: List[DeepResearchCitation] = []
            for annotation in block_annotations:
                for b_title, b_url in self._extract_annotation_citations(annotation):
                    block_citations.append(
                        DeepResearchCitation(title=b_title or b_url, url=b_url)
                    )

            for fallback_url in self._extract_urls_from_text(block_content):
                block_citations.append(
                    DeepResearchCitation(title=fallback_url, url=fallback_url)
                )
                citations.append(
                    DeepResearchCitation(title=fallback_url, url=fallback_url)
                )
            
            sections.append(
                DeepResearchSection(
                    heading=heading,
                    content=block_content,
                    citations=self._dedupe_citations(block_citations),
                )
            )

        return DeepResearchReport(
            summary=summary,
            sections=sections,
            citations=self._dedupe_citations(citations),
            metadata={},
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self._agent_id and self._client:
            try:
                await self._client.agents.delete_agent(self._agent_id)
                logger.info(f"Deleted agent: {self._agent_id}")
            except Exception as e:
                logger.warning(f"Could not delete agent: {e}")
        
        if self._client:
            await self._client.close()
            self._client = None
        if self._credential:
            await self._credential.close()
            self._credential = None


# Global client management
deep_research_client: Optional[DeepResearchClient] = None


def get_deep_research_client(industry: str = "general") -> DeepResearchClient:
    """
    Get or create Deep Research client for specified industry.
    
    Args:
        industry: Industry prompt to use (defense, financial_services, energy, 
                 healthcare, technology, general)
    
    Returns:
        DeepResearchClient instance configured for the industry
    """
    global deep_research_client
    
    logger.info(
        f"get_deep_research_client called: requested_industry={industry}, "
        f"existing_client={'None' if deep_research_client is None else deep_research_client._industry}"
    )
    
    # Create new client if none exists or if industry changed
    if deep_research_client is None or deep_research_client._industry != industry:
        logger.info(f"Creating NEW Deep Research client for industry={industry}")
        deep_research_client = DeepResearchClient(industry=industry)
    else:
        logger.info(f"Reusing existing Deep Research client for industry={industry}")
    
    return deep_research_client
