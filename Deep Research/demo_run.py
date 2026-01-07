from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Callable

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


logger = logging.getLogger(__name__)


@dataclass
class DeepResearchCitation:
    title: str
    url: str


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
            # Load industry-specific prompt with enhanced "20-SOURCE" rule
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
            
            # Enhance with the "20-SOURCE" volume rule from demo_run.py
            enhanced_instructions = base_instructions + """

## CRITICAL VOLUME REQUIREMENT: The "20-SOURCE" Rule

**You MUST acquire at least 20 DISTINCT unique citations to complete your research.**

SOURCE DIVERSITY REQUIREMENTS:
- No single domain should be cited more than 3 times
- Prioritize authoritative sources (.gov, .mil, regulatory agencies, official databases)
- If you're stuck below 15 sources, you MUST loop and search again with different queries
- Use fallback searches: look for related topics, adjacent issues, supporting context

VALIDATION BEFORE COMPLETION:
- Count your unique URLs before finalizing your report
- If below 15 sources: Your job is NOT done - continue researching
- If 15-19 sources: Acceptable, but note this in your report
- If 20+ sources: Mission accomplished

REMEMBER: Volume AND quality. More sources = more verification = higher confidence in findings.
"""
            
            deep_tool = DeepResearchToolDefinition(
                deep_research=DeepResearchDetails(
                    deep_research_model=self._deep_model,
                    deep_research_bing_grounding_connections=[
                        DeepResearchBingGroundingConnection(connection_id=self._bing_connection)
                    ],
                )
            )
            logger.info(f"Creating Deep Research agent with {self._industry} industry focus + volume requirements")
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
        """Extract unique URLs from message annotations."""
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
                            url_citation = getattr(ann, 'url_citation', None)
                            if url_citation:
                                url = getattr(url_citation, 'url', None)
                                if url:
                                    unique_urls.add(url)
        except Exception:
            pass  # Silent fail for citation extraction
        
        return unique_urls

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

        thread = await self._client.agents.threads.create()
        await self._client.agents.messages.create(
            thread_id=thread.id,
            role=MessageRole.USER,
            content=query,
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
        all_citations: Set[str] = set()
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
            
            try:
                # Fetch messages (iterate directly, don't convert to list)
                messages = await self._client.agents.messages.list(
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
                        if progress_callback and msg_text:
                            metadata = {
                                'citation_count': len(all_citations),
                                'status': run.status,
                                'poll_count': poll_count
                            }
                            # Extract metadata from message if available
                            msg_metadata = getattr(msg, 'metadata', {})
                            if msg_metadata:
                                metadata.update(msg_metadata)
                            
                            try:
                                progress_callback(msg_text, metadata)
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

        # Add metadata
        report.metadata.update({
            "thread_id": thread.id,
            "run_id": run.id,
            "industry": self._industry,
            "poll_count": poll_count,
            "citation_count": len(report.citations),
        })
        
        # Final citation audit
        citation_count = len(report.citations)
        has_urls = any(c.url.startswith(('http://', 'https://')) for c in report.citations) if report.citations else False
        
        logger.info(
            f"Deep Research complete: {citation_count} citations, URLs present: {has_urls}"
        )
        
        # Log warning if below target
        if citation_count < 15:
            logger.warning(f"Below target citation count: {citation_count}/20 sources")
        elif citation_count < 20:
            logger.info(f"Acceptable citation count: {citation_count}/20 sources")
        else:
            logger.info(f"Target exceeded: {citation_count}/20 sources")
        
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
            url_citation_obj = getattr(ann, "url_citation", None)
            url = getattr(url_citation_obj, "url", None) if url_citation_obj else None
            title = (
                getattr(url_citation_obj, "title", None) or url or "Source"
                if url_citation_obj
                else None
            )
            if url:
                message_level_citations.append(
                    DeepResearchCitation(title=title or url, url=url)
                )

        if not text_blocks:
            summary = getattr(message, "text", "") or ""
            return DeepResearchReport(
                summary=summary,
                sections=[],
                citations=message_level_citations,
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
            url = None
            title = None

            url_citation_obj = getattr(annotation, "url_citation", None)
            if url_citation_obj is not None:
                url = getattr(url_citation_obj, "url", None)
                title = getattr(url_citation_obj, "title", None) or url or "Source"
            else:
                # Backwards compatibility
                uri_citation_obj = getattr(annotation, "uri_citation", None)
                if uri_citation_obj is not None:
                    url = getattr(uri_citation_obj, "uri", None)
                    title = getattr(uri_citation_obj, "title", None) or url or "Source"

            if url:
                citations.append(DeepResearchCitation(title=title or url, url=url))

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
                b_url = None
                b_title = None

                b_url_citation_obj = getattr(annotation, "url_citation", None)
                if b_url_citation_obj is not None:
                    b_url = getattr(b_url_citation_obj, "url", None)
                    b_title = getattr(b_url_citation_obj, "title", None) or b_url or "Source"
                else:
                    b_uri_citation_obj = getattr(annotation, "uri_citation", None)
                    if b_uri_citation_obj is not None:
                        b_url = getattr(b_uri_citation_obj, "uri", None)
                        b_title = getattr(b_uri_citation_obj, "title", None) or b_url or "Source"

                if b_url:
                    block_citations.append(
                        DeepResearchCitation(title=b_title or b_url, url=b_url)
                    )
            
            sections.append(
                DeepResearchSection(
                    heading=heading,
                    content=block_content,
                    citations=block_citations,
                )
            )

        return DeepResearchReport(
            summary=summary,
            sections=sections,
            citations=citations,
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