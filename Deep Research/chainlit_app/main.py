from __future__ import annotations
import sys
from pathlib import Path
from dataclasses import asdict, is_dataclass



PROJECT_ROOT = str(Path(__file__).parent.parent.resolve())
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import logging
from config.logging_config import setup_logging
import chainlit as cl
import asyncio
from typing import Dict, Any, Optional, List
import os
from agents.bing_data_extraction_agent import BingDataExtractionAgent
from agents.analyst_agent import AnalystAgent
from services.conversation_manager import ConversationContext, QueryRouter, AnalysisBlob, QueryType, conversation_manager
from services.follow_up_handler import FollowUpHandler
from services.session_manager import session_manager
from models.schemas import CompanyRef
from tools import orchestrators as ors
from config.config import Config as AppConfig

# Enhanced system imports
from tools.orchestrators import enhanced_user_request_handler
from services.enhanced_router import enhanced_router
from tools.task_executor import task_executor
from tools.response_formatter import response_formatter
from services.company_profiles import load_company_profiles
from services.prompt_generator import get_prompt_generator, ResearchParameters
from services.transition_form_mapper import (
    TRANSITION_ARTIFACTS_SESSION_KEY,
    TRANSITION_EDIT_PENDING_SESSION_KEY,
    TRANSITION_PREFLIGHT_SESSION_KEY,
    TRANSITION_PROMPT_SESSION_KEY,
    TRANSITION_PROMPT_OVERRIDE_SESSION_KEY,
    TRANSITION_REQUEST_SESSION_KEY,
    build_transition_form_props,
    build_transition_request_from_form_response,
    load_transition_request_session,
    persist_transition_request_session,
)
from services.movement_form_mapper import (
    MOVEMENT_ARTIFACTS_SESSION_KEY,
    MOVEMENT_BRIEF_SESSION_KEY,
    MOVEMENT_EDIT_PENDING_SESSION_KEY,
    MOVEMENT_EVIDENCE_ARTIFACT_KEY,
    MOVEMENT_PREFLIGHT_SESSION_KEY,
    MOVEMENT_PROGRESS_SESSION_KEY,
    MOVEMENT_PROMPT_OVERRIDE_SESSION_KEY,
    MOVEMENT_PROMPT_SESSION_KEY,
    MOVEMENT_REPORT_ARTIFACT_KEY,
    MOVEMENT_REQUEST_SESSION_KEY,
    MOVEMENT_SIGNALS_ARTIFACT_KEY,
    build_movement_artifact_actions,
    build_movement_artifacts,
    build_movement_person_details_by_name,
    build_movement_progress_content,
    build_movement_request_from_form_response,
    build_movement_row_action_context_by_person_name,
    load_movement_artifacts_session,
    load_movement_progress_session,
    load_movement_request_session,
    persist_movement_artifacts_session,
    persist_movement_progress_session,
    persist_movement_request_session,
)
from services.transition_brief_formatter import (
    build_transition_artifacts,
    build_transition_brief,
)
from services.element_response_utils import extract_element_response_payload
from services.review_flow import run_review_action_loop
from services.transition_presenter import (
    ACTION_ADJUST_TRANSITION,
    ACTION_EDIT_PROMPT,
    ACTION_RUN_RESEARCH,
    ACTION_VIEW_ARTIFACT,
    ACTION_VIEW_PROMPT,
    build_transition_brief_payload,
    build_transition_preflight_review,
    build_transition_progress_content,
)
from services.transition_prompt_builder import TransitionPromptPackage
from services.movement_prompt_builder import MovementPromptBuilder, MovementPromptPackage
from services.movement_presenter import (
    ACTION_ADJUST_MOVEMENT,
    ACTION_EDIT_MOVEMENT_PROMPT,
    ACTION_RUN_MOVEMENT_RESEARCH,
    ACTION_VIEW_MOVEMENT_PROMPT,
    build_movement_brief_payload,
    build_movement_form_props,
    build_movement_preflight_review,
)

# BD Analysis enrichment (auto-runs after Deep Research)
from services.bd_report_formatter import format_bd_report_as_section
from services.bd_trigger_context import build_trigger_for_bd_enrichment
from services.deep_research_formatter import (
    build_structured_evidence_map,
    format_deep_research_response_as_markdown,
)
from models.bd_schemas import MDReport, MDReportOpportunity
from services.workflow_state import (
    WorkflowRunContext,
    WorkflowRunStatus,
    create_workflow_run,
    get_active_run_id,
    load_workflow_run,
    persist_workflow_run,
    resolve_run_context,
    set_active_run_id,
    update_workflow_run,
)

setup_logging(level=logging.INFO)
logger = logging.getLogger(__name__)
DEEP_RESEARCH_SESSION_KEY = "deep_research_mode"
INDUSTRY_PROMPT_SESSION_KEY = "industry_prompt"
RESEARCH_PARAMS_SESSION_KEY = "research_params"
DEFAULT_MODE = "standard"
DEFAULT_INDUSTRY = "general"
MOVEMENT_MODE = "movement"
TRANSITION_MODE = "transition"
ACTION_START_NEW_MOVEMENT_SCAN = "movement_new_scan"
BD_TRACES_DIR = Path(__file__).parent.parent / "traces"

# --- Input validation helpers ---

def validate_payload(payload: Dict[str, Any], required_keys: list[str]) -> tuple[bool, Optional[str]]:
    """Validate payload has required keys."""
    if not isinstance(payload, dict):
        return False, "Payload must be a dictionary"
    
    for key in required_keys:
        if key not in payload:
            return False, f"Missing required key: {key}"
    
    return True, None

