"""
Tool-centric orchestrators for the Chainlit chat experience.
"""
from __future__ import annotations
from typing import List, Tuple, Optional, Callable, Awaitable, Dict
import logging
import re
import asyncio

from models.schemas import CompanyRef, Citation, GWBSSection, FullGWBS, AnalysisItem, AnalysisEvent, Briefing, ScopeLiteral
from tools.gwbs_tools import gwbs_full, gwbs_search
from tools.analyst_tools import analyst_synthesis
from services.cache import TTLCache, cache_key
from services.classifier import classify_primary, needs_analyst as _needs_analyst, scopes_for_label
from config.config import Config as AppConfig
from services.deep_research_client import get_deep_research_client

logger = logging.getLogger(__name__)

_briefing_cache = TTLCache(maxsize=64, ttl_seconds=1800)

def _analysis_items_from_gwbs(bundle: FullGWBS) -> List[AnalysisItem]:
    items: List[AnalysisItem] = []
    for key, section in (bundle.sections or {}).items():
        if not isinstance(section, GWBSSection):
            try:
                section = GWBSSection(**section)  # type: ignore[arg-type]
            except Exception:
                continue
        items.append(
            AnalysisItem(
                company=bundle.company.name,
                title=key.replace("_", " ").title(),
                content=section.summary or "",
                citations=section.citations or [],
                raw={"scope": key, "audit": section.audit},
            )
        )
    return items

