"""
Run-scoped workflow session state helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass

    def Field(*args, **kwargs):  # type: ignore
        return None


WorkflowMode = Literal["movement", "transition"]


class WorkflowRunStatus(str, Enum):
    PREFLIGHT_PENDING = "preflight_pending"
    REVIEW_READY = "review_ready"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class WorkflowStage(str, Enum):
    RESOLVING_TRANSITION = "resolving_transition"
    RESOLVING_NAMED_MOVE = "resolving_named_move"
    BUILDING_RELATIONSHIP_CONTEXT = "building_relationship_context"
    GENERATING_RESEARCH_PLAN = "generating_research_plan"
    RUNNING_DEEP_RESEARCH = "running_deep_research"
    ACCOUNT_SIGNALS = "account_signals"
    EXECUTIVE_MOVEMENT = "executive_movement"
    BUYER_MOVEMENT = "buyer_movement"
    PROCONNECT_ENRICHMENT = "proconnect_enrichment"
    VALIDATING_CREDENTIALS = "validating_credentials"
    MAPPING_WARM_LEADS = "mapping_warm_leads"
    ASSEMBLING_BRIEF = "assembling_brief"


class WorkflowRunContext(BaseModel):
    run_id: str = Field(..., description="Stable run identifier")
    mode: WorkflowMode = Field(..., description="Workflow mode")
    request: Dict[str, Any] = Field(default_factory=dict, description="Serialized request model")
    preflight: Optional[Dict[str, Any]] = Field(default=None, description="Serialized reviewed preflight")
    actioning_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialized reviewed actioning context when available",
    )
    prompt_package: Optional[Dict[str, Any]] = Field(default=None, description="Serialized prompt package")
    prompt_override: Optional[str] = Field(default=None, description="Latest edited prompt override")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    progress: list[Dict[str, Any]] = Field(default_factory=list, description="Run progress events")
    artifacts: Dict[str, str] = Field(default_factory=dict, description="Run-scoped artifact store")
    status: WorkflowRunStatus = Field(default=WorkflowRunStatus.PREFLIGHT_PENDING)


RUNS_BY_ID_SESSION_KEY = "workflow_runs_by_id"
ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY = "workflow_active_run_ids"


def create_workflow_run(
    *,
    mode: WorkflowMode,
    request: Dict[str, Any],
    preflight: Optional[Dict[str, Any]] = None,
    actioning_context: Optional[Dict[str, Any]] = None,
    prompt_package: Optional[Dict[str, Any]] = None,
    prompt_override: Optional[str] = None,
    status: WorkflowRunStatus = WorkflowRunStatus.PREFLIGHT_PENDING,
) -> WorkflowRunContext:
    return WorkflowRunContext(
        run_id=f"run_{uuid4().hex[:12]}",
        mode=mode,
        request=dict(request or {}),
        preflight=dict(preflight or {}) or None,
        actioning_context=dict(actioning_context or {}) or None,
        prompt_package=dict(prompt_package or {}) or None,
        prompt_override=prompt_override,
        status=status,
    )


def persist_workflow_run(session: Any, context: WorkflowRunContext) -> Dict[str, Any]:
    runs = _load_runs(session)
    payload = _dump_model(context)
    runs[context.run_id] = payload
    session.set(RUNS_BY_ID_SESSION_KEY, runs)
    return payload


def load_workflow_run(session: Any, run_id: Optional[str]) -> Optional[WorkflowRunContext]:
    if not run_id:
        return None
    payload = _load_runs(session).get(run_id)
    if not payload:
        return None
    if isinstance(payload, WorkflowRunContext):
        return payload
    if hasattr(WorkflowRunContext, "model_validate"):
        return WorkflowRunContext.model_validate(payload)
    return WorkflowRunContext.parse_obj(payload)


def update_workflow_run(session: Any, run_id: str, **updates: Any) -> Optional[WorkflowRunContext]:
    current = load_workflow_run(session, run_id)
    if current is None:
        return None
    if hasattr(current, "model_copy"):
        updated = current.model_copy(update=updates)
    else:  # pragma: no cover
        updated = current.copy(update=updates)
    persist_workflow_run(session, updated)
    return updated


def set_active_run_id(session: Any, mode: WorkflowMode, run_id: Optional[str]) -> Dict[str, str]:
    payload = dict(session.get(ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY) or {})
    if run_id:
        payload[mode] = str(run_id)
    else:
        payload.pop(mode, None)
    session.set(ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY, payload)
    return payload


def get_active_run_id(session: Any, mode: WorkflowMode) -> Optional[str]:
    payload = dict(session.get(ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY) or {})
    run_id = payload.get(mode)
    return str(run_id) if run_id else None


def resolve_run_context(
    session: Any,
    *,
    mode: Optional[WorkflowMode] = None,
    run_id: Optional[str] = None,
) -> Optional[WorkflowRunContext]:
    if run_id:
        return load_workflow_run(session, run_id)
    if mode:
        return load_workflow_run(session, get_active_run_id(session, mode))
    return None


def _load_runs(session: Any) -> Dict[str, Dict[str, Any]]:
    payload = session.get(RUNS_BY_ID_SESSION_KEY) or {}
    return dict(payload)


def _dump_model(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value)