def validate_company_payload(payload: Dict[str, Any]) -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate company payload and extract company data."""
    if not isinstance(payload, dict):
        return False, "Payload must be a dictionary", None
    
    if "company" not in payload:
        return False, "Missing company information", None
    
    company_data = payload["company"]
    if not isinstance(company_data, dict):
        return False, "Company data must be a dictionary", None
    
    if "name" not in company_data:
        return False, "Missing company name", None
    
    return True, None, company_data

# --- Session management helpers ---

def _get_ctx() -> ConversationContext:
    """Get or create conversation context for the current session."""
    try:
        session_id = cl.user_session.get("session_id")
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())
            cl.user_session.set("session_id", session_id)
        
        ctx = conversation_manager.get_or_create_context(session_id)
        return ctx
    except Exception as e:
        logger.error(f"Error getting context: {e}")
        # Fallback: create a new context
        import uuid
        session_id = str(uuid.uuid4())
        return conversation_manager.get_or_create_context(session_id)

async def _init_singletons() -> None:
    """Initialize singleton services with error handling."""
    try:
        if not cl.user_session.get("bing_agent"):
            cl.user_session.set("bing_agent", BingDataExtractionAgent())

        analyst = cl.user_session.get("analyst_agent")
        if not analyst:
            analyst = AnalystAgent()
            cl.user_session.set("analyst_agent", analyst)
        await analyst.ensure_kernel_ready()

        profiles = cl.user_session.get("company_profiles")
        if profiles is None:
            profiles = load_company_profiles()
            cl.user_session.set("company_profiles", profiles)
        if profiles:
            analyst.set_profiles(profiles)
            try:
                ctx = _get_ctx()
                available = {
                    (profile.get("company_name") or name)
                    for name, profile in profiles.items()
                    if isinstance(profile, dict)
                }
                ctx.available_companies = sorted(available)
            except Exception as exc:  # pragma: no cover - defensive safeguard
                logger.debug("Unable to update available companies: %s", exc)

        if not cl.user_session.get("follow_up_handler"):
            bing_agent = cl.user_session.get("bing_agent")
            if bing_agent:
                cl.user_session.set("follow_up_handler", FollowUpHandler(bing_agent))

        if not cl.user_session.get("router"):
            cl.user_session.set("router", QueryRouter())
    except Exception as e:
        logger.exception("Error initializing singletons: %s", e)
        raise

# --- Error handling helpers ---

async def handle_error(error: Exception, context: str, user_message: str = "Sorry, I encountered an error processing your request. Please try again.") -> None:
    """Handle errors gracefully with user-friendly messages."""
    logger.error(f"Error in {context}: {error}")
    
    # Send error message to user
    await cl.Message(user_message).send()
    
    # Log additional details for debugging
    logger.debug(f"Error details: {type(error).__name__}: {str(error)}")


# --- BD Analysis enrichment helpers ---

async def enrich_with_bd_analysis(
    deep_research_response: Dict[str, Any],
    sector: str,
    user_query: str,
    session_params: Optional[Dict[str, Any]] = None,
    progress_callback = None
) -> Dict[str, Any]:
    """Enrich Deep Research output with Credentials validation + ATLAS synthesis.
    
    Automatically runs after Deep Research completes:
    1. Extracts opportunities from DR output
    2. Queries Credentials Agent for each opportunity
    3. Synthesizes final report via ATLAS
    4. Appends results as new section to DR response
    
    Args:
        deep_research_response: Dict from run_deep_research()
        sector: Industry sector (from GUI form)
        user_query: Original user prompt text
        session_params: Optional research form parameters from session
        progress_callback: Optional async callback for progress updates
        
    Returns:
        Enriched response with BD analysis section appended
    """
    try:
        # Convert DR response sections to markdown for BD orchestrator
        dr_markdown = _format_dr_as_markdown(deep_research_response)
        structured_source_urls = _extract_structured_source_urls(deep_research_response)
        structured_evidence_map = build_structured_evidence_map(deep_research_response)
        
        if not dr_markdown or len(dr_markdown.strip()) < 100:
            logger.warning("Deep Research output too short for BD enrichment")
            return deep_research_response
        
        trigger = build_trigger_for_bd_enrichment(
            sector=sector,
            user_query=user_query,
            session_params=session_params or {},
        )
        
        # Progress update
        if progress_callback:
            await progress_callback("Extracting opportunities...")
        
        # Run BD orchestration with trace persistence (non-fatal if unavailable)
        try:
            BD_TRACES_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as trace_err:
            logger.warning(f"Could not prepare BD traces directory '{BD_TRACES_DIR}': {trace_err}")

        from services.bd_orchestrator import BDOrchestrator

        orchestrator = BDOrchestrator(
            traces_dir=BD_TRACES_DIR,
            use_atlas_digestion=AppConfig.ENABLE_BD_ATLAS_DIGESTION
        )
        
        async def bd_progress(msg: str):
            if progress_callback:
                await progress_callback(f"BD Analysis: {msg}")
        
        report = await orchestrator.run(
            trigger,
            deep_research_output=dr_markdown,
            structured_source_urls=structured_source_urls,
            structured_evidence_map=structured_evidence_map,
            progress_cb=bd_progress
        )
        
        # Append BD section to response
        bd_section = _format_bd_report_as_section(report)
        if bd_section:
            deep_research_response["sections"].append(bd_section)
            logger.info(f"BD enrichment complete: {len(report.top_opportunities)} opportunities validated")
        
    except Exception as e:
        logger.warning(f"BD enrichment failed (non-fatal): {e}")
        # Non-fatal - return original response unchanged
    
    return deep_research_response


def _format_dr_as_markdown(response: Dict[str, Any]) -> str:
    """Convert Deep Research response dict to markdown for BD orchestrator."""
    return format_deep_research_response_as_markdown(response)


def _extract_structured_source_urls(response: Dict[str, Any]) -> List[str]:
    """Collect structured source URLs from Deep Research response payload and metadata."""
    urls: List[str] = []
    seen = set()

    def _add(url: Any):
        value = str(url or "").strip()
        if not value.startswith(("http://", "https://")):
            return
        key = value.lower()
        if key in seen:
            return
        seen.add(key)
        urls.append(value)

    for citation in response.get("citations", []) or []:
        if isinstance(citation, dict):
            _add(citation.get("url"))

    for section in response.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        for citation in section.get("citations", []) or []:
            if isinstance(citation, dict):
                _add(citation.get("url"))

    metadata = response.get("metadata", {}) or {}
    for key in ("discovery_sources", "confirmation_sources", "display_sources"):
        for url in metadata.get(key, []) or []:
            _add(url)

    return urls


def _format_bd_report_as_section(report: MDReport) -> Optional[Dict[str, Any]]:
    """Format MDReport as a section dict for present_enhanced_response."""
    return format_bd_report_as_section(report)


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if is_dataclass(value):
        return asdict(value)
    return value


def _load_transition_preflight() -> Optional[Any]:
    payload = cl.user_session.get(TRANSITION_PREFLIGHT_SESSION_KEY)
    if not payload:
        return None
    from models.transition_schemas import TransitionPreflight

    if isinstance(payload, TransitionPreflight):
        return payload
    if hasattr(TransitionPreflight, "model_validate"):
        return TransitionPreflight.model_validate(payload)
    return TransitionPreflight.parse_obj(payload)


def _load_transition_prompt_package() -> Optional[TransitionPromptPackage]:
    payload = cl.user_session.get(TRANSITION_PROMPT_SESSION_KEY)
    if not payload:
        return None
    if isinstance(payload, TransitionPromptPackage):
        return payload
    return TransitionPromptPackage(
        industry_key=str(payload.get("industry_key") or DEFAULT_INDUSTRY),
        system_prompt=str(payload.get("system_prompt") or ""),
        user_prompt=str(payload.get("user_prompt") or ""),
    )


def _persist_transition_prompt_package(prompt_package: TransitionPromptPackage) -> Dict[str, Any]:
    payload = _dump_model(prompt_package)
    cl.user_session.set(TRANSITION_PROMPT_SESSION_KEY, payload)
    return payload


def _load_movement_preflight() -> Optional[Any]:
    payload = cl.user_session.get(MOVEMENT_PREFLIGHT_SESSION_KEY)
    if not payload:
        return None
    from models.transition_schemas import TransitionPreflight

    if isinstance(payload, TransitionPreflight):
        return payload
    if hasattr(TransitionPreflight, "model_validate"):
        return TransitionPreflight.model_validate(payload)
    return TransitionPreflight.parse_obj(payload)


def _load_movement_prompt_package() -> Optional[MovementPromptPackage]:
    payload = cl.user_session.get(MOVEMENT_PROMPT_SESSION_KEY)
    if not payload:
        return None
    if isinstance(payload, MovementPromptPackage):
        return payload
    return MovementPromptPackage(
        industry_key=str(payload.get("industry_key") or DEFAULT_INDUSTRY),
        system_prompt=str(payload.get("system_prompt") or ""),
        user_prompt=str(payload.get("user_prompt") or ""),
    )


def _persist_movement_prompt_package(prompt_package: MovementPromptPackage) -> Dict[str, Any]:
    payload = _dump_model(prompt_package)
    cl.user_session.set(MOVEMENT_PROMPT_SESSION_KEY, payload)
    return payload


WORKFLOW_EDIT_PENDING_RUN_ID_BY_MODE_SESSION_KEY = "workflow_edit_pending_run_ids"


def _set_pending_edit_run_id(mode: str, run_id: Optional[str]) -> Dict[str, str]:
    payload = dict(cl.user_session.get(WORKFLOW_EDIT_PENDING_RUN_ID_BY_MODE_SESSION_KEY) or {})
    if run_id:
        payload[mode] = str(run_id)
    else:
        payload.pop(mode, None)
    cl.user_session.set(WORKFLOW_EDIT_PENDING_RUN_ID_BY_MODE_SESSION_KEY, payload)
    return payload


def _get_pending_edit_run_id(mode: str) -> Optional[str]:
    payload = dict(cl.user_session.get(WORKFLOW_EDIT_PENDING_RUN_ID_BY_MODE_SESSION_KEY) or {})
    value = payload.get(mode)
    return str(value) if value else None


def _clear_mode_runtime_state(mode: str) -> None:
    _set_pending_edit_run_id(mode, None)
    if mode == TRANSITION_MODE:
        cl.user_session.set(TRANSITION_EDIT_PENDING_SESSION_KEY, False)
        cl.user_session.set(TRANSITION_PROMPT_OVERRIDE_SESSION_KEY, None)
        cl.user_session.set(TRANSITION_ARTIFACTS_SESSION_KEY, {})
    elif mode == MOVEMENT_MODE:
        cl.user_session.set(MOVEMENT_EDIT_PENDING_SESSION_KEY, False)
        cl.user_session.set(MOVEMENT_PROMPT_OVERRIDE_SESSION_KEY, None)
        cl.user_session.set(MOVEMENT_ARTIFACTS_SESSION_KEY, {})
        cl.user_session.set(MOVEMENT_PROGRESS_SESSION_KEY, [])


def _get_active_run(mode: str) -> Optional[WorkflowRunContext]:
    run = resolve_run_context(cl.user_session, mode=mode)
    return run


def _create_mode_run(mode: str, request: Any) -> WorkflowRunContext:
    run = create_workflow_run(mode=mode, request=_dump_model(request))
    persist_workflow_run(cl.user_session, run)
    set_active_run_id(cl.user_session, mode, run.run_id)
    return run


def _store_reviewed_run(
    *,
    run_id: str,
    preflight: Any,
    actioning_context: Optional[Dict[str, Any]] = None,
    prompt_package: Any,
) -> WorkflowRunContext:
    updated = update_workflow_run(
        cl.user_session,
        run_id,
        preflight=_dump_model(preflight),
        actioning_context=dict(actioning_context or {}) or None,
        prompt_package=_dump_model(prompt_package),
        prompt_override=None,
        progress=[],
        artifacts={},
        status=WorkflowRunStatus.REVIEW_READY,
    )
    if updated is None:  # pragma: no cover - defensive safeguard
        raise RuntimeError(f"Run '{run_id}' is no longer available.")
    return updated


def _store_completed_run(
    *,
    run_id: str,
    preflight: Any,
    prompt_package: Any,
    artifacts: Dict[str, str],
    progress: List[Dict[str, Any]],
) -> WorkflowRunContext:
    updated = update_workflow_run(
        cl.user_session,
        run_id,
        preflight=_dump_model(preflight),
        prompt_package=_dump_model(prompt_package),
        artifacts=dict(artifacts or {}),
        progress=[dict(event) for event in progress],
        status=WorkflowRunStatus.COMPLETE,
    )
    if updated is None:  # pragma: no cover
        raise RuntimeError(f"Run '{run_id}' is no longer available.")
    return updated


def _store_failed_run(run_id: str, mode: str, progress: List[Dict[str, Any]]) -> None:
    update_workflow_run(
        cl.user_session,
        run_id,
        progress=[dict(event) for event in progress],
        status=WorkflowRunStatus.FAILED,
    )
    _clear_mode_runtime_state(mode)


def _load_transition_request_from_run(run: WorkflowRunContext):
    payload = run.request or {}
    request = build_transition_request_from_form_response(payload)
    persist_transition_request_session(cl.user_session, request)
    return request


def _load_movement_request_from_run(run: WorkflowRunContext):
    payload = run.request or {}
    request = build_movement_request_from_form_response(payload)
    persist_movement_request_session(cl.user_session, request)
    return request


def _load_transition_preflight_from_run(run: WorkflowRunContext):
    if not run.preflight:
        return None
    from models.transition_schemas import TransitionPreflight

    payload = run.preflight
    if hasattr(TransitionPreflight, "model_validate"):
        return TransitionPreflight.model_validate(payload)
    return TransitionPreflight.parse_obj(payload)


def _load_movement_preflight_from_run(run: WorkflowRunContext):
    if not run.preflight:
        return None
    from models.transition_schemas import TransitionPreflight

    payload = run.preflight
    if hasattr(TransitionPreflight, "model_validate"):
        return TransitionPreflight.model_validate(payload)
    return TransitionPreflight.parse_obj(payload)


def _load_movement_actioning_context_from_run(run: WorkflowRunContext) -> Dict[str, Any]:
    return dict(run.actioning_context or {})


def _load_transition_prompt_from_run(run: WorkflowRunContext) -> Optional[TransitionPromptPackage]:
    payload = run.prompt_package or {}
    if not payload:
        return None
    return TransitionPromptPackage(
        industry_key=str(payload.get("industry_key") or DEFAULT_INDUSTRY),
        system_prompt=str(payload.get("system_prompt") or ""),
        user_prompt=str(payload.get("user_prompt") or ""),
    )


def _load_movement_prompt_from_run(run: WorkflowRunContext) -> Optional[MovementPromptPackage]:
    payload = run.prompt_package or {}
    if not payload:
        return None
    return MovementPromptPackage(
        industry_key=str(payload.get("industry_key") or DEFAULT_INDUSTRY),
        system_prompt=str(payload.get("system_prompt") or ""),
        user_prompt=str(payload.get("user_prompt") or ""),
    )


def _get_transition_orchestrator():
    orchestrator = cl.user_session.get("transition_playbook_orchestrator")
    if orchestrator is None:
        from services.transition_playbook_orchestrator import TransitionPlaybookOrchestrator

        orchestrator = TransitionPlaybookOrchestrator()
        cl.user_session.set("transition_playbook_orchestrator", orchestrator)
    return orchestrator


def _get_movement_orchestrator():
    orchestrator = cl.user_session.get("movement_brief_orchestrator")
    if orchestrator is None:
        from services.movement_brief_orchestrator import MovementBriefOrchestrator

        orchestrator = MovementBriefOrchestrator()
        cl.user_session.set("movement_brief_orchestrator", orchestrator)
    return orchestrator


def _build_transition_progress_callback(progress_msg: cl.Message, request_payload: Dict[str, Any]):
    events: List[Dict[str, Any]] = []

    async def _progress_callback(event: Dict[str, Any]):
        try:
            events.append(dict(event))
            progress_msg.content = build_transition_progress_content(request_payload, events)
            await progress_msg.update()
        except Exception as exc:
            logger.warning("Transition progress callback error: %s", exc)

    return events, _progress_callback


def _build_movement_progress_callback(progress_msg: cl.Message, request_payload: Dict[str, Any]):
    events: List[Dict[str, Any]] = []

    async def _progress_callback(event: Any):
        try:
            normalized = _normalize_movement_progress_event(event)
            logger.info(
                "Movement progress event stage=%s status=%s message=%s",
                normalized.get("stage"),
                normalized.get("status"),
                str(normalized.get("message") or "")[:200],
            )
            events.append(normalized)
            persist_movement_progress_session(cl.user_session, events)
            progress_msg.content = build_movement_progress_content(request_payload, events)
            await progress_msg.update()
        except Exception as exc:
            logger.warning("Movement progress callback error: %s", exc)

    return events, _progress_callback


async def _run_transition_preflight_flow(run_id: str) -> None:
    run = load_workflow_run(cl.user_session, run_id)
    if run is None:
        await cl.Message("That transition run is no longer available. Please reopen the form.").send()
        return
    request = _load_transition_request_from_run(run)
    progress_msg = cl.Message(content="**Transition Playbook**\n\nInitializing validation...")
    await progress_msg.send()

    request_payload = _dump_model(request)
    events, progress_cb = _build_transition_progress_callback(progress_msg, request_payload)
    try:
        orchestrator = _get_transition_orchestrator()
        preflight = await orchestrator.build_preflight(request, progress_cb=progress_cb)
        prompt_package = _load_transition_prompt_from_run(run)
        if not prompt_package:
            from services.transition_prompt_builder import TransitionPromptBuilder

            prompt_package = TransitionPromptBuilder().build(preflight)

        _store_reviewed_run(run_id=run_id, preflight=preflight, prompt_package=prompt_package)
        cl.user_session.set(TRANSITION_PREFLIGHT_SESSION_KEY, _dump_model(preflight))
        _persist_transition_prompt_package(prompt_package)
        _clear_mode_runtime_state(TRANSITION_MODE)

        if events:
            progress_msg.content = build_transition_progress_content(request_payload, events)
            await progress_msg.update()

        await present_transition_preflight_review(preflight, prompt_package, run_id=run_id)
    except Exception as exc:
        logger.exception("Transition preflight failed: %s", exc)
        _store_failed_run(run_id, TRANSITION_MODE, events)
        progress_msg.content = "**Transition Playbook**\n\nValidation failed."
        await progress_msg.update()
        await cl.Message(
            "Transition validation failed. Check the backend ProConnect token and try again."
        ).send()


async def _run_movement_preflight_flow(run_id: str) -> None:
    run = load_workflow_run(cl.user_session, run_id)
    if run is None:
        await cl.Message("That people movement run is no longer available. Please reopen the form.").send()
        return
    request = _load_movement_request_from_run(run)
    progress_msg = cl.Message(content="**People Movement Brief**\n\nInitializing named-move validation...")
    await progress_msg.send()

    request_payload = _dump_model(request)
    events, progress_cb = _build_movement_progress_callback(progress_msg, request_payload)
    try:
        orchestrator = _get_movement_orchestrator()
        preflight_result = await orchestrator.build_preflight(request, progress_cb=progress_cb)
        _store_reviewed_run(
            run_id=run_id,
            preflight=preflight_result.preflight,
            actioning_context=preflight_result.actioning_context,
            prompt_package=preflight_result.prompt_package,
        )
        cl.user_session.set(MOVEMENT_PREFLIGHT_SESSION_KEY, _dump_model(preflight_result.preflight))
        _persist_movement_prompt_package(preflight_result.prompt_package)
        _clear_mode_runtime_state(MOVEMENT_MODE)
        cl.user_session.set(MOVEMENT_BRIEF_SESSION_KEY, None)

        if events:
            progress_msg.content = build_movement_progress_content(request_payload, events)
            await progress_msg.update()
        logger.info(
            "Movement preflight ready run_id=%s person=%s destination=%s",
            run_id,
            request.person_name,
            request.to_company,
        )

        await present_movement_preflight_review(
            request,
            preflight_result.preflight,
            preflight_result.prompt_package,
            run_id=run_id,
        )
    except Exception as exc:
        logger.exception("Movement preflight failed: %s", exc)
        _store_failed_run(run_id, MOVEMENT_MODE, events)
        progress_msg.content = "**People Movement Brief**\n\nMove validation failed."
        await progress_msg.update()
        await cl.Message(
            "People movement validation failed. Confirm the backend ProConnect token and try again."
        ).send()


async def _run_movement_research_flow(run_id: str) -> None:
    run = load_workflow_run(cl.user_session, run_id)
    if run is None:
        await cl.Message("That people movement run is no longer available. Re-open the movement form first.").send()
        return
    request = _load_movement_request_from_run(run)
    preflight = _load_movement_preflight_from_run(run)
    actioning_context = _load_movement_actioning_context_from_run(run)
    prompt_package = _load_movement_prompt_from_run(run)
    if not request or not preflight or not prompt_package:
        await cl.Message("No people movement scenario is loaded. Re-open the movement form first.").send()
        return

    logger.info(
        "Movement research requested run_id=%s person=%s source=%s destination=%s",
        run_id,
        request.person_name,
        request.from_company,
        request.to_company,
    )
    progress_msg = cl.Message(content="**People Movement Brief**\n\nStarting research run...")
    await progress_msg.send()

    request_payload = _dump_model(request)
    events, progress_cb = _build_movement_progress_callback(progress_msg, request_payload)
    prompt_override = run.prompt_override
    try:
        update_workflow_run(cl.user_session, run_id, status=WorkflowRunStatus.RUNNING, progress=[])
        orchestrator = _get_movement_orchestrator()
        if hasattr(orchestrator, "run_from_reviewed_context"):
            result = await orchestrator.run_from_reviewed_context(
                request=request,
                preflight=preflight,
                actioning_context=actioning_context,
                prompt_package=prompt_package,
                run_id=run_id,
                progress_cb=progress_cb,
            )
        else:
            result = await orchestrator.run(
                request,
                reviewed_preflight=preflight,
                reviewed_actioning_context=actioning_context,
                reviewed_prompt_package=prompt_package,
                progress_cb=progress_cb,
                prompt_override=prompt_override,
            )
        logger.info(
            "Movement research completed run_id=%s visible_rows=%s",
            run_id,
            len(getattr(result.movement_brief, "movement_rows", []) or []),
        )

        artifacts = build_movement_artifacts(result)
        persist_movement_artifacts_session(cl.user_session, artifacts)
        cl.user_session.set(MOVEMENT_BRIEF_SESSION_KEY, _dump_model(result.movement_brief))

        events.append(
            {
                "stage": "brief_assembly",
                "message": "Movement brief assembled.",
                "status": "complete",
            }
        )
        persist_movement_progress_session(cl.user_session, events)
        progress_msg.content = build_movement_progress_content(request_payload, events)
        await progress_msg.update()

        _store_completed_run(
            run_id=run_id,
            preflight=result.preflight,
            prompt_package=result.prompt_package,
            artifacts=artifacts,
            progress=events,
        )
        cl.user_session.set(MOVEMENT_PREFLIGHT_SESSION_KEY, _dump_model(result.preflight))
        _persist_movement_prompt_package(result.prompt_package)
        await present_movement_brief(result, run_id=run_id)
    except Exception as exc:
        logger.exception("Movement research flow failed: %s", exc)
        _store_failed_run(run_id, MOVEMENT_MODE, events)
        progress_msg.content = "**People Movement Brief**\n\nMovement research failed."
        await progress_msg.update()
        await cl.Message(
            "People movement research failed. Confirm Deep Research, ProConnect, and credentials access, then retry."
        ).send()


async def _run_transition_research_flow(run_id: str) -> None:
    run = load_workflow_run(cl.user_session, run_id)
    if run is None:
        await cl.Message("That transition run is no longer available. Re-open the transition form first.").send()
        return
    request = _load_transition_request_from_run(run)
    preflight = _load_transition_preflight_from_run(run)
    prompt_package = _load_transition_prompt_from_run(run)
    if not request or not preflight or not prompt_package:
        await cl.Message("No transition scenario is loaded. Re-open the transition form first.").send()
        return

    progress_msg = cl.Message(content="**Transition Playbook**\n\nStarting research run...")
    await progress_msg.send()

    request_payload = _dump_model(request)
    events, progress_cb = _build_transition_progress_callback(progress_msg, request_payload)
    prompt_override = run.prompt_override

    try:
        update_workflow_run(cl.user_session, run_id, status=WorkflowRunStatus.RUNNING, progress=[])
        orchestrator = _get_transition_orchestrator()
        if hasattr(orchestrator, "run_transition_playbook_from_reviewed_context"):
            result = await orchestrator.run_transition_playbook_from_reviewed_context(
                request=request,
                preflight=preflight,
                prompt_package=prompt_package,
                run_id=run_id,
                progress_cb=progress_cb,
            )
        else:
            result = await orchestrator.run_transition_playbook(
                request,
                reviewed_preflight=preflight,
                reviewed_prompt_package=prompt_package,
                reviewed_run_id=run_id,
                progress_cb=progress_cb,
                prompt_override=prompt_override,
            )

        brief = build_transition_brief(result)
        artifacts = build_transition_artifacts(result)
        cl.user_session.set(TRANSITION_ARTIFACTS_SESSION_KEY, artifacts)

        if events:
            progress_msg.content = build_transition_progress_content(request_payload, events)
            await progress_msg.update()

        _store_completed_run(
            run_id=run_id,
            preflight=result.preflight,
            prompt_package=result.prompt_package,
            artifacts=artifacts,
            progress=events,
        )
        cl.user_session.set(TRANSITION_PREFLIGHT_SESSION_KEY, _dump_model(result.preflight))
        _persist_transition_prompt_package(result.prompt_package)
        await present_transition_brief(brief, run_id=run_id)
    except Exception as exc:
        logger.exception("Transition research flow failed: %s", exc)
        _store_failed_run(run_id, TRANSITION_MODE, events)
        progress_msg.content = "**Transition Playbook**\n\nResearch run failed."
        await progress_msg.update()
        await cl.Message(
            "Transition research failed. Confirm the Deep Research environment and ProConnect token, then retry."
        ).send()


def _normalize_movement_progress_event(event: Any) -> Dict[str, Any]:
    if isinstance(event, dict):
        normalized = dict(event)
    else:
        normalized = {"message": str(event or "")}

    message = _movement_text(normalized.get("message") or "")
    stage = _movement_text(normalized.get("stage") or "")
    if not stage:
        stage = _infer_movement_stage(message)
    normalized["message"] = message
    normalized["stage"] = stage or "movement"
    normalized["status"] = _movement_text(normalized.get("status") or "in_progress") or "in_progress"
    return normalized


def _infer_movement_stage(message: str) -> str:
    lowered = message.lower()
    if "signal evidence" in lowered or "account signals" in lowered:
        return "account_signals"
    if "extracting movement rows" in lowered:
        return "movement_rows"
    if "matching movement leverage" in lowered or "deep-enriching top movement rows" in lowered:
        return "proconnect"
    if "validating credentials" in lowered:
        return "credentials"
    if "assembling movement brief" in lowered:
        return "brief_assembly"
    if "deep research" in lowered:
        return "deep_research_poll"
    return ""


def _movement_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()

# --- Enhanced system integration ---

async def present_enhanced_response(response: Dict[str, Any]) -> None:
    """
    Present enhanced system response to the user.
    
    Args:
        response: Formatted response from enhanced system
    """
    try:
        response_type = response.get("type", "unknown")
        
        # Define helper functions at the top so they're available for all response types
        async def _send_sources(citations, heading="Sources"):
            if not citations:
                return
            lines = [f"**{heading}:**"]
            # Show ALL sources - extremely high limit
            for citation in citations[:1000]:
                title = citation.get("title", "Source")
                url = citation.get("url", "#")
                lines.append(f" [{title}]({url})")
            await cl.Message("\n".join(lines)).send()
        
        if response_type == "error":
            error_msg = response.get("error", "Unknown error")
            details = response.get("details", [])
            error_text = f" **Error**: {error_msg}"
            if details:
                error_text += f"\n\n**Details**:\n" + "\n".join([f" {detail}" for detail in details])
            await cl.Message(error_text).send()
            return
        
        if response_type == "deep_research":
            summary = response.get("summary", "")
            sections = response.get("sections", []) or []
            lines = ["#   Deep Research Findings", ""]
            if summary:
                lines.append(summary)
                lines.append("")
            for idx, section in enumerate(sections, 1):
                title = section.get("title") or f"Section {idx}"
                content = section.get("content", "")
                lines.append(f"## {title}")
                if content:
                    lines.append(content)
                lines.append("")
            await cl.Message("\n".join(lines).strip()).send()

            if response.get("citations"):
                await _send_sources(response.get("citations", []))

            metadata = response.get("metadata", {}) or {}
            meta_bits = []
            if metadata.get("run_id"):
                meta_bits.append(f"Run ID: `{metadata['run_id']}`")
            if metadata.get("thread_id"):
                meta_bits.append(f"Thread ID: `{metadata['thread_id']}`")
            if meta_bits:
                await cl.Message(" " + " | ".join(meta_bits)).send()
            return

        profiles_cache = cl.user_session.get("company_profiles") or {}

        def _lookup_profile(name: Optional[str]) -> Optional[Dict[str, Any]]:
            if not name:
                return None
            candidates = [name, name.lower(), name.replace("_", " "), name.replace("_", " ").lower()]
            for candidate in candidates:
                if candidate in profiles_cache:
                    return profiles_cache[candidate]
            return None

        async def _present_events(company: str, events: List[Dict[str, Any]], summary: str = ""):
            if not events:
                return
            lines = [f"#  {company}  Comprehensive Analysis Results", ""]
            if summary:
                lines.append(f"**Executive Summary:** {summary}")
                lines.append("")
            lines.append(f"Identified {len(events)} significant event(s) requiring attention.")
            lines.append("")

            for idx, event in enumerate(events[:10], 1):
                title = event.get("title", f"Event #{idx}")
                insights = event.get("insights", {})
                citations = event.get("citations", [])

                lines.append(f"##  Event #{idx}: {title}")
                lines.append("")

                if isinstance(insights, dict):
                    what = insights.get("what_happened", "")
                    why = insights.get("why_it_matters", "")
                    consulting_angle = insights.get("consulting_angle", "")
                    if what:
                        lines.append(f"**What Happened:** {what}")
                        lines.append("")
                    if why:
                        lines.append(f"**Why It Matters:** {why}")
                        lines.append("")
                    if consulting_angle:
                        lines.append(f"** Consulting Angle:** {consulting_angle}")
                        lines.append("")

                    detail_pairs = []
                    for key in ("need_type", "service_line", "urgency", "priority", "timeline"):
                        value = insights.get(key)
                        if value:
                            detail_pairs.append((key.replace("_", " ").title(), value))
                    if detail_pairs:
                        lines.append("** Business Impact:**")
                        for label, value in detail_pairs:
                            lines.append(f"- **{label}:** {value}")
                        lines.append("")

                    categories = insights.get("service_categories")
                    if categories and isinstance(categories, list):
                        lines.append(f"** Service Categories:** {', '.join(categories)}")
                        lines.append("")

                    industry_context = insights.get("industry_overview")
                    if industry_context:
                        lines.append(f"** Industry Context:** {industry_context}")
                        lines.append("")

                    source_urls = insights.get("source_urls")
                    if source_urls and isinstance(source_urls, list):
                        lines.append("** Sources:**")
                        for url in source_urls[:10]:
                            lines.append(f"- {url}")
                        lines.append("")

                if citations:
                    lines.append("** Additional Sources:**")
                    for citation in citations[:10]:
                        title = citation.get("title", citation.get("url", "Source"))
                        url = citation.get("url", "#")
                        lines.append(f"- [{title}]({url})")
                    lines.append("")

                lines.append("---")
                lines.append("")

            await cl.Message("\n".join(lines)).send()

        async def _present_raw_gwbs(company: str, raw_sections: List[Dict[str, Any]]):
            if not raw_sections:
                return
            lines = [f"#  Raw Research Results for {company}", "", "## Grounding with Bing Search (GWBS) Findings", ""]
            for section in raw_sections:
                title = section.get("title") or section.get("scope", "").replace("_", " ").title()
                summary = section.get("summary", "")
                citations = section.get("citations", [])

                lines.append(f"### {title}")
                lines.append("")
                if summary:
                    lines.append(summary)
                    lines.append("")
                if citations:
                    lines.append("**Sources:**")
                    for citation in citations[:10]:
                        cite_title = citation.get("title", citation.get("url", "Source"))
                        cite_url = citation.get("url", "#")
                        lines.append(f"- [{cite_title}]({cite_url})")
                    lines.append("")

            await cl.Message("\n".join(lines)).send()

        async def _present_account_context(company: str) -> None:
            profile = _lookup_profile(company)
            if not profile:
                return

            def _from_people(key: str):
                people = profile.get("people") or {}
                return (
                    people.get(key)
                    or people.get(key.lower())
                    or people.get(key.replace("_", ""))
                    or people.get(key[0].lower() + key[1:])
                    or []
                )

            def _from_opportunities(key: str):
                opps = profile.get("opportunities") or {}
                return (
                    opps.get(key)
                    or opps.get(key.lower())
                    or opps.get(key[0].lower() + key[1:])
                    or []
                )

            lines = ["#  Account Context", ""]

            description = profile.get("description") or profile.get("company_description")
            if description and description != "N/A":
                lines.append(f"**Description:** {description}")
                lines.append("")

            overview_pairs = []
            for label, key in (
                ("Company", "company_name"),
                ("Industry", "industry"),
                ("Size", "size"),
                ("Annual Revenue", "revenue"),
                ("Website", "website"),
            ):
                value = profile.get(key)
                if value and value != "N/A":
                    overview_pairs.append((label, value))
            if overview_pairs:
                lines.append("**Overview**")
                for label, value in overview_pairs:
                    lines.append(f"- **{label}:** {value}")
                lines.append("")

            raw_key_buyers = _from_people("keyBuyers") or _from_people("key_buyers")
            if raw_key_buyers:
                sorted_buyers = sorted(
                    raw_key_buyers,
                    key=lambda b: b.get("numberOfWins", 0),
                    reverse=True,
                )
                lines.append("**Key Buyers**")
                for buyer in sorted_buyers[:2]:
                    name = buyer.get("name", "Unknown")
                    lines.append(f" {name}")
                    if buyer.get("title"):
                        lines.append(f"  - Title: {buyer['title']}")
                    if buyer.get("emailAddress"):
                        lines.append(f"  - Email: {buyer['emailAddress']}")
                    if buyer.get("linkedinUrl"):
                        lines.append(f"  - LinkedIn: {buyer['linkedinUrl']}")
                    wins = buyer.get("numberOfWins")
                    last_win = buyer.get("lastOpportunityWonDate")
                    if wins or last_win:
                        detail = []
                        if wins:
                            detail.append(f"wins: {wins}")
                        if last_win:
                            detail.append(f"last win: {last_win[:10]}")
                        lines.append(f"  - Performance: {', '.join(detail)}")
                    close_won = (
                        buyer.get("closeWonOpps")
                        or buyer.get("close_won_opps")
                        or []
                    )
                    if close_won:
                        lines.append("  - Recent Wins:")
                        for opp in close_won[:3]:
                            if isinstance(opp, dict):
                                opp_name = opp.get("name", "Unnamed Opportunity")
                                solution = opp.get("solution")
                                close_date = opp.get("opportunityCloseDate")
                                extra = []
                                if solution:
                                    extra.append(solution)
                                if close_date:
                                    extra.append(close_date[:10])
                                suffix = f" ({', '.join(extra)})" if extra else ""
                                lines.append(f"     {opp_name}{suffix}")
                            else:
                                lines.append(f"     {opp}")
                    lines.append("")

            raw_alumni = _from_people("alumni") or _from_people("protiviti_alumni")
            if raw_alumni:
                lines.append("**Protiviti Alumni**")
                for alum in raw_alumni[:3]:
                    if isinstance(alum, dict):
                        name = alum.get("name", "Unknown")
                        lines.append(f" {name}")
                        if alum.get("title"):
                            lines.append(f"  - Title: {alum['title']}")
                        if alum.get("emailAddress"):
                            lines.append(f"  - Email: {alum['emailAddress']}")
                        if alum.get("linkedinUrl"):
                            lines.append(f"  - LinkedIn: {alum['linkedinUrl']}")
                        lines.append("")
                    else:
                        lines.append(f" {alum}")
                if lines[-1] != "":
                    lines.append("")

            open_opps = _from_opportunities("open")
            if open_opps:
                lines.append("**Active Opportunities**")
                for opp in open_opps[:3]:
                    if isinstance(opp, dict):
                        name = opp.get("name", "Unnamed Opportunity")
                        details = []
                        for key in ("value", "value_usd", "status"):
                            value = opp.get(key)
                            if value:
                                details.append(str(value))
                        suffix = f" ({', '.join(details)})" if details else ""
                        lines.append(f" {name}{suffix}")
                    else:
                        lines.append(f" {opp}")
                lines.append("")

            await cl.Message("\n".join(lines).rstrip()).send()

        async def _present_company_briefing(payload: Dict[str, Any]) -> None:
            company = payload.get("company", "Company")
            summary = payload.get("summary", "")
            raw_gwbs = payload.get("raw_gwbs", [])
            events = payload.get("events", [])

            await _present_raw_gwbs(company, raw_gwbs)

            if summary and not events:
                await cl.Message(summary).send()

            await _present_events(company, events, summary)
            await _present_account_context(company)

        if response_type == "company_briefing":
            await _present_company_briefing(response)
            await _send_sources(response.get("citations", []))

        elif response_type == "mixed_request":
            sections = response.get("sections", [])
            for section in sections:
                raw_task_type = section.get("task_type") or ""
                task_type = raw_task_type.strip().lower()
                if task_type == "company_briefing":
                    briefing_payload = section.get("briefing") or {
                        "company": section.get("target") or response.get("company"),
                        "summary": section.get("content", ""),
                        "events": section.get("events", []),
                        "raw_gwbs": section.get("raw_gwbs", []),
                    }
                    if not briefing_payload.get("company"):
                        briefing_payload["company"] = response.get("company", "Company")
                    await _present_company_briefing(briefing_payload)
                    await _send_sources(section.get("citations", []))
                else:
                    display_task = raw_task_type.replace('_', ' ').title() if raw_task_type else "Section"
                    header = f"**{display_task} - {section.get('target', response.get('company', 'Unknown'))}**"
                    content = section.get("content", "")
                    if content:
                        await cl.Message(f"{header}\n\n{content}").send()
                    await _send_sources(section.get("citations", []))

            await _send_sources(response.get("citations", []))
            if response.get("company"):
                await _present_account_context(response.get("company"))

        else:
            summary = response.get("summary", "")
            if summary:
                await cl.Message(summary).send()

            sections = response.get("sections", [])
            for section in sections:
                header = f"**{section.get('task_type', 'Section').replace('_', ' ').title()} - {section.get('target', response.get('company', 'Unknown'))}**"
                content = section.get("content", "")
                if content:
                    await cl.Message(f"{header}\n\n{content}").send()
                await _send_sources(section.get("citations", []))

            await _present_events(response.get("company", "Company"), response.get("events", []), summary)
            await _send_sources(response.get("citations", []))
            if response.get("company"):
                await _present_account_context(response.get("company"))

        # Present metadata
        execution_time = response.get("execution_time", 0)
        confidence = response.get("confidence", 0)
        if execution_time > 0 or confidence > 0:
            metadata_text = ""
            if execution_time > 0:
                metadata_text += f" **Execution time**: {execution_time:.2f}s"
            if confidence > 0:
                metadata_text += f" |  **Confidence**: {confidence:.1%}"
            if metadata_text:
                await cl.Message(metadata_text).send()
        
    except Exception as e:
        logger.error(f"Error presenting enhanced response: {e}")
        await cl.Message("  Response generated successfully.").send()

async def handle_old_system(qtype: QueryType, payload: Dict[str, Any], ctx: ConversationContext, 
                           bing_agent: BingDataExtractionAgent, analyst_agent: AnalystAgent, 
                           fup: FollowUpHandler, user_text: str) -> None:
    """
    Handle requests using the old system as fallback.
    
    Args:
        qtype: Query type from old router
        payload: Payload from old router
        ctx: Conversation context
        bing_agent: Bing data extraction agent
        analyst_agent: Analyst agent
        fup: Follow-up handler
        user_text: Original user input
    """
    try:
        if qtype == QueryType.CLARIFICATION:
            await cl.Message("Which company should I analyze? You can type a name (e.g., `Capital One`) or a ticker (e.g., `COF`).").send()
            return

        elif qtype == QueryType.NEW_ANALYSIS:
            await handle_new_analysis(payload, ctx, bing_agent, analyst_agent, original_text=user_text)
            return

        elif qtype == QueryType.FOLLOW_UP:
            await handle_follow_up(ctx, fup, user_text)
            return

        elif qtype == QueryType.COMPARE_COMPANIES:
            await handle_company_comparison(payload, ctx, bing_agent, analyst_agent)
            return

        elif qtype == QueryType.GENERAL_RESEARCH:
            await handle_general_research(payload, bing_agent)
            return

        else:
            await cl.Message("I didn't quite catch that. Try a company name or ask a specific follow-up.").send()
            return
            
    except Exception as e:
        logger.error(f"Error in old system handler: {e}")
        await cl.Message("Sorry, I encountered an error processing your request. Please try again.").send()

# --- Chainlit event handlers ---

@cl.on_chat_start
async def start():
    """Initialize the chat session."""
    try:
        await _init_singletons()
        ctx = _get_ctx()
        
        # Send welcome message
        welcome_msg = (
            "**Company Intelligence (Chat)**\n\n"
            "- Type a company (e.g., Capital One or ticker COF) for a full analysis.\n"
            "- Then ask follow-ups (risk, competitors, regulatory, strategy, timeline, etc.).\n"
            "- I'll remember the context and only search when needed.\n\n"
            "**New capabilities:**\n"
            "- Ask about any company (not just hardcoded ones)\n"
            "- General research questions (e.g., 'What are the top financial companies?')\n"
            "- Mixed requests (e.g., 'Tell me about Tesla and its competitors')"
        )
        await cl.Message(welcome_msg).send()

        current_mode = cl.user_session.get(DEEP_RESEARCH_SESSION_KEY)
        if current_mode not in {"standard", "deep", MOVEMENT_MODE, TRANSITION_MODE}:
            current_mode = "deep" if AppConfig.ENABLE_DEEP_RESEARCH else DEFAULT_MODE
            cl.user_session.set(DEEP_RESEARCH_SESSION_KEY, current_mode)
        logger.info(
            "Session initialized",
            extra={
                "session_id": cl.user_session.get("session_id"),
                "initial_mode": current_mode,
                "feature_flag": AppConfig.ENABLE_DEEP_RESEARCH,
            },
        )

        if AppConfig.ENABLE_DEEP_RESEARCH:
            # Store loader in session for later use
            from services.prompt_loader import PromptLoader
            loader = PromptLoader()
            cl.user_session.set("prompt_loader", loader)
            
            # Keep the mode picker as a persistent Message with actions so the
            # options remain visible until the user chooses a mode.
            actions = [
                cl.Action(
                    name="set_mode",
                    label="Standard Analysis",
                    payload={"mode": "standard"},
                ),
                cl.Action(
                    name="set_mode",
                    label="Deep Research (slower)",
                    payload={"mode": "deep"},
                ),
                cl.Action(
                    name="set_mode",
                    label="People Movement Brief",
                    payload={"mode": MOVEMENT_MODE},
                ),
                cl.Action(
                    name="set_mode",
                    label="Transition Playbook",
                    payload={"mode": TRANSITION_MODE},
                ),
            ]
            await cl.Message(
                content="**Step 1:** Select research mode:",
                actions=actions
            ).send()

        else:
            await cl.Message(
                " Deep Research mode is unavailable in this environment. Running with the standard analysis pipeline."
            ).send()
        
    except Exception as e:
        await handle_error(e, "chat_start", "Failed to initialize chat session. Please refresh and try again.")


@cl.action_callback("set_mode")
async def update_mode(action: cl.Action):
    """Handle mode selection actions."""
    selected = (action.payload or {}).get("mode", DEFAULT_MODE)
    session_id = cl.user_session.get("session_id")
    logger.info(
        "Mode action received: name=%s payload=%s resolved=%s session=%s",
        action.name,
        action.payload,
        selected,
        session_id,
    )
    if selected in {"deep", TRANSITION_MODE} and not AppConfig.ENABLE_DEEP_RESEARCH:
        await cl.Message("Deep Research is not enabled in this environment.").send()
        cl.user_session.set(DEEP_RESEARCH_SESSION_KEY, DEFAULT_MODE)
        return
    if selected == MOVEMENT_MODE and not AppConfig.ENABLE_DEEP_RESEARCH:
        await cl.Message("People Movement Brief mode is not available in this environment.").send()
        cl.user_session.set(DEEP_RESEARCH_SESSION_KEY, DEFAULT_MODE)
        return

    cl.user_session.set(DEEP_RESEARCH_SESSION_KEY, selected)
    logger.info(
        "Mode updated session=%s stored=%s",
        session_id,
        cl.user_session.get(DEEP_RESEARCH_SESSION_KEY),
    )
    label = {
        "deep": "Deep Research",
        MOVEMENT_MODE: "People Movement Brief",
        TRANSITION_MODE: "Transition Playbook",
    }.get(selected, "Standard Analysis")
    await cl.Message(f"✓ Mode: **{label}**").send()
    
    # If Deep Research mode selected, show the research parameters form
    if selected == "deep":
        await show_research_form()
    elif selected == MOVEMENT_MODE:
        await show_movement_form()
    elif selected == TRANSITION_MODE:
        await show_transition_form()


async def show_research_form():
    """Show the research parameters form using CustomElement."""
    from services.prompt_loader import PromptLoader
    loader = PromptLoader()
    industries = loader.get_available_industries()
    
    # Build sector options for the form
    sectors = [
        {"value": key, "label": meta["display_name"]}
        for key, meta in industries.items()
    ]
    
    # Create the custom element form
    form_element = cl.CustomElement(
        name="ResearchForm",
        display="inline",
        props={
            "sectors": sectors,
            "sector": "general",
            "company": "",
            "signals": "",
            "service_lines": "",
            "geography": "",
            "min_value": "",
            "time_window": "",
            "max_opportunities": "10"
        }
    )
    
    # Ask for element - this blocks until user submits or cancels
    # Note: AskElementMessage takes 'element' (singular), not 'elements'
    response = await cl.AskElementMessage(
        content="**Configure your research parameters below:**",
        element=form_element,
        timeout=300  # 5 minutes
    ).send()
    
    if response and response.get("submitted"):
        payload = extract_element_response_payload(
            response,
            expected_keys=(
                "sector",
                "company",
                "signals",
                "service_lines",
                "geography",
                "min_value",
                "time_window",
                "max_opportunities",
                "other_context",
            ),
        )
        # User submitted the form - fields are directly on the response object
        logger.info("Research form submitted: response_keys=%s payload_keys=%s", list(response.keys()), list(payload.keys()))
        
        # Extract form data from response (fields are directly accessible)
        form_data = {
            "sector": payload.get("sector", DEFAULT_INDUSTRY),
            "company": payload.get("company", ""),
            "signals": payload.get("signals", ""),
            "service_lines": payload.get("service_lines", ""),
            "geography": payload.get("geography", ""),
            "min_value": payload.get("min_value", ""),
            "time_window": payload.get("time_window", ""),
            "max_opportunities": payload.get("max_opportunities", "10"),
            "other_context": payload.get("other_context", "")
        }
        
        # Store in session
        cl.user_session.set(RESEARCH_PARAMS_SESSION_KEY, form_data)
        cl.user_session.set(INDUSTRY_PROMPT_SESSION_KEY, form_data.get("sector", DEFAULT_INDUSTRY))
        # Generate the prompt (no auto-run - user copies and pastes)
        await generate_research_prompt(form_data)
    else:
        # User cancelled or timed out
        await cl.Message("Form cancelled or timed out. You can type your research question directly.").send()


async def show_transition_form():
    """Show the transition playbook intake form using CustomElement."""
    from services.prompt_loader import PromptLoader

    loader = PromptLoader()
    industries = loader.get_available_industries()
    industry_options = [
        {"value": key, "label": meta["display_name"]}
        for key, meta in industries.items()
    ]

    active_run = _get_active_run(TRANSITION_MODE)
    request = _load_transition_request_from_run(active_run) if active_run else load_transition_request_session(cl.user_session)
    props = build_transition_form_props(industry_options=industry_options)
    if request:
        props.update(_dump_model(request))

    form_element = cl.CustomElement(
        name="TransitionForm",
        display="inline",
        props=props,
    )

    response = await cl.AskElementMessage(
        content="**Configure the transition scenario below:**",
        element=form_element,
        timeout=300,
    ).send()

    if response and response.get("submitted"):
        logger.info("Transition form submitted: response_keys=%s", list(response.keys()))
        try:
            request = build_transition_request_from_form_response(response)
        except Exception as exc:
            logger.warning("Transition form submission failed validation: %s", exc)
            await cl.Message(
                f"Transition form submission was incomplete or invalid: {exc}"
            ).send()
            await show_transition_form()
            return
        persist_transition_request_session(cl.user_session, request)
        run = _create_mode_run(TRANSITION_MODE, request)
        cl.user_session.set(TRANSITION_PREFLIGHT_SESSION_KEY, None)
        cl.user_session.set(TRANSITION_PROMPT_SESSION_KEY, None)
        _clear_mode_runtime_state(TRANSITION_MODE)
        await _run_transition_preflight_flow(run.run_id)
    else:
        _clear_mode_runtime_state(TRANSITION_MODE)
        await cl.Message("Transition form cancelled or timed out.").send()


async def show_movement_form():
    """Show the people movement intake form using CustomElement."""
    from services.prompt_loader import PromptLoader

    loader = PromptLoader()
    industries = loader.get_available_industries()
    industry_options = [
        {"value": key, "label": meta["display_name"]}
        for key, meta in industries.items()
    ]

    active_run = _get_active_run(MOVEMENT_MODE)
    request = _load_movement_request_from_run(active_run) if active_run else load_movement_request_session(cl.user_session)
    props = build_movement_form_props(
        industry_options=industry_options,
        industry_override=getattr(request, "industry_override", None) or "financial_services",
    )
    if request:
        props.update(_dump_model(request))

    form_element = cl.CustomElement(
        name="MovementScanForm",
        display="inline",
        props=props,
    )

    response = await cl.AskElementMessage(
        content="**Configure the people movement scan below:**",
        element=form_element,
        timeout=300,
    ).send()

    if response and response.get("submitted"):
        logger.info("Movement form submitted: response_keys=%s", list(response.keys()))
        try:
            request = build_movement_request_from_form_response(response)
        except Exception as exc:
            logger.warning("Movement form submission failed validation: %s", exc)
            await cl.Message(
                f"Movement form submission was incomplete or invalid: {exc}"
            ).send()
            await show_movement_form()
            return
        persist_movement_request_session(cl.user_session, request)
        run = _create_mode_run(MOVEMENT_MODE, request)
        cl.user_session.set(MOVEMENT_BRIEF_SESSION_KEY, None)
        cl.user_session.set(MOVEMENT_PREFLIGHT_SESSION_KEY, None)
        cl.user_session.set(MOVEMENT_PROMPT_SESSION_KEY, None)
        _clear_mode_runtime_state(MOVEMENT_MODE)
        await _run_movement_preflight_flow(run.run_id)
    else:
        _clear_mode_runtime_state(MOVEMENT_MODE)
        await cl.Message("Movement form cancelled or timed out.").send()


async def present_transition_preflight_review(preflight, prompt_package, *, run_id: str):
    """Render the compact transition validation review surface."""
    payload = build_transition_preflight_review(preflight, prompt_package, run_id=run_id)
    actions = _build_review_actions(payload)
    await cl.Message(content=payload["content"]).send()

    async def _ask_next_action():
        response = await cl.AskActionMessage(
            content="Choose the next step for this transition run.",
            actions=actions,
            timeout=900,
            raise_on_timeout=False,
        ).send()
        logger.info(
            "Transition review selection run_id=%s action=%s",
            run_id,
            str((response or {}).get("name") or "timeout"),
        )
        return response

    await run_review_action_loop(
        ask_next_action=_ask_next_action,
        view_action_name=ACTION_VIEW_PROMPT,
        edit_action_name=ACTION_EDIT_PROMPT,
        adjust_action_name=ACTION_ADJUST_TRANSITION,
        run_action_name=ACTION_RUN_RESEARCH,
        on_view_prompt=lambda: _show_generated_prompt_message(
            title="Generated Transition Prompt",
            prompt_text=prompt_package.user_prompt,
        ),
        on_edit_prompt=lambda: _enter_prompt_edit_mode(
            mode=TRANSITION_MODE,
            run_id=run_id,
            prompt_text=prompt_package.user_prompt,
            edit_pending_key=TRANSITION_EDIT_PENDING_SESSION_KEY,
            descriptor="transition",
        ),
        on_adjust=show_transition_form,
        on_run=lambda: _run_transition_research_flow(run_id),
        on_timeout=lambda: cl.Message(
            "Transition review timed out. Re-open the transition form if you want to continue."
        ).send(),
        on_unknown_action=lambda action_name: cl.Message(
            f"Unknown transition review action: {action_name or 'missing action name'}."
        ).send(),
    )


async def present_movement_preflight_review(request, preflight, prompt_package, *, run_id: str):
    """Render the named-move review surface before movement research launches."""
    payload = build_movement_preflight_review(request, preflight, prompt_package, run_id=run_id)
    actions = _build_review_actions(payload)
    await cl.Message(content=payload["content"]).send()

    async def _ask_next_action():
        response = await cl.AskActionMessage(
            content="Choose the next step for this people movement run.",
            actions=actions,
            timeout=900,
            raise_on_timeout=False,
        ).send()
        logger.info(
            "Movement review selection run_id=%s action=%s",
            run_id,
            str((response or {}).get("name") or "timeout"),
        )
        return response

    await run_review_action_loop(
        ask_next_action=_ask_next_action,
        view_action_name=ACTION_VIEW_MOVEMENT_PROMPT,
        edit_action_name=ACTION_EDIT_MOVEMENT_PROMPT,
        adjust_action_name=ACTION_ADJUST_MOVEMENT,
        run_action_name=ACTION_RUN_MOVEMENT_RESEARCH,
        on_view_prompt=lambda: _show_generated_prompt_message(
            title="Generated People Movement Prompt",
            prompt_text=prompt_package.user_prompt,
        ),
        on_edit_prompt=lambda: _enter_prompt_edit_mode(
            mode=MOVEMENT_MODE,
            run_id=run_id,
            prompt_text=prompt_package.user_prompt,
            edit_pending_key=MOVEMENT_EDIT_PENDING_SESSION_KEY,
            descriptor="people movement",
        ),
        on_adjust=show_movement_form,
        on_run=lambda: _run_movement_research_flow(run_id),
        on_timeout=lambda: cl.Message(
            "People movement review timed out. Re-open the movement form if you want to continue."
        ).send(),
        on_unknown_action=lambda action_name: cl.Message(
            f"Unknown people movement review action: {action_name or 'missing action name'}."
        ).send(),
    )


async def present_transition_brief(brief, *, run_id: str):
    """Render the compact transition brief surface."""
    payload = build_transition_brief_payload(brief, run_id=run_id)
    actions = [
        cl.Action(name=action["name"], label=action["label"], payload=action.get("payload", {}))
        for action in payload.get("actions", [])
    ]
    await cl.Message(content=payload["content"], actions=actions).send()


async def present_movement_brief(result, *, run_id: str) -> None:
    """Render the compact movement brief surface."""
    payload = build_movement_brief_payload(
        result.movement_brief,
        request=result.request,
        preflight=result.preflight,
        person_details_by_name=build_movement_person_details_by_name(result),
        row_action_context_by_person_name=build_movement_row_action_context_by_person_name(result),
    )
    brief_element = cl.CustomElement(
        name="MovementBrief",
        display="inline",
        size="large",
        props=payload,
    )
    await cl.Message(
        content="",
        elements=[brief_element],
    ).send()

    actions = [
        cl.Action(
            name=ACTION_START_NEW_MOVEMENT_SCAN,
            label="Start New Scan",
            payload={"mode": "movement"},
        )
    ] + [
        cl.Action(name=item["name"], label=item["label"], payload=item.get("payload", {}))
        for item in build_movement_artifact_actions(run_id=run_id)
    ]
    await cl.Message(
        content="Open the supporting movement artifacts or launch another movement scan:",
        actions=actions,
    ).send()


async def generate_research_prompt(params_dict: dict):
    """Generate and display the research prompt for user to copy/paste."""
    try:
        # Create ResearchParameters
        params = ResearchParameters(
            sector=params_dict.get("sector", DEFAULT_INDUSTRY),
            company=params_dict.get("company", ""),
            signals=params_dict.get("signals", ""),
            service_lines=params_dict.get("service_lines", ""),
            geography=params_dict.get("geography", ""),
            min_value=params_dict.get("min_value", ""),
            time_window=params_dict.get("time_window", ""),
            other_context=params_dict.get("other_context", "")
        )
        
        # Get prompt generator and analyst agent
        analyst_agent = cl.user_session.get("analyst_agent")
        if not analyst_agent:
            await cl.Message("❌ Error: Analyst agent not initialized. Please refresh.").send()
            return
        
        prompt_gen = get_prompt_generator()
        await prompt_gen.ensure_kernel_ready(analyst_agent)
        
        # Generate the prompt
        await cl.Message("⏳ Generating research prompt...").send()
        generated_prompt = await prompt_gen.generate(params)
        
        # Show generated prompt for user to copy and paste
        await cl.Message(
            f"""✅ **Generated Research Prompt:**

