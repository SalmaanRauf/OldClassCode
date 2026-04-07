"""
Utilities for safely rendering Chainlit custom-element surfaces.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def ensure_chainlit_files_directory(files_directory: Any) -> Path:
    """Ensure the Chainlit files root exists before elements are persisted."""
    path = Path(files_directory)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_movement_brief_fallback_markdown(payload: Dict[str, Any]) -> str:
    """Build a readable markdown fallback when the custom brief surface cannot render."""
    title = _text(payload.get("title")) or "People Movement Brief"
    subtitle = _text(payload.get("subtitle"))
    move_summary = payload.get("move_summary") or {}
    signal_summary = payload.get("signal_summary") or []
    opportunity_context = payload.get("destination_account_opportunity_context") or []
    rows = payload.get("movement_rows") or []
    where_to_act = payload.get("where_to_act") or []
    takeaway = _text(payload.get("takeaway"))

    lines: List[str] = [f"**{title}**"]
    if subtitle:
        lines.extend(["", subtitle])

    summary_text = _text(move_summary.get("summary_text"))
    if summary_text:
        lines.extend(["", "**Move Summary**", summary_text])

    if signal_summary:
        lines.extend(["", "**Signal Summary**"])
        lines.extend(f"- {_text(item)}" for item in signal_summary[:4] if _text(item))

    if opportunity_context:
        lines.extend(["", "**Destination Account Opportunity Context**"])
        for item in opportunity_context[:3]:
            title_text = _text(item.get("title"))
            rationale = _text(item.get("rationale"))
            confidence = _text(item.get("confidence")) or "Medium"
            if title_text:
                detail = f"{title_text} ({confidence})"
                if rationale:
                    detail = f"{detail}: {rationale}"
                lines.append(f"- {detail}")

    if rows:
        lines.extend(["", "**Who Has Moved - And Where We Have Leverage**"])
        for row in rows[:8]:
            person = _text(row.get("person_name")) or "Unknown"
            role = _text(row.get("new_role")) or _text(row.get("movement_type")) or "Role change"
            signal = _text(row.get("signal")) or "EXEC"
            posture = _text(row.get("action_posture")) or "Monitor"
            leverage_bits = []
            if row.get("known"):
                leverage_bits.append("known")
            if row.get("worked_with"):
                leverage_bits.append("worked with")
            projects = row.get("project_count") or 0
            wins = row.get("win_count") or 0
            if isinstance(projects, int) and projects > 0:
                leverage_bits.append(f"{projects} current projects")
            if isinstance(wins, int) and wins > 0:
                leverage_bits.append(f"{wins} wins")
            leverage_text = f" | leverage: {', '.join(leverage_bits)}" if leverage_bits else ""
            lines.append(f"- [{signal}] {person}: {role} | {posture}{leverage_text}")

    if where_to_act:
        lines.extend(["", "**Where to Act**"])
        for index, action in enumerate(where_to_act[:3], start=1):
            person = _text(action.get("person_name")) or "Unknown"
            play = _text(action.get("likely_play"))
            why_now = _text(action.get("why_now"))
            lines.append(f"{index}. {person}")
            if play:
                lines.append(f"   {play}")
            if why_now:
                lines.append(f"   {why_now}")

    if takeaway:
        lines.extend(["", "**Takeaway**", takeaway])

    return "\n".join(lines).strip()


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
