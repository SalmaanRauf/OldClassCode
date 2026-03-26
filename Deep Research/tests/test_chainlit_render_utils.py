import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chainlit_render_utils import (
    build_movement_brief_fallback_markdown,
    ensure_chainlit_files_directory,
)


def test_ensure_chainlit_files_directory_creates_missing_parents(tmp_path):
    target = tmp_path / "missing-parent" / ".files"

    created = ensure_chainlit_files_directory(target)

    assert created == Path(target)
    assert created.is_dir()


def test_build_movement_brief_fallback_markdown_includes_core_sections():
    payload = {
        "title": "People Movement Brief",
        "subtitle": "Executive and buyer movement with leverage, proof, and next actions.",
        "move_summary": {
            "summary_text": "Jennifer Brady moved from Capital One to Fannie Mae as Chief Information Officer."
        },
        "signal_summary": [
            "Senior executive transitions confirmed.",
            "Model governance remains in focus.",
        ],
        "destination_account_opportunity_context": [
            {
                "title": "Fannie Mae - ESG Control Design Testing",
                "confidence": "High",
                "rationale": "Destination account signal currently sits at stage: Opportunity Qualified.",
            }
        ],
        "movement_rows": [
            {
                "signal": "EXEC",
                "person_name": "Jennifer Brady",
                "new_role": "Chief Information Officer",
                "action_posture": "Expansion Opportunity",
                "known": True,
                "worked_with": True,
                "project_count": 2,
                "win_count": 1,
            }
        ],
        "where_to_act": [
            {
                "person_name": "Jennifer Brady",
                "likely_play": "Executive support around chief information officer.",
                "why_now": "Warm path exists and prior work is confirmed.",
            }
        ],
        "takeaway": "Lead with the named move and destination-account opportunity context.",
    }

    markdown = build_movement_brief_fallback_markdown(payload)

    assert "**People Movement Brief**" in markdown
    assert "**Move Summary**" in markdown
    assert "Jennifer Brady moved from Capital One to Fannie Mae" in markdown
    assert "**Signal Summary**" in markdown
    assert "**Destination Account Opportunity Context**" in markdown
    assert "**Who Has Moved - And Where We Have Leverage**" in markdown
    assert "**Where to Act**" in markdown
    assert "**Takeaway**" in markdown
