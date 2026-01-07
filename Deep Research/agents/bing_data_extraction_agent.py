"""
Grounding with Bing Search Tool Research Agent — annotation-driven, no scraping, SDK-safe.

What this does:
- Uses the Grounding with Bing Search tool for discovery and understanding of sources.
- Never trusts inline URLs in model prose; only uses the tool's citation annotations for links.
- If citations are empty, performs ONE corrective follow-up asking the model to re-search and attach citations.
- No web scraping or direct HTTP validation.
- Avoids SDK parameters that caused errors (e.g., 'parallel_tool_calls', 'temperature').

If you later upgrade the azure.ai.agents SDK and want to set model parameters,
add them carefully with a try/except TypeError around create_agent.
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import MessageRole, BingGroundingTool
from azure.core.exceptions import ServiceResponseError
from azure.identity import DefaultAzureCredential, EnvironmentCredential

# Set up logger for this module
logger = logging.getLogger(__name__)

# Suppress Azure SDK debug logs
logging.getLogger('azure').setLevel(logging.WARNING)
logging.getLogger('azure.ai').setLevel(logging.WARNING)
logging.getLogger('azure.ai.agents').setLevel(logging.WARNING)


def _cond_load_dotenv() -> None:
    """Load environment variables from .env if python-dotenv is present."""
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except ImportError:
        pass


class BingDataExtractionAgent:
    """
    Research agent that relies exclusively on the Grounding with Bing Search tool:
    - Citations (URL + title) are extracted only from the tool's citation annotations.
    - Inline URLs in the model body are stripped and never trusted.
    - One corrective follow-up is attempted if no citations are returned.
    """

    SYSTEM_PROMPT = (
        "You are an intelligent AI agent skilled at using the **Grounding with Bing Search tool** to discover, "
        "understand, and cite reputable web information for the user's question.\n\n"
        "Follow this process:\n"
        "Step 1 — Understand Intent:\n"
        "• Carefully analyze the user's question to capture the key facts required and be very thorough.\n\n"
        "Step 2 — Search & Compile (via the Grounding with Bing Search tool):\n"
        "• Use the tool to perform web search and retrieve information.\n"
        "• Prefer primary/official sources (issuer investor relations sites, SEC EDGAR, U.S. regulators) and tier-1 wires "
        "  (Reuters, Bloomberg, AP, WSJ) when available, but you may use any reputable sources discovered by the tool.\n"
        "• Capture key quantitative metrics (deal value, consideration mix, financial figures, timelines) and cite them explicitly. "
        "If sources conflict on a metric, note the discrepancy.\n"
        "• Compile findings into a structured, concise summary with clear bullets and/or short paragraphs.\n"
        "• IMPORTANT: Provide **sources only via the tool's citation annotations**. \n"
        "• When citing SEC filings, reference the specific filing page discovered via the tool (e.g., filing index/IXBRL), "
        "  not guessed or constructed links.\n\n"
        "Step 3 — Coverage Check:\n"
        "• Ensure your findings are very thorough. If information is insufficient to confidently answer, perform additional searches using the tool and update findings.\n\n"
        "Step 4 — Output Formatting:\n"
        "• Present a clear, organized answer. Use headings where appropriate. Keep the writing concise and factual.\n"
        "• Include all your sources at the end of every section.\n"

    )

    def __init__(
        self,
        project_endpoint: Optional[str] = None,
        model_deployment_name: Optional[str] = None,
        azure_bing_connection_id: Optional[str] = None,
        credential: Optional[Any] = None,
    ):
        """
        Initialize the Bing Data Extraction Agent with Azure AI Project credentials.
        
        Args:
            project_endpoint: Azure AI Project endpoint URL
            model_deployment_name: Name of the model deployment
            azure_bing_connection_id: Azure Bing connection ID for grounding
            credential: Azure credential object (optional)
        """
        _cond_load_dotenv()
        
        self.project_endpoint = project_endpoint or os.getenv("PROJECT_ENDPOINT")
        self.model_deployment_name = model_deployment_name or os.getenv("MODEL_DEPLOYMENT_NAME")
        self.azure_bing_connection_id = azure_bing_connection_id or os.getenv("AZURE_BING_CONNECTION_ID")
        self.credential = credential or DefaultAzureCredential()

        if not all([self.project_endpoint, self.model_deployment_name, self.azure_bing_connection_id]):
            raise ValueError(
                "Missing required Azure variables. Set PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME, AZURE_BING_CONNECTION_ID."
            )
        
        logger.info("BingDataExtractionAgent initialized successfully")

    # -----------------------
    # Internal helper methods
    # -----------------------

    def _create_agent(self, agents_client):
        """
        Create an ephemeral agent configured with the Grounding with Bing Search tool.
        NOTE: We do NOT pass unsupported kwargs (e.g., 'parallel_tool_calls', 'temperature').
        """
        bing_tool = BingGroundingTool(connection_id=self.azure_bing_connection_id)
        agent = agents_client.create_agent(
            model=self.model_deployment_name,
            name="bing-data-extraction-session",
            instructions=self.SYSTEM_PROMPT,
            tools=bing_tool.definitions,
        )
        logger.debug("Created ephemeral agent for GWBS search")
        return agent

    @staticmethod
    def _strip_inline_urls(text: str) -> str:
        """Remove any inline raw URLs from the body text (we do not trust them)."""
        if not text:
            return text
        cleaned = re.sub(r"https?://\S+", "[link omitted]", text)
        cleaned = re.sub(r"【[^】]+】", "", cleaned)
        return cleaned

    @staticmethod
    def _role_equals(role_obj: Any, expected: str) -> bool:
        """Compare Azure agent message roles defensively."""
        if role_obj is None:
            return False

        # Strings (current SDK) -> case-insensitive compare
        if isinstance(role_obj, str):
            return role_obj.strip().lower() == expected

        # Enum values -> compare value/ name
        try:
            if hasattr(role_obj, "value") and isinstance(role_obj.value, str):
                if role_obj.value.strip().lower() == expected:
                    return True
        except Exception:
            pass

        try:
            return role_obj == MessageRole[expected.upper()]
        except Exception:
            return False

    @staticmethod
    def _extract_text(msg) -> str:
        """
        Collect the assistant's text parts and strip any inline raw URLs.
        We only surface citations from annotations later.
        """
        out: List[str] = []
        for t in getattr(msg, "text_messages", []) or []:
            if hasattr(t, "text") and hasattr(t.text, "value"):
                out.append(t.text.value)
            elif hasattr(t, "value"):
                out.append(t.value)
            elif isinstance(t, str):
                out.append(t)
        body = "\n".join(out)
        return body

    @staticmethod
    def _extract_citations(msg) -> List[Dict[str, str]]:
        """Collect citations from both legacy and current Azure SDK shapes."""
        citations: List[Dict[str, str]] = []
        seen_urls = set()

        def _add_citation(title: Optional[str], url: Optional[str]) -> None:
            if not url:
                return
            if not url.lower().startswith(("http://", "https://")):
                return
            if "ainvest.com" in url.lower():
                return
            if url in seen_urls:
                return
            citations.append({"title": title or url, "url": url})
            seen_urls.add(url)

        # Modern SDK: annotations list with nested citations
        for annotation in getattr(msg, "annotations", []) or []:
            try:
                nested = getattr(annotation, "citations", None)
                if nested:
                    for citation in nested:
                        _add_citation(getattr(citation, "title", None), getattr(citation, "url", None))
                    continue

                url_citation = getattr(annotation, "url_citation", None)
                if url_citation:
                    _add_citation(getattr(url_citation, "title", None), getattr(url_citation, "url", None))
            except Exception:
                continue

        # Legacy SDK: url_citation_annotations collection
        for annotation in getattr(msg, "url_citation_annotations", []) or []:
            try:
                url_citation = getattr(annotation, "url_citation", None)
                if url_citation:
                    _add_citation(getattr(url_citation, "title", None), getattr(url_citation, "url", None))
            except Exception:
                continue

        return citations

    def _log_run_steps_bing_queries(self, agents_client, thread_id: str, run_id: str) -> List[str]:
        """Best-effort capture of Grounding with Bing query strings for auditing."""
        queries: List[str] = []
        try:
            steps = agents_client.runs.list_steps(thread_id=thread_id, run_id=run_id)
            for step in steps:
                tool_calls = getattr(step, "tool_calls", None) or []
                for call in tool_calls:
                    for attr in ("query", "parameters", "args", "arguments"):
                        value = getattr(call, attr, None)
                        if value:
                            queries.append(str(value))
        except Exception:
            pass
        return queries

    def _run_agent_task(self, user_prompt: str) -> Dict[str, Any]:
        """
        Execute a single agent task with the Grounding with Bing Search tool.
        Returns a dict with 'summary', 'citations_md', and 'audit' keys.
        """
        attempts = 2
        last_error: Optional[Exception] = None

        for attempt in range(1, attempts + 1):
            agent = None
            thread = None
            try:
                with AIProjectClient(
                    self.project_endpoint,
                    credential=self.credential,
                ) as project_client:
                    agents_client = project_client.agents
                    result: Optional[Dict[str, Any]] = None

                    try:
                        agent = self._create_agent(agents_client)
                        thread = agents_client.threads.create()

                        agents_client.messages.create(
                            thread_id=thread.id,
                            role=MessageRole.USER,
                            content=user_prompt,
                        )

                        run = agents_client.runs.create_and_process(
                            thread_id=thread.id,
                            agent_id=agent.id,
                        )

                        if run.status == "failed":
                            raise RuntimeError(f"Bing grounding run failed: {run.last_error}")

                        search_queries = self._log_run_steps_bing_queries(
                            agents_client, thread.id, run.id
                        )

                        messages = agents_client.messages.list(thread_id=thread.id)
                        assistant_msg = None
                        for msg in messages:
                            if self._role_equals(getattr(msg, "role", None), "assistant"):
                                assistant_msg = msg
                                break

                        if not assistant_msg:
                            raise RuntimeError("No assistant message found")

                        body = self._strip_inline_urls(self._extract_text(assistant_msg))
                        citations = self._extract_citations(assistant_msg)

                        if not citations:
                            logger.warning("No citations found, attempting corrective follow-up")
                            follow_up_prompt = (
                                f"{user_prompt}\n\nFOLLOW-UP:\n"
                                "Citations were missing or incomplete. Re-run the search using the Grounding with "
                                "Bing Search tool and attach explicit citation annotations for every major claim. "
                                "Organize the response into clearly labeled bullet sections, and avoid placing raw "
                                "URLs in the body—use annotations only."
                            )
                            agents_client.messages.create(
                                thread_id=thread.id,
                                role=MessageRole.USER,
                                content=follow_up_prompt,
                            )
                            follow_up_run = agents_client.runs.create_and_process(
                                thread_id=thread.id,
                                agent_id=agent.id,
                            )
                            if follow_up_run.status == "completed":
                                search_queries.extend(
                                    self._log_run_steps_bing_queries(
                                        agents_client, thread.id, follow_up_run.id
                                    )
                                )
                                follow_up_messages = agents_client.messages.list(thread_id=thread.id)
                                for msg in follow_up_messages:
                                    if (
                                        self._role_equals(getattr(msg, "role", None), "assistant")
                                        and msg.id != assistant_msg.id
                                    ):
                                        citations = self._extract_citations(msg)
                                        body = self._strip_inline_urls(self._extract_text(msg))
                                        break

                        citations_md = ""
                        if citations:
                            citations_md = "\n".join([f"- [{c['title']}]({c['url']})" for c in citations])

                        if not search_queries:
                            search_queries = [user_prompt]

                        audit_queries = list(dict.fromkeys(search_queries))

                        result = {
                            "summary": body or "",
                            "citations_md": citations_md,
                            "audit": {
                                "citation_count": len(citations),
                                "search_queries": audit_queries,
                            },
                        }
                    finally:
                        if thread is not None:
                            try:
                                delete_thread_method = getattr(agents_client.threads, "delete", None)
                                if callable(delete_thread_method):
                                    delete_thread_method(thread.id)
                                else:
                                    legacy_delete = getattr(agents_client, "delete_thread", None)
                                    if callable(legacy_delete):
                                        legacy_delete(thread.id)
                            except Exception as cleanup_err:
                                logger.debug(
                                    "Failed to delete thread %s: %s",
                                    getattr(thread, "id", ""),
                                    cleanup_err,
                                )
                        if agent is not None:
                            try:
                                agents_client.delete_agent(agent.id)
                            except Exception as cleanup_err:
                                logger.warning(
                                    "Failed to delete ephemeral agent %s: %s",
                                    getattr(agent, "id", ""),
                                    cleanup_err,
                                )

                if result is not None:
                    return result

            except ServiceResponseError as exc:
                last_error = exc
                logger.warning(
                    "Bing agent connection error on attempt %d/%d: %s",
                    attempt,
                    attempts,
                    exc,
                )
                if attempt < attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except Exception as exc:
                logger.exception("Bing agent task failed for prompt '%s'", user_prompt)
                raise

        if last_error is not None:
            raise last_error

        raise RuntimeError("Bing agent task failed without a specific error")

    # -----------------------
    # Public API methods
    # -----------------------

    def search_sec_filings(self, company: str) -> Dict[str, Any]:
        """
        Search for SEC filings and regulatory disclosures for a company.
        
        Args:
            company: Company name to search for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching SEC filings for {company}")
        query = (
            f"TASK: SEC filings and key findings for {company}. "
            "Focus on 2025+ 10-K, 10-Q, and 8-K; highlight material items (Risk Factors, MD&A, specific 8-K Items). "
            "Use the Grounding with Bing Search tool to discover the specific filing pages (filing index/IXBRL) and "
            "summarize the relevant content. Provide concise bullets per finding. Do NOT place raw URLs in your body; "
            "provide sources only via citation annotations."
        )
        return self._run_agent_task(query)

    def search_news(self, company: str) -> Dict[str, Any]:
        """
        Search for recent news and market developments for a company.
        
        Args:
            company: Company name to search for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching news for {company}")
        query = (
            f"TASK: 2025+ impactful news for {company} (regulatory, financial, M&A, risk). "
            "Use the Grounding with Bing Search tool with appropriate freshness. Provide multiple citations for major "
            "claims when available. Surface transaction values, regulatory conditions, community commitments, and "
            "integration plans for any M&A activity. No raw URLs in body; sources only via citation annotations."
        )
        return self._run_agent_task(query)

    def search_procurement(self, company: str) -> Dict[str, Any]:
        """
        Search for government procurement and contracts for a company.
        
        Args:
            company: Company name to search for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching procurement for {company}")
        query = (
            f"TASK: U.S. Government procurement context for {company}. "
            "Use the Grounding with Bing Search tool to find notable government notices or official releases; if none are "
            "visible, say so briefly. No raw URLs in body; sources only via citation annotations."
        )
        return self._run_agent_task(query)

    def search_earnings(self, company: str) -> Dict[str, Any]:
        """
        Search for earnings calls and financial guidance for a company.
        
        Args:
            company: Company name to search for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching earnings for {company}")
        query = (
            f"TASK: Earnings for {company} (transcripts, releases, guidance). "
            "Prefer issuer investor relations and SEC filings discovered via the Grounding with Bing Search tool. "
            "Summarize key deltas and guidance clearly. No raw URLs in body; sources only via citation annotations."
        )
        return self._run_agent_task(query)

    def search_industry_context(self, company: str) -> Dict[str, Any]:
        """
        Search for industry context and competitive landscape for a company.
        
        Args:
            company: Company name to search for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching industry context for {company}")
        query = (
            f"TASK: Sector/competitive context for {company}. "
            "Use the Grounding with Bing Search tool to discover credible landscape sources; keep to facts and label opinion "
            "as such. No raw URLs in body; sources only via citation annotations."
        )
        return self._run_agent_task(query)

    def get_full_intelligence(self, company: str) -> Dict[str, Any]:
        """
        Get comprehensive intelligence for a company across all research areas.
        
        Args:
            company: Company name to research
            
        Returns:
            Dict with results from all research areas
        """
        logger.info(f"Getting full intelligence for {company}")
        return {
            "sec_filings": self.search_sec_filings(company),
            "news": self.search_news(company),
            "procurement": self.search_procurement(company),
            "earnings": self.search_earnings(company),
            "industry_context": self.search_industry_context(company),
        }

    def search_competitors(self, company: str) -> Dict[str, Any]:
        """
        Public method to perform a competitor-oriented research task using GWBS.
        Returns a dict with 'summary', 'citations_md', and 'audit' keys, consistent with other helpers.
        """
        logger.info(f"Searching competitors for {company}")
        query = (
            f"TASK: Identify the top competitors for {company} and summarize their recent moves to gain market share. "
            "Use the Grounding with Bing Search tool, provide concise bullets, and cite all claims (annotations)."
        )
        return self._run_agent_task(query)

    def run_custom_search(self, prompt: str) -> Dict[str, Any]:
        """
        Execute a custom research prompt using GWBS. Returns a dict with
        summary, citations_md, and audit (search queries, citation_count).
        """
        logger.info(f"Running custom search: {prompt[:80]}...")
        return self._run_agent_task(prompt)

    # -----------------------
    # Enhanced General Research Methods
    # -----------------------

    def search_market_overview(self, industry: str, location: str = None, limit: int = 10) -> Dict[str, Any]:
        """
        Search for market overview/ranking information for an industry.
        
        Args:
            industry: Industry to research (e.g., "financial services", "technology")
            location: Geographic location to focus on (e.g., "USA", "Puerto Rico")
            limit: Maximum number of companies to include
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching market overview for {industry} in {location or 'global'}")
        
        query = f"Top {limit} {industry} companies"
        if location:
            query += f" in {location}"
        query += " market size revenue ranking 2024 2025 market share"
        
        return self._run_agent_task(query)

    def search_industry_analysis(self, industry: str, location: str = None) -> Dict[str, Any]:
        """
        Search for comprehensive industry analysis and trends.
        
        Args:
            industry: Industry to analyze
            location: Geographic focus area
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching industry analysis for {industry} in {location or 'global'}")
        
        query = f"{industry} industry analysis trends market outlook 2024 2025"
        if location:
            query += f" {location}"
        query += " growth opportunities challenges"
        
        return self._run_agent_task(query)

    def search_regulatory_updates(self, industry: str, location: str = None) -> Dict[str, Any]:
        """
        Search for recent regulatory updates and changes.
        
        Args:
            industry: Industry to research
            location: Geographic focus area
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching regulatory updates for {industry} in {location or 'global'}")
        
        query = f"{industry} regulatory updates new regulations 2024 2025"
        if location:
            query += f" {location}"
        query += " compliance requirements changes"
        
        return self._run_agent_task(query)

    def search_competitor_analysis(self, company: str) -> Dict[str, Any]:
        """
        Enhanced competitor analysis with market positioning.
        
        Args:
            company: Company to analyze competitors for
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching competitor analysis for {company}")
        
        query = f"Top competitors of {company} market share analysis competitive landscape positioning strengths weaknesses"
        
        return self._run_agent_task(query)

    def search_general_topic(self, topic: str) -> Dict[str, Any]:
        """
        Search for any general topic or question.
        
        Args:
            topic: The topic or question to research
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching general topic: {topic}")
        
        # Enhance the topic with research-focused keywords
        enhanced_topic = f"{topic} analysis overview recent developments 2024 2025"
        
        return self._run_agent_task(enhanced_topic)

    def search_company_any(self, company_name: str) -> Dict[str, Any]:
        """
        Search for any company (not restricted to hardcoded list).
        
        Args:
            company_name: Name of the company to research
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching for company: {company_name}")
        
        query = f"{company_name} company overview business model financial performance recent news 2024 2025"
        
        return self._run_agent_task(query)

    def search_financial_companies_by_location(self, location: str, limit: int = 30) -> Dict[str, Any]:
        """
        Search for financial companies in a specific location.
        
        Args:
            location: Geographic location (e.g., "Puerto Rico", "USA")
            limit: Maximum number of companies to include
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching top {limit} financial companies in {location}")
        
        query = f"Top {limit} financial companies banks in {location} market size revenue ranking 2024 2025"
        
        return self._run_agent_task(query)

    def search_technology_trends(self, industry: str = None) -> Dict[str, Any]:
        """
        Search for technology trends in a specific industry.
        
        Args:
            industry: Industry to focus on (optional)
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching technology trends for {industry or 'general'}")
        
        query = f"Technology trends innovations 2024 2025"
        if industry:
            query += f" in {industry}"
        query += " AI digital transformation"
        
        return self._run_agent_task(query)

    def search_market_rankings(self, category: str, location: str = None, limit: int = 10) -> Dict[str, Any]:
        """
        Search for market rankings in a specific category.
        
        Args:
            category: Category to rank (e.g., "banks", "tech companies", "insurance")
            location: Geographic focus (optional)
            limit: Number of companies to include
            
        Returns:
            Dict with summary, citations_md, and audit info
        """
        logger.info(f"Searching {category} rankings in {location or 'global'}")
        
        query = f"Top {limit} {category} ranking market share revenue"
        if location:
            query += f" in {location}"
        query += " 2024 2025"
        
        return self._run_agent_task(query)


def test_bing_data_extraction(company: str) -> None:
    """
    Test function for Bing data extraction agent.
    
    Args:
        company: Company name to test with
    """
    agent = BingDataExtractionAgent()
    res = agent.get_full_intelligence(company)
    for section, data in res.items():
        print(f"\n--- {section.upper()} ---\n")
        print(data.get("summary", "(no summary)"))
        print("\nCITATIONS:\n")
        print(data.get("citations_md", "(no citations)"))
        # Optional: print audit info for debugging
        audit = data.get("audit", {})
        if audit:
            print("\nAUDIT:")
            print(f"- citation_count: {audit.get('citation_count')}")
            if audit.get("search_queries"):
                print("- search_queries:")
                for q in audit["search_queries"]:
                    print(f"  • {q}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run research with the Grounding with Bing Search tool for a company.")
    parser.add_argument("--company", "-c", required=True, help="Target company name")
    args = parser.parse_args()
    test_bing_data_extraction(args.company)