```
{generated_prompt}
```

**Copy** this prompt, **paste** it in the chat input below, edit if needed, and **press Enter** to start the research."""
        ).send()
        
        logger.info(f"Generated prompt for sector={params.sector}")
        
    except Exception as e:
        logger.exception(f"Error generating prompt: {e}")
        await cl.Message(f"❌ Error generating prompt: {str(e)}").send()


def _build_review_actions(payload: Dict[str, Any]) -> List[cl.Action]:
    actions = [
        cl.Action(name=action["name"], label=action["label"], payload=action.get("payload", {}))
        for action in payload.get("actions", [])
    ]
    view_prompt_action = payload.get("view_prompt_action")
    if view_prompt_action:
        actions.append(
            cl.Action(
                name=view_prompt_action["name"],
                label=view_prompt_action["label"],
                payload=view_prompt_action.get("payload", {}),
            )
        )
    return actions


async def _show_generated_prompt_message(*, title: str, prompt_text: str) -> None:
    await cl.Message(f"**{title}**\n\n```text\n{prompt_text}\n```").send()


async def _enter_prompt_edit_mode(
    *,
    mode: str,
    run_id: str,
    prompt_text: Optional[str],
    edit_pending_key: str,
    descriptor: str,
) -> None:
    cl.user_session.set(edit_pending_key, True)
    _set_pending_edit_run_id(mode, run_id)
    if prompt_text:
        await cl.Message(
            f"Send your edited {descriptor} research prompt as the next message. "
            "That text will replace the generated prompt for the run.\n\n"
            f"Current prompt:\n```text\n{prompt_text}\n```"
        ).send()
    else:
        await cl.Message(
            f"Send your edited {descriptor} research prompt as the next message."
        ).send()


@cl.action_callback(ACTION_VIEW_PROMPT)
async def transition_view_prompt(action: cl.Action):
    run = resolve_run_context(
        cl.user_session,
        mode="transition",
        run_id=str((action.payload or {}).get("run_id") or ""),
    )
    prompt_package = _load_transition_prompt_from_run(run) if run else _load_transition_prompt_package()
    if not prompt_package:
        await cl.Message("No generated prompt is available yet.").send()
        return
    await _show_generated_prompt_message(
        title="Generated Transition Prompt",
        prompt_text=prompt_package.user_prompt,
    )


@cl.action_callback(ACTION_EDIT_PROMPT)
async def transition_edit_prompt(action: cl.Action):
    run_id = str((action.payload or {}).get("run_id") or "") or get_active_run_id(cl.user_session, TRANSITION_MODE)
    run = resolve_run_context(cl.user_session, mode="transition", run_id=run_id)
    prompt_package = _load_transition_prompt_from_run(run) if run else _load_transition_prompt_package()
    await _enter_prompt_edit_mode(
        mode=TRANSITION_MODE,
        run_id=run_id,
        prompt_text=prompt_package.user_prompt if prompt_package else None,
        edit_pending_key=TRANSITION_EDIT_PENDING_SESSION_KEY,
        descriptor="transition",
    )


@cl.action_callback(ACTION_ADJUST_TRANSITION)
async def transition_adjust_transition(action: cl.Action):
    await show_transition_form()


@cl.action_callback(ACTION_RUN_RESEARCH)
async def transition_run_research(action: cl.Action):
    run_id = str((action.payload or {}).get("run_id") or "") or get_active_run_id(cl.user_session, TRANSITION_MODE)
    await _run_transition_research_flow(run_id)


@cl.action_callback(ACTION_VIEW_MOVEMENT_PROMPT)
async def movement_view_prompt(action: cl.Action):
    run = resolve_run_context(
        cl.user_session,
        mode="movement",
        run_id=str((action.payload or {}).get("run_id") or ""),
    )
    prompt_package = _load_movement_prompt_from_run(run) if run else _load_movement_prompt_package()
    if not prompt_package:
        await cl.Message("No generated prompt is available yet.").send()
        return
    await _show_generated_prompt_message(
        title="Generated People Movement Prompt",
        prompt_text=prompt_package.user_prompt,
    )


@cl.action_callback(ACTION_EDIT_MOVEMENT_PROMPT)
async def movement_edit_prompt(action: cl.Action):
    run_id = str((action.payload or {}).get("run_id") or "") or get_active_run_id(cl.user_session, MOVEMENT_MODE)
    run = resolve_run_context(cl.user_session, mode="movement", run_id=run_id)
    prompt_package = _load_movement_prompt_from_run(run) if run else _load_movement_prompt_package()
    await _enter_prompt_edit_mode(
        mode=MOVEMENT_MODE,
        run_id=run_id,
        prompt_text=prompt_package.user_prompt if prompt_package else None,
        edit_pending_key=MOVEMENT_EDIT_PENDING_SESSION_KEY,
        descriptor="people movement",
    )


@cl.action_callback(ACTION_ADJUST_MOVEMENT)
async def movement_adjust_move(action: cl.Action):
    await show_movement_form()


@cl.action_callback(ACTION_RUN_MOVEMENT_RESEARCH)
async def movement_run_research(action: cl.Action):
    run_id = str((action.payload or {}).get("run_id") or "") or get_active_run_id(cl.user_session, MOVEMENT_MODE)
    logger.info("Movement Run Research action clicked run_id=%s payload=%s", run_id, action.payload)
    await _run_movement_research_flow(run_id)


@cl.action_callback(ACTION_VIEW_ARTIFACT)
async def transition_view_artifact(action: cl.Action):
    payload = action.payload or {}
    artifact_key = str(payload.get("artifact_key") or "").strip()
    artifact_type = str(payload.get("artifact_type") or artifact_key).strip()
    run_id = str(payload.get("run_id") or "").strip()
    mode = str(payload.get("mode") or "").strip() or cl.user_session.get(DEEP_RESEARCH_SESSION_KEY, DEFAULT_MODE)
    run = resolve_run_context(cl.user_session, mode=mode or None, run_id=run_id or None)
    artifacts: Dict[str, str] = dict((run.artifacts if run else {}) or {})
    content = str(artifacts.get(artifact_key) or "").strip()
    if not content:
        await cl.Message("That artifact is no longer available for this run.").send()
        return
    title = artifact_type.replace("_", " ").title()
    await cl.Message(f"**{title}**\n\n{content}").send()


@cl.action_callback(ACTION_START_NEW_MOVEMENT_SCAN)
async def movement_start_new_scan(action: cl.Action):
    await show_movement_form()



@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming messages with comprehensive error handling."""
    user_text = ""
    try:
        await _init_singletons()
        ctx = _get_ctx()
        router: QueryRouter = cl.user_session.get("router")
        bing_agent: BingDataExtractionAgent = cl.user_session.get("bing_agent")
        analyst_agent: AnalystAgent = cl.user_session.get("analyst_agent")
        fup: FollowUpHandler = cl.user_session.get("follow_up_handler")

        # Validate required services
        if not all([router, bing_agent, analyst_agent, fup]):
            raise RuntimeError("Required services not initialized")

        user_text = (message.content or "").strip()
        if not user_text:
            await cl.Message("Please enter a message.").send()
            return

        current_mode = cl.user_session.get(DEEP_RESEARCH_SESSION_KEY, DEFAULT_MODE)

        if current_mode == TRANSITION_MODE:
            pending_run_id = _get_pending_edit_run_id(TRANSITION_MODE)
            if pending_run_id:
                cl.user_session.set(TRANSITION_EDIT_PENDING_SESSION_KEY, False)
                _set_pending_edit_run_id(TRANSITION_MODE, None)
                run = resolve_run_context(cl.user_session, mode="transition", run_id=pending_run_id)
                prompt_package = _load_transition_prompt_from_run(run) if run else None
                preflight = _load_transition_preflight_from_run(run) if run else None
                if prompt_package and preflight and run:
                    updated_prompt = TransitionPromptPackage(
                        industry_key=prompt_package.industry_key,
                        system_prompt=prompt_package.system_prompt,
                        user_prompt=user_text,
                    )
                    update_workflow_run(
                        cl.user_session,
                        pending_run_id,
                        prompt_package=_dump_model(updated_prompt),
                        prompt_override=user_text,
                    )
                    _persist_transition_prompt_package(updated_prompt)
                    cl.user_session.set(TRANSITION_PROMPT_OVERRIDE_SESSION_KEY, user_text)
                    await cl.Message("Updated prompt captured for this transition run.").send()
                    await present_transition_preflight_review(preflight, updated_prompt, run_id=pending_run_id)
                else:
                    await cl.Message("Updated prompt captured for the next transition run.").send()
                return

            if _get_active_run(TRANSITION_MODE):
                await cl.Message(
                    "Transition mode is active. Use the review actions to run research, view the prompt, or adjust the scenario."
                ).send()
                return
            await show_transition_form()
            return

        if current_mode == MOVEMENT_MODE:
            pending_run_id = _get_pending_edit_run_id(MOVEMENT_MODE)
            if pending_run_id:
                cl.user_session.set(MOVEMENT_EDIT_PENDING_SESSION_KEY, False)
                _set_pending_edit_run_id(MOVEMENT_MODE, None)
                run = resolve_run_context(cl.user_session, mode="movement", run_id=pending_run_id)
                prompt_package = _load_movement_prompt_from_run(run) if run else None
                preflight = _load_movement_preflight_from_run(run) if run else None
                request = _load_movement_request_from_run(run) if run else None
                if prompt_package and preflight and request and run:
                    updated_prompt = MovementPromptPackage(
                        industry_key=prompt_package.industry_key,
                        system_prompt=prompt_package.system_prompt,
                        user_prompt=user_text,
                    )
                    update_workflow_run(
                        cl.user_session,
                        pending_run_id,
                        prompt_package=_dump_model(updated_prompt),
                        prompt_override=user_text,
                    )
                    _persist_movement_prompt_package(updated_prompt)
                    cl.user_session.set(MOVEMENT_PROMPT_OVERRIDE_SESSION_KEY, user_text)
                    await cl.Message("Updated prompt captured for this people movement run.").send()
                    await present_movement_preflight_review(request, preflight, updated_prompt, run_id=pending_run_id)
                else:
                    await cl.Message("Updated prompt captured for the next people movement run.").send()
                return

            if _get_active_run(MOVEMENT_MODE):
                await cl.Message(
                    "People Movement Brief mode is active. Use the review actions to run research, view the prompt, or adjust the scenario."
                ).send()
                return
            await show_movement_form()
            return

        ctx.add_message("user", user_text)

        logger.info(
            "Deep research mode check session=%s mode=%s feature_flag=%s",
            cl.user_session.get("session_id"),
            current_mode,
            AppConfig.ENABLE_DEEP_RESEARCH,
        )
        deep_mode = current_mode == "deep" and AppConfig.ENABLE_DEEP_RESEARCH

        if deep_mode:
            # Get selected industry prompt
            selected_industry = cl.user_session.get(INDUSTRY_PROMPT_SESSION_KEY, DEFAULT_INDUSTRY)
            
            logger.info(
                f"Deep Research starting: session={cl.user_session.get('session_id')}, "
                f"industry_retrieved={selected_industry}"
            )
            
            # Create a progress message that will be updated in real-time
            progress_msg = cl.Message(
                content=f"**Deep Research Started** (Industry: {selected_industry})\n\n"
                        f"Status: Initializing...\n"
                        f"Sources Found: 0"
            )
            await progress_msg.send()
            
            # Define progress callback to update the Chainlit UI in real-time
            async def progress_callback(text: str, metadata: dict):
                """Update progress message with latest research status (like demo_run.py)."""
                try:
                    citation_count = metadata.get('citation_count', 0)
                    status = metadata.get('status', 'in_progress')
                    activity_log = metadata.get('activity_log', [])
                    poll_count = metadata.get('poll_count', 0)
                    
                    # Build progress update with activity log
                    content = f"**Deep Research in Progress** (Industry: {selected_industry})\n\n"
                    content += f"**Status:** {status} | **Sources Found:** {citation_count} | **Poll:** #{poll_count}\n\n"
                    
                    # Show activity log (recent 10 activities)
                    if activity_log:
                        content += "**Research Activity:**\n```\n"
                        # Show last 10 activities to avoid message getting too long
                        recent_activities = activity_log[-10:]
                        for activity in recent_activities:
                            content += f"{activity}\n"
                        
                        if len(activity_log) > 10:
                            content += f"... and {len(activity_log) - 10} earlier activities\n"
                        content += "```\n\n"
                    
                    # Show snippet of latest findings (first 250 chars)
                    if text:
                        snippet = text[:250] + "..." if len(text) > 250 else text
                        content += f"**Latest Finding:**\n{snippet}"
                    
                    # Update the existing message
                    progress_msg.content = content
                    await progress_msg.update()
                    
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")
            
            try:
                response = await ors.run_deep_research(
                    user_text, 
                    industry=selected_industry,
                    progress_callback=progress_callback
                )
                
                # Auto-enrich with BD Analysis (Credentials + ATLAS synthesis)
                progress_msg.content = f"**Deep Research Complete!** Enriching with Credentials validation..."
                await progress_msg.update()
                
                async def bd_progress_update(msg: str):
                    try:
                        progress_msg.content = f"**BD Analysis:** {msg}"
                        await progress_msg.update()
                    except:
                        pass
                
                response = await enrich_with_bd_analysis(
                    response, 
                    sector=selected_industry,
                    user_query=user_text,
                    session_params=cl.user_session.get(RESEARCH_PARAMS_SESSION_KEY, {}),
                    progress_callback=bd_progress_update
                )
                
                # Final update
                progress_msg.content = f"**Analysis Complete!** (Industry: {selected_industry})\n\nFinal Report Ready"
                await progress_msg.update()
                
                await present_enhanced_response(response)
                return
            except Exception as exc:
                logger.exception("Deep Research execution failed: %s", exc)
                await cl.Message(
                    "  Deep Research encountered an error. Falling back to the standard analysis pipeline for this request."
                ).send()

        # Check if enhanced system is enabled
        enhanced_enabled = os.getenv("ENABLE_ENHANCED_SYSTEM", "true").lower() in ("1", "true", "yes")
        
        if enhanced_enabled:
            try:
                # Enhanced system path
                logger.info("Using enhanced system for request")
                response = await enhanced_user_request_handler(
                    user_text, ctx, bing_agent, analyst_agent, 
                    progress=lambda msg: cl.Message(f" {msg}").send()
                )
                await present_enhanced_response(response)
                return
                
            except Exception as e:
                logger.warning(f"Enhanced system failed, falling back to old system: {e}")
                # Fall back to old system
                qtype, payload = router.route(user_text, ctx)
                await handle_old_system(qtype, payload, ctx, bing_agent, analyst_agent, fup, user_text)
                return
        else:
            # Old system path
            logger.info("Using old system for request")
            qtype, payload = router.route(user_text, ctx)
            await handle_old_system(qtype, payload, ctx, bing_agent, analyst_agent, fup, user_text)
            return

    except Exception as e:
        await handle_error(e, "on_message", user_text)

