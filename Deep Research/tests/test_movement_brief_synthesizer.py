"""
Tests for bounded movement brief synthesis.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.movement_brief_synthesizer import (  # noqa: E402
    MovementBriefSynthesizer,
    MovementBriefSynthesisResult,
)


def test_coerce_result_treats_string_signal_summary_as_single_bullet():
    synthesizer = MovementBriefSynthesizer()

    result = synthesizer._coerce_result(  # noqa: SLF001
        {
            "move_summary": "Fannie Mae is in active transition.",
            "signal_summary": "Executive and buyer movement accelerated in the last 180 days.",
            "takeaway": "Lead with the strongest sourced movers.",
        }
    )

    assert result == MovementBriefSynthesisResult(
        move_summary="Fannie Mae is in active transition.",
        signal_summary=["Executive and buyer movement accelerated in the last 180 days."],
        takeaway="Lead with the strongest sourced movers.",
        action_narratives=[],
    )


def test_compact_text_removes_report_wrappers_and_sources_block():
    text = (
        "Final Report: # Fannie Mae Signals\\n\\n"
        "**Overview:** Pressure is building across governance and leadership.\\n\\n"
        "Sources: 1. Example source"
    )

    compacted = MovementBriefSynthesizer._compact_text(text)  # noqa: SLF001

    assert compacted == "Fannie Mae Signals Overview: Pressure is building across governance and leadership."
