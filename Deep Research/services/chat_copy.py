"""
Reusable user-facing copy for the Chainlit shell.
"""
from __future__ import annotations


def build_company_intelligence_welcome_message() -> str:
    """Return the lightweight default welcome message shown on chat start."""
    return (
        "**Company Intelligence**\n\n"
        "Ask about a company or run a guided workflow below."
    )


def build_mode_picker_message() -> str:
    """Return the mode-picker prompt shown below the welcome message."""
    return "**Step 1:** Select research mode:"


def build_movement_mode_active_message() -> str:
    """Return the helper copy shown when movement mode is already active."""
    return (
        "People Movement Brief mode is active. Validate a named move, research broader "
        "executive and buyer movement, then surface leverage and next actions."
    )


def build_proconnect_deep_research_active_message() -> str:
    """Return the helper copy shown when the account-brief mode is already active."""
    return (
        "ProConnect + Deep Research mode is active. Type one target account name to "
        "collect ProConnect facts, run public Deep Research, and synthesize a short brief."
    )
