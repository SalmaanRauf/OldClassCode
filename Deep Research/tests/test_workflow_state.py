"""
Tests for run-scoped workflow session state.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.workflow_state import (  # noqa: E402
    ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY,
    RUNS_BY_ID_SESSION_KEY,
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


class FakeSession(dict):
    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return super().get(key, default)


def _context(*, mode: str = "movement", run_id: str = "run-123") -> WorkflowRunContext:
    return WorkflowRunContext(
        run_id=run_id,
        mode=mode,
        request={"person_name": "Jennifer Brady"},
        preflight={"matched": True},
        prompt_package={"user_prompt": "Generated prompt"},
        status=WorkflowRunStatus.REVIEW_READY,
    )


def test_create_workflow_run_defaults_status_and_created_at():
    run = create_workflow_run(
        mode="transition",
        request={"person_name": "Jennifer Brady"},
    )

    assert run.mode == "transition"
    assert run.status == WorkflowRunStatus.PREFLIGHT_PENDING
    assert run.run_id
    assert run.created_at
    assert run.progress == []
    assert run.artifacts == {}


def test_create_workflow_run_supports_proconnect_deep_research_mode():
    run = create_workflow_run(
        mode="proconnect_deep_research",
        request={"account_name": "BAE Systems"},
    )

    assert run.mode == "proconnect_deep_research"
    assert run.request["account_name"] == "BAE Systems"


def test_persist_and_load_workflow_run_round_trips():
    session = FakeSession()
    context = _context()

    persist_workflow_run(session, context)
    loaded = load_workflow_run(session, context.run_id)

    assert loaded == context
    assert context.run_id in session[RUNS_BY_ID_SESSION_KEY]


def test_update_workflow_run_replaces_only_target_run():
    session = FakeSession()
    first = _context(run_id="run-1")
    second = _context(run_id="run-2")
    persist_workflow_run(session, first)
    persist_workflow_run(session, second)

    updated = update_workflow_run(
        session,
        "run-2",
        status=WorkflowRunStatus.RUNNING,
        prompt_override="Edited prompt",
    )

    assert updated is not None
    assert updated.status == WorkflowRunStatus.RUNNING
    assert updated.prompt_override == "Edited prompt"
    assert load_workflow_run(session, "run-1") == first


def test_active_run_id_is_scoped_by_mode():
    session = FakeSession()
    set_active_run_id(session, "movement", "run-m")
    set_active_run_id(session, "transition", "run-t")

    assert get_active_run_id(session, "movement") == "run-m"
    assert get_active_run_id(session, "transition") == "run-t"
    assert session[ACTIVE_RUN_IDS_BY_MODE_SESSION_KEY] == {
        "movement": "run-m",
        "transition": "run-t",
    }


def test_resolve_run_context_prefers_explicit_run_id_over_active_mode():
    session = FakeSession()
    movement = _context(mode="movement", run_id="run-m")
    transition = _context(mode="transition", run_id="run-t")
    persist_workflow_run(session, movement)
    persist_workflow_run(session, transition)
    set_active_run_id(session, "movement", "run-m")
    set_active_run_id(session, "transition", "run-t")

    resolved = resolve_run_context(session, mode="movement", run_id="run-t")

    assert resolved == transition


def test_resolve_run_context_falls_back_to_active_mode():
    session = FakeSession()
    context = _context(mode="movement", run_id="run-m")
    persist_workflow_run(session, context)
    set_active_run_id(session, "movement", "run-m")

    resolved = resolve_run_context(session, mode="movement")

    assert resolved == context