# --- Legacy handlers (for old system fallback) ---

async def handle_new_analysis(
    payload: Dict[str, Any],
    ctx: ConversationContext,
    bing_agent: BingDataExtractionAgent,
    analyst_agent: AnalystAgent,
    original_text: Optional[str] = None
):
    """Handle new company analysis with validation."""
    # Validate payload
    is_valid, error, company_data = validate_company_payload(payload)
    if not is_valid:
        await cl.Message(f"Error: {error}").send()
        return

    company = company_data["name"]
    ticker = company_data.get("ticker")
    ctx.set_company(company, ticker)

    await cl.Message(f" Running analysis on **{company}**").send()

    try:
        if os.getenv("ENABLE_TOOL_ORCHESTRATOR", "false").lower() in ("1", "true", "yes"):
            # Tool-centric orchestrator path
            await cl.Message(" Collecting GWBS sections (SEC, News, Procurement, Earnings, Industry)").send()
            cref = CompanyRef(name=company, ticker=ticker)
            briefing = await ors.full_company_analysis(cref, bing_agent=bing_agent, analyst_agent=analyst_agent)

            # Save context
            blob = AnalysisBlob(
                company_name=briefing.company.name,
                ticker=briefing.company.ticker,
                gwbs_sections={k: {"summary": v} for k, v in (briefing.sections or {}).items()},
                analyst_summary=briefing.summary,
                analyst_events=[e.dict() for e in briefing.events],
            )
            ctx.set_analysis(blob)

            # Present results
            await present_briefing_results(briefing)

            # Optional: if original_text includes competitor request, run competitor GWBS too
            if original_text and "competitor" in original_text.lower():
                await cl.Message(" Also searching for competitor information").send()
                try:
                    comp_result = await ors.competitor_analysis(cref, bing_agent=bing_agent)
                    await cl.Message(f"**Competitor Analysis:**\n{comp_result.summary}").send()
                except Exception as comp_err:
                    logger.warning(f"Competitor analysis failed: {comp_err}")

        else:
            # Legacy path
            await cl.Message(" Running legacy analysis").send()
            # ... existing legacy code ...

    except Exception as e:
        await handle_error(e, "handle_new_analysis", f"Analysis failed for {company}")

