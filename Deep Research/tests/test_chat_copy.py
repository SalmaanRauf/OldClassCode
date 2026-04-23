"""
Tests for Chainlit shell copy helpers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chat_copy import (  # noqa: E402
    build_company_intelligence_welcome_message,
    build_mode_picker_message,
    build_proconnect_deep_research_active_message,
    build_movement_mode_active_message,
)


def test_build_company_intelligence_welcome_message_is_compact() -> None:
    content = build_company_intelligence_welcome_message()

    assert "Company Intelligence" in content
    assert "Ask about a company or run a guided workflow below." in content
    assert "New capabilities" not in content
    assert "Type a company" not in content


def test_build_mode_picker_message_is_short() -> None:
    assert build_mode_picker_message() == "**Step 1:** Select research mode:"


def test_build_movement_mode_active_message_explains_workflow() -> None:
    content = build_movement_mode_active_message()

    assert "Validate a named move" in content
    assert "broader executive and buyer movement" in content
    assert "surface leverage and next actions" in content


def test_build_proconnect_deep_research_active_message_explains_workflow() -> None:
    content = build_proconnect_deep_research_active_message()

    assert "Type one target account name" in content
    assert "ProConnect facts" in content
    assert "public Deep Research" in content
