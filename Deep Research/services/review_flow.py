"""
Deterministic review-action routing shared by movement and transition workflows.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional


AskNextAction = Callable[[], Awaitable[Optional[Dict[str, Any]]]]
AsyncNoArgHandler = Callable[[], Awaitable[None]]
AsyncUnknownHandler = Callable[[str], Awaitable[None]]


async def run_review_action_loop(
    *,
    ask_next_action: AskNextAction,
    view_action_name: str,
    edit_action_name: str,
    adjust_action_name: str,
    run_action_name: str,
    on_view_prompt: AsyncNoArgHandler,
    on_edit_prompt: AsyncNoArgHandler,
    on_adjust: AsyncNoArgHandler,
    on_run: AsyncNoArgHandler,
    on_timeout: AsyncNoArgHandler,
    on_unknown_action: AsyncUnknownHandler,
) -> Optional[str]:
    """
    Drive a review loop until the user chooses a terminal action.

    `View prompt` is intentionally non-terminal so the user can return to the
    review step and choose another action without losing context.
    """

    while True:
        response = await ask_next_action()
        if response is None:
            await on_timeout()
            return None

        action_name = str(response.get("name") or "")
        if action_name == view_action_name:
            await on_view_prompt()
            continue
        if action_name == edit_action_name:
            await on_edit_prompt()
            return action_name
        if action_name == adjust_action_name:
            await on_adjust()
            return action_name
        if action_name == run_action_name:
            await on_run()
            return action_name

        await on_unknown_action(action_name)
        return action_name