async def handle_follow_up(ctx: ConversationContext, fup: FollowUpHandler, user_text: str):
    """Handle follow-up questions."""
    try:
        await cl.Message(" Searching for additional information").send()
        answer, citations = await fup.handle_follow_up(user_text, ctx)
        
        if answer:
            await cl.Message(answer).send()
            if citations:
                citation_text = "**Sources:**\n" + "\n".join([f" [{c.title}]({c.url})" for c in citations])
                await cl.Message(citation_text).send()
        else:
            await cl.Message("I couldn't find specific information about that. Try asking more specifically.").send()
            
    except Exception as e:
        await handle_error(e, "handle_follow_up", "Follow-up search failed")

async def handle_company_comparison(payload: Dict[str, Any], ctx: ConversationContext, 
                                  bing_agent: BingDataExtractionAgent, analyst_agent: AnalystAgent):
    """Handle company comparison requests."""
    try:
        companies = payload.get("companies", [])
        if not companies or len(companies) < 2:
            await cl.Message("Please specify at least two companies to compare.").send()
            return
        
        await cl.Message(f" Comparing **{companies[0]}** and **{companies[1]}**").send()
        
        # Run analysis for both companies
        for company in companies:
            cref = CompanyRef(name=company)
            briefing = await ors.full_company_analysis(cref, bing_agent=bing_agent, analyst_agent=analyst_agent)
            await present_briefing_results(briefing)
            
    except Exception as e:
        await handle_error(e, "handle_company_comparison", "Company comparison failed")