async def full_company_analysis(
    company: CompanyRef,
    *,
    bing_agent,
    analyst_agent,
    progress: Optional[Callable[[str, Dict], Awaitable[None]]] = None,  # Enhanced progress callback
) -> Briefing:
    """
    Run a full company analysis with enhanced progress tracking.
    """
    bkey = cache_key("briefing", company.name, company.ticker)
    cached = _briefing_cache.get(bkey)
    if cached:
        logger.info(f"Returning cached briefing for {company.name}")
        return cached

    logger.info(f"Starting full company analysis for {company.name}")
    # Track overall progress
    total_citations = 0
    completed_scopes = 0
    scopes: List[ScopeLiteral] = ["sec_filings", "news", "procurement", "earnings", "industry_context"]
    total_scopes = len(scopes)

    async def _fetch_scope(scope: ScopeLiteral) -> GWBSSection:
        """Fetch a single GWBS scope with enhanced progress tracking."""
        nonlocal total_citations, completed_scopes
        # Send start progress
        if progress:
            try:
                await progress("start", {
                    "scope": scope,
                    "company": company.name,
                    "current": completed_scopes + 1,
                    "total": total_scopes
                })
            except Exception as e:
                logger.warning(f"Start progress callback failed: {e}")
        logger.debug(f"Fetching scope: {scope} for {company.name}")
        section = await asyncio.wait_for(
            asyncio.to_thread(gwbs_search, scope, company, bing_agent),
            timeout=AppConfig.GWBS_SCOPE_TIMEOUT_SECONDS,
        )
        # Update citation count
        scope_citations = len(section.citations or [])
        total_citations += scope_citations
        completed_scopes += 1
        # Send completion progress with citation count
        if progress:
            try:
                await progress("complete", {
                    "scope": scope,
                    "company": company.name,
                    "citations": scope_citations,
                    "total_citations": total_citations,
                    "current": completed_scopes,
                    "total": total_scopes
                })
            except Exception as e:
                logger.warning(f"Complete progress callback failed: {e}")
        return section

    # Kick off all scopes concurrently
    scope_tasks = [asyncio.create_task(_fetch_scope(s)) for s in scopes]
    results = await asyncio.gather(*scope_tasks, return_exceptions=True)

    # Collect sections preserving scope order
    sections: Dict[str, GWBSSection] = {}
    for scope_name, result in zip(scopes, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to fetch scope '{scope_name}': {result}")
            sections[scope_name] = GWBSSection(
                scope=scope_name,
                summary=f"(Failed to fetch {scope_name})",
                citations=[],
                audit={"error": f"{type(result).__name__}: {result}"},
            )
        else:
            sections[scope_name] = result
    # Send final summary progress
    if progress:
        try:
            await progress("summary", {
                "company": company.name,
                "total_citations": total_citations,
                "total_scopes": total_scopes,
                "completed_scopes": completed_scopes
            })
        except Exception as e:
            logger.warning(f"Summary progress callback failed: {e}")

    gwbs = FullGWBS(company=company, sections=sections)
    analysis_items = _analysis_items_from_gwbs(gwbs)
    # Send analyst synthesis progress
    if progress:
        try:
            await progress("analyzing", {
                "company": company.name,
                "items": len(analysis_items)
            })
        except Exception as e:
            logger.warning(f"Analyzing progress callback failed: {e}")

    events = await analyst_synthesis(analysis_items, analyst_agent)
    summary = f"Identified {len(events)} significant events for {company.name}."
    sec_summaries = {k: v.summary for k, v in gwbs.sections.items()}
    briefing = Briefing(company=company, events=events, summary=summary, sections=sec_summaries, gwbs=gwbs.sections)
    _briefing_cache.set(bkey, briefing)
    logger.info(f"Analysis complete for {company.name} - {len(events)} events, {total_citations} total citations")
    return briefing

async def follow_up_research(
    company: CompanyRef,
    question: str,
    *,
    bing_agent,
    analyst_agent,
    ctx_blob=None,
    progress: Optional[Callable[[str], Awaitable[None]]] = None  # Added progress parameter
) -> Tuple[str, List[Citation]]:
    """
    Answer a follow-up question in the context of a company's existing briefing.
    """
    logger.info(f"Follow-up research for {company.name}: '{question}'")

    # If ctx_blob missing, try loading cached Briefing context
    if not ctx_blob:
        bkey = cache_key("briefing", company.name, getattr(company, 'ticker', None))
        cached_briefing = _briefing_cache.get(bkey)
        if cached_briefing:
            logger.debug("Using cached briefing for context matching")
            q_lower = (question or "").lower()
            key_terms = [word for word in q_lower.split() if len(word) > 3]
            pools: List[Tuple[str, List[Citation]]] = []
            if getattr(cached_briefing, "summary", None):
                pools.append((cached_briefing.summary, []))
            for ev in getattr(cached_briefing, "events", []):
                title = ev.get("title", "")
                insights = ev.get("insights", {})
                insights_str = str(insights) if isinstance(insights, dict) else insights
                citations = ev.get("citations", []) if isinstance(ev.get("citations", []), list) else []
                pools.append((" ".join([title, insights_str]), citations))
            hits = []
            for p_text, p_cites in pools:
                if any(term in p_text.lower() for term in key_terms):
                    hits.append((p_text, p_cites))
            if hits:
                hit_text, hit_cites = hits[0]
                logger.info("Found matching context in cached briefing")
                return hit_text[:1200], hit_cites

    if ctx_blob and isinstance(ctx_blob, dict):
        logger.debug(f"Context blob available with keys: {list(ctx_blob.keys())}")
        q_lower = (question or "").lower()
        key_terms = [word for word in q_lower.split() if len(word) > 3]
        pools: List[Tuple[str, List[Citation]]] = []

        if ctx_blob.get("analyst_summary"):
            pools.append((ctx_blob["analyst_summary"], []))

        for ev in ctx_blob.get("analyst_events") or []:
            if isinstance(ev, dict):
                title = ev.get("title", "")
                insights = ev.get("insights", {})
                insights_str = str(insights) if isinstance(insights, dict) else insights
                citations = ev.get("citations", []) if isinstance(ev.get("citations", []), list) else []
                pools.append((" ".join([title, insights_str]), citations))

        hits = []
        for p_text, p_cites in pools:
            if any(term in p_text.lower() for term in key_terms):
                hits.append((p_text, p_cites))
        if hits:
            logger.info("Found matching context in analysis blob")
            hit_text, hit_cites = hits[0]
            return hit_text[:1200], hit_cites

    label = classify_primary(question)
    scopes = scopes_for_label(label)
    logger.info(f"No context match found, running targeted GWBS for label '{label}' with scopes: {scopes}")

    # Send user-facing progress message about what we're searching
    if progress:
        scope_names = [s.replace('_', ' ').title() for s in scopes]
        search_description = f"Searching {', '.join(scope_names)} for {company.name}..."
        try:
            await progress(search_description)
        except Exception as e:
            logger.warning(f"Progress callback failed: {e}")

    # Run targeted GWBS scopes concurrently with progress updates
    async def _fetch(scope: str) -> GWBSSection:
        # Send progress update for each scope starting
        if progress:
            try:
                scope_name = scope.replace('_', ' ').title()
                await progress(f" Searching {scope_name}...")
            except Exception as e:
                logger.warning(f"Scope progress callback failed: {e}")
        logger.debug(f"Fetching GWBS scope: {scope}")
        return await asyncio.wait_for(
            asyncio.to_thread(gwbs_search, scope, company, bing_agent),
            timeout=AppConfig.GWBS_SCOPE_TIMEOUT_SECONDS,
        )

    # Create tasks for all scopes
    tasks = [asyncio.create_task(_fetch(s)) for s in scopes]
    sections: List[GWBSSection] = []
    # For mapping task back to its scope
    scope_task_map = {t: s for t, s in zip(tasks, scopes)}
    for fut in asyncio.as_completed(tasks):
        try:
            sec = await fut
            sections.append(sec)
            # Send completion progress for each scope
            if progress:
                try:
                    scope_name = sec.scope.replace('_', ' ').title()
                    await progress(f"  {scope_name} completed")
                except Exception as e:
                    logger.warning(f"Completion progress callback failed: {e}")
        except Exception as fetch_err:
            logger.warning(f"GWBS scope failed: {fetch_err}")
            # Still send progress for failed scopes
            if progress:
                try:
                    scope_name = scope_task_map.get(fut, "Unknown").replace('_', ' ').title()
                    await progress(f"  {scope_name} failed - continuing with available data")
                except Exception as e:
                    logger.warning(f"Error progress callback failed: {e}")

    body_parts: List[str] = []
    citations_all: List[Citation] = []
    for sec in sections:
        if sec.summary:
            body_parts.append(f"**{sec.scope.replace('_', ' ').title()}**\n{sec.summary}")
        citations_all.extend(sec.citations or [])

    logger.info(f"GWBS results: {len(body_parts)} sections, {len(citations_all)} total citations")

    if not body_parts:
        logger.warning("No content found in GWBS results")
        return ("I couldn't find information that directly answers that. Try asking more specifically, or I can re-run a broader search.", citations_all)

    if _needs_analyst(label, question):
        logger.info("Question requires analyst synthesis")
        items = [
            AnalysisItem(
                company=company.name,
                title=sec.scope.replace("_", " ").title(),
                content=sec.summary,
                citations=sec.citations or [],
                raw={"scope": sec.scope},
            )
            for sec in sections
        ]
        try:
            events = await analyst_synthesis(items, analyst_agent)
        except Exception as synth_err:
            logger.error(f"Analyst synthesis failed: {synth_err}")
            return ("There was an error generating a synthesized analyst answer. Please try again later.", citations_all)
        if events:
            e = events[0]
            what = e.insights.get("what_happened", "") if isinstance(e.insights, dict) else ""
            why = e.insights.get("why_it_matters", "") if isinstance(e.insights, dict) else ""
            combined = "\n".join([p for p in [what, why] if p])
            return combined or "", (e.citations or citations_all)[:8]

    logger.info(f"Returning GWBS response with {len(body_parts)} sections")
    return ("\n\n".join(body_parts), citations_all)
    

async def competitor_analysis(company: CompanyRef, *, bing_agent) -> GWBSSection:
    logger.info(f"Running competitor analysis for {company.name}")
    # Offload to background thread
    return await asyncio.to_thread(gwbs_search, "competitors", company, bing_agent)

async def general_research(prompt: str, *, bing_agent, progress: Optional[Callable[[str], Awaitable[None]]] = None) -> Tuple[str, List[Citation]]:
    """
    Run a single GWBS session from a general prompt (no company context).
    Streams a single progress marker if provided and returns (summary, citations).
    """
    logger.info(f"General research: '{prompt[:80]}...'")
    
    if progress:
        try:
            await progress("general")
        except Exception as cb_err:
            logger.warning(f"Progress callback failed for 'general': {type(cb_err).__name__}: {cb_err}")
            
    # Run the custom prompt in a background thread with a reasonable timeout
    async def _run():
        return await asyncio.wait_for(
            asyncio.to_thread(bing_agent.run_custom_search, prompt),
            timeout=AppConfig.GENERAL_RESEARCH_TIMEOUT_SECONDS,
        )
        
    try:
        raw = await _run()
    except Exception as e:
        logger.error(f"General research failed: {e}")
        return "I couldn't complete that search in time. Please try again.", []
        
    # Extract citations
    md = (raw or {}).get("citations_md", "")
    cites: List[Citation] = []
    if md:
        # simple parse of markdown bullets
        import re
        for line in md.splitlines():
            m = re.match(r"^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)", line.strip())
            if m:
                try:
                    cites.append(Citation(title=m.group("title"), url=m.group("url")))
                except Exception:
                    continue
                    
    logger.info(f"General research completed - found {len(cites)} citations")
    return (raw or {}).get("summary", ""), cites


async def run_deep_research(
    query: str, 
    industry: str = "general",
    progress_callback = None
) -> Dict[str, Any]:
    """
    Execute Deep Research run via Azure AI Foundry.
    
    Args:
        query: User's research question
        industry: Industry prompt to use (e.g., "defense", "financial_services", "general")
        progress_callback: Optional callback function for real-time progress updates
    
    Returns:
        Dict with formatted Deep Research results
    """
    logger.info(f"run_deep_research called with industry={industry}, query={query[:100]}")
    
    if not AppConfig.ENABLE_DEEP_RESEARCH:
        raise RuntimeError("Deep Research feature flag is disabled")

    client = get_deep_research_client(industry=industry)
    logger.info(f"Got Deep Research client with industry={client._industry}")
    
    # Pass progress callback to client if provided
    report = await client.run(query, progress_callback=progress_callback)

    def _to_citations(raw_items) -> List[Citation]:
        cites: List[Citation] = []
        for entry in raw_items:
            if entry.url:
                cites.append(Citation(title=entry.title or entry.url, url=entry.url))
        return cites

    def _smart_dedupe(items: List[Citation]) -> List[Citation]:
        """Smart deduplication that preserves domain diversity"""
        seen_urls = set()
        seen_domains = {}
        deduped: List[Citation] = []
        
        for item in items:
            # Extract domain for diversity tracking
            try:
                from urllib.parse import urlparse
                domain = urlparse(item.url).netloc
            except:
                domain = "unknown"
            
            # Always keep first occurrence of each URL
            if item.url not in seen_urls:
                deduped.append(item)
                seen_urls.add(item.url)
                
                # Track how many sources we have from each domain
                seen_domains[domain] = seen_domains.get(domain, 0) + 1
                
        logger.info(f"Smart deduplication: {len(items)} -> {len(deduped)} citations across {len(seen_domains)} domains")
        logger.info(f"Domain distribution: {dict(sorted(seen_domains.items(), key=lambda x: x[1], reverse=True)[:10])}")
        
        return deduped

    sections: List[Dict[str, Any]] = []
    combined = _to_citations(report.citations)
    
    logger.info(f"Deep Research report has {len(report.citations)} top-level citations")

    for section in report.sections:
        section_cites = [c.dict() for c in _to_citations(section.citations)]
        combined.extend([Citation(**c) for c in section_cites])
        sections.append(
            {
                "title": section.heading or "Findings",
                "content": section.content,
                "citations": section_cites,
            }
        )
    
    # Use smart deduplication instead of removing it entirely
    all_citations = _smart_dedupe(combined)
    
    if all_citations:
        logger.debug(f"Sample citations: {[c.url for c in all_citations[:3]]}")

    response = {
        "type": "deep_research",
        "summary": report.summary,
        "sections": sections,
        "citations": [c.dict() for c in all_citations],
        "metadata": report.metadata,
    }
    return response
# Enhanced orchestrator functions for new capabilities

async def enhanced_user_request_handler(
    user_input: str,
    context,
    bing_agent,
    analyst_agent,
    progress: Optional[Callable[[str], Awaitable[None]]] = None
) -> Dict[str, Any]:
    """
    Enhanced handler for any user request using intent resolution.
    
    This is the main entry point for handling user requests with the new
    intent resolution and task execution system.
    
    Args:
        user_input: User's input text
        context: Conversation context
        bing_agent: Bing data extraction agent
        analyst_agent: Analyst agent
        progress: Optional progress callback
        
    Returns:
        Dict with formatted response data
    """
    try:
        # Import here to avoid circular imports
        from services.enhanced_router import enhanced_router
        from tools.task_executor import task_executor
        from tools.response_formatter import response_formatter
        from tools.general_research_orchestrator import initialize_general_research_orchestrator
        
        # Initialize general research orchestrator if needed
        if not task_executor.general_research_orchestrator:
            general_orchestrator = initialize_general_research_orchestrator(bing_agent)
            task_executor.set_general_research_orchestrator(general_orchestrator)
        
        # Resolve intent
        if progress:
            await progress(" Analyzing your request...")
        
        intent_type, intent_plan = await enhanced_router.route_enhanced(user_input, context)

        logger.info(f"Resolved intent: {intent_type.value} with {len(intent_plan.tasks)} tasks")

        if not intent_plan.tasks:
            logger.info("No tasks produced by intent resolution; requesting clarification")
            return {
                "type": "clarification",
                "summary": "I couldn't determine the right action from that request. Could you rephrase or provide more detail?",
                "citations": [],
                "execution_time": 0.0,
                "intent_type": intent_type.value,
                "confidence": intent_plan.confidence,
                "reasoning": intent_plan.reasoning,
            }

        # Execute tasks
        if progress:
            await progress(f" Executing {len(intent_plan.tasks)} task(s)...")
        
        execution_result = await task_executor.execute_plan(
            intent_plan, context, bing_agent, analyst_agent
        )
        
        # Format response
        if progress:
            await progress(" Formatting response...")
        
        formatted_response = response_formatter.format_response(execution_result)
        
        # Add execution metadata
        formatted_response["intent_type"] = intent_type.value
        formatted_response["confidence"] = intent_plan.confidence
        formatted_response["reasoning"] = intent_plan.reasoning
        
        logger.info(f"Enhanced request handled successfully: {intent_type.value}")
        return formatted_response
        
    except Exception as e:
        logger.error(f"Enhanced request handler failed: {e}")
        return {
            "type": "error",
            "error": "Request processing failed",
            "details": [str(e)],
            "execution_time": 0.0
        }

async def handle_mixed_request(
    user_input: str,
    context,
    bing_agent,
    analyst_agent,
    progress: Optional[Callable[[str], Awaitable[None]]] = None
) -> Dict[str, Any]:
    """
    Handle mixed requests (e.g., company briefing + competitor analysis).
    
    This function specifically handles requests that involve multiple
    different types of tasks.
    """
    try:
        # Use the enhanced handler for mixed requests
        return await enhanced_user_request_handler(
            user_input, context, bing_agent, analyst_agent, progress
        )
    except Exception as e:
        logger.error(f"Mixed request handler failed: {e}")
        return {
            "type": "error",
            "error": "Mixed request processing failed",
            "details": [str(e)]
        }

async def handle_general_research_request(
    user_input: str,
    context,
    bing_agent,
    progress: Optional[Callable[[str], Awaitable[None]]] = None
) -> Dict[str, Any]:
    """
    Handle general research requests (e.g., market overviews, industry analysis).
    
    This function handles non-company-specific research requests.
    """
    try:
        # Import here to avoid circular imports
        from tools.general_research_orchestrator import initialize_general_research_orchestrator
        
        # Initialize general research orchestrator
        general_orchestrator = initialize_general_research_orchestrator(bing_agent)
        
        if progress:
            await progress(" Researching your topic...")
        
        # Execute general research
        summary, citations = await general_orchestrator.execute_general_research(user_input)
        
        # Format response
        formatted_citations = []
        for citation in citations:
            formatted_citations.append({
                "title": citation.title or citation.url,
                "url": citation.url
            })
        
        response = {
            "type": "general_research",
            "summary": summary,
            "citations": formatted_citations,
            "execution_time": 0.0
        }
        
        logger.info("General research request handled successfully")
        return response
        
    except Exception as e:
        logger.error(f"General research handler failed: {e}")
        return {
            "type": "error",
            "error": "General research processing failed",
            "details": [str(e)]
        }

async def handle_any_company_request(
    company_name: str,
    context,
    bing_agent,
    analyst_agent,
    progress: Optional[Callable[[str], Awaitable[None]]] = None
) -> Dict[str, Any]:
    """
    Handle requests for any company (not restricted to hardcoded list).
    
    This function removes the company restrictions and allows analysis
    of any company.
    """
    try:
        # Create company reference
        company_ref = CompanyRef(name=company_name)
        
        if progress:
            await progress(f" Analyzing {company_name}...")
        
        # Execute full company analysis
        briefing = await full_company_analysis(
            company_ref,
            bing_agent=bing_agent,
            analyst_agent=analyst_agent,
            progress=progress
        )
        
        # Format response
        formatted_events = []
        for event in briefing.events:
            if hasattr(event, 'dict'):
                formatted_events.append(event.dict())
            elif isinstance(event, dict):
                formatted_events.append(event)
            else:
                formatted_events.append({"title": str(event), "insights": {}})
        
        formatted_citations = []
        if hasattr(briefing, 'gwbs') and briefing.gwbs:
            for section in briefing.gwbs.values():
                if hasattr(section, 'citations'):
                    for citation in section.citations:
                        formatted_citations.append({
                            "title": citation.title or citation.url,
                            "url": citation.url
                        })
        
        response = {
            "type": "company_briefing",
            "company": briefing.company.name,
            "summary": briefing.summary,
            "events": formatted_events,
            "sections": briefing.sections,
            "citations": formatted_citations,
            "execution_time": 0.0
        }
        
        logger.info(f"Any company request handled successfully: {company_name}")
        return response
        
    except Exception as e:
        logger.error(f"Any company request handler failed: {e}")
        return {
            "type": "error",
            "error": f"Company analysis failed for {company_name}",
            "details": [str(e)]
        }