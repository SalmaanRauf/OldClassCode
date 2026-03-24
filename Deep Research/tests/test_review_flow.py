"""
Tests for deterministic preflight review action routing.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.review_flow import run_review_action_loop  # noqa: E402


@pytest.mark.asyncio
async def test_review_flow_loops_on_view_then_runs():
    responses: List[Optional[Dict[str, Any]]] = [
        {"name": "view_prompt"},
        {"name": "run"},
    ]
    calls: List[str] = []

    async def ask_next_action():
        return responses.pop(0)

    async def on_view_prompt():
        calls.append("view")

    async def on_edit_prompt():
        calls.append("edit")

    async def on_adjust():
        calls.append("adjust")

    async def on_run():
        calls.append("run")

    async def on_timeout():
        calls.append("timeout")

    async def on_unknown_action(name: str):
        calls.append(f"unknown:{name}")

    selected = await run_review_action_loop(
        ask_next_action=ask_next_action,
        view_action_name="view_prompt",
        edit_action_name="edit_prompt",
        adjust_action_name="adjust",
        run_action_name="run",
        on_view_prompt=on_view_prompt,
        on_edit_prompt=on_edit_prompt,
        on_adjust=on_adjust,
        on_run=on_run,
        on_timeout=on_timeout,
        on_unknown_action=on_unknown_action,
    )

    assert selected == "run"
    assert calls == ["view", "run"]


@pytest.mark.asyncio
async def test_review_flow_marks_edit_as_terminal():
    calls: List[str] = []

    async def ask_next_action():
        return {"name": "edit_prompt"}

    async def on_view_prompt():
        calls.append("view")

    async def on_edit_prompt():
        calls.append("edit")

    async def on_adjust():
        calls.append("adjust")

    async def on_run():
        calls.append("run")

    async def on_timeout():
        calls.append("timeout")

    async def on_unknown_action(name: str):
        calls.append(f"unknown:{name}")

    selected = await run_review_action_loop(
        ask_next_action=ask_next_action,
        view_action_name="view_prompt",
        edit_action_name="edit_prompt",
        adjust_action_name="adjust",
        run_action_name="run",
        on_view_prompt=on_view_prompt,
        on_edit_prompt=on_edit_prompt,
        on_adjust=on_adjust,
        on_run=on_run,
        on_timeout=on_timeout,
        on_unknown_action=on_unknown_action,
    )

    assert selected == "edit_prompt"
    assert calls == ["edit"]


@pytest.mark.asyncio
async def test_review_flow_handles_timeout_without_running():
    calls: List[str] = []

    async def ask_next_action():
        return None

    async def on_view_prompt():
        calls.append("view")

    async def on_edit_prompt():
        calls.append("edit")

    async def on_adjust():
        calls.append("adjust")

    async def on_run():
        calls.append("run")

    async def on_timeout():
        calls.append("timeout")

    async def on_unknown_action(name: str):
        calls.append(f"unknown:{name}")

    selected = await run_review_action_loop(
        ask_next_action=ask_next_action,
        view_action_name="view_prompt",
        edit_action_name="edit_prompt",
        adjust_action_name="adjust",
        run_action_name="run",
        on_view_prompt=on_view_prompt,
        on_edit_prompt=on_edit_prompt,
        on_adjust=on_adjust,
        on_run=on_run,
        on_timeout=on_timeout,
        on_unknown_action=on_unknown_action,
    )

    assert selected is None
    assert calls == ["timeout"]


@pytest.mark.asyncio
async def test_review_flow_reports_unknown_action():
    calls: List[str] = []

    async def ask_next_action():
        return {"name": "something_else"}

    async def on_view_prompt():
        calls.append("view")

    async def on_edit_prompt():
        calls.append("edit")

    async def on_adjust():
        calls.append("adjust")

    async def on_run():
        calls.append("run")

    async def on_timeout():
        calls.append("timeout")

    async def on_unknown_action(name: str):
        calls.append(f"unknown:{name}")

    selected = await run_review_action_loop(
        ask_next_action=ask_next_action,
        view_action_name="view_prompt",
        edit_action_name="edit_prompt",
        adjust_action_name="adjust",
        run_action_name="run",
        on_view_prompt=on_view_prompt,
        on_edit_prompt=on_edit_prompt,
        on_adjust=on_adjust,
        on_run=on_run,
        on_timeout=on_timeout,
        on_unknown_action=on_unknown_action,
    )

    assert selected == "something_else"
    assert calls == ["unknown:something_else"]