async def handle_general_research(payload: Dict[str, Any], bing_agent: BingDataExtractionAgent):
    """Handle general research requests."""
    try:
        prompt = payload.get("prompt", "")
        if not prompt:
            await cl.Message("Please specify what you'd like me to research.").send()
            return
        
        await cl.Message(" Researching your topic").send()
        summary, citations = await ors.general_research(prompt, bing_agent=bing_agent)
        
        if summary:
            await cl.Message(summary).send()
            if citations:
                citation_text = "**Sources:**\n" + "\n".join([f" [{c.title}]({c.url})" for c in citations])
                await cl.Message(citation_text).send()
        else:
            await cl.Message("I couldn't find information on that topic. Please try rephrasing your question.").send()
            
    except Exception as e:
        await handle_error(e, "handle_general_research", "General research failed")

async def present_briefing_results(briefing):
    """Present briefing results to the user."""
    try:
        # Present summary
        if briefing.summary:
            await cl.Message(f"**Analysis Summary:**\n{briefing.summary}").send()
        
        # Present events
        if briefing.events:
            await cl.Message("**Key Events:**").send()
            for event in briefing.events:
                title = event.get("title", "Event")
                insights = event.get("insights", {})
                
                event_text = f"**{title}**"
                if insights:
                    what = insights.get("what_happened", "")
                    why = insights.get("why_it_matters", "")
                    if what:
                        event_text += f"\n\n**What happened**: {what}"
                    if why:
                        event_text += f"\n\n**Why it matters**: {why}"
                
                await cl.Message(event_text).send()
        
        # Present sections
        if briefing.sections:
            await cl.Message("**Research Sections:**").send()
            for section_name, section_summary in briefing.sections.items():
                section_title = section_name.replace("_", " ").title()
                await cl.Message(f"**{section_title}:**\n{section_summary}").send()
                
    except Exception as e:
        logger.error(f"Error presenting briefing results: {e}")
        await cl.Message("  Analysis completed successfully.").send()
