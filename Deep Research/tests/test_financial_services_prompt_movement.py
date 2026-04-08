"""
Tests for the Financial Services Deep Research prompt movement guidance.
"""
from pathlib import Path


PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "industries"
    / "financial_services.md"
)


def _read_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def test_financial_services_prompt_includes_buyer_movement_guidance():
    content = _read_prompt()

    assert "### Buyer Movement" in content
    assert "promotions, role expansions, and inbound/outbound buyer moves" in content
    assert "LinkedIn/self-disclosure" in content


def test_financial_services_prompt_keeps_broad_signal_coverage_but_biases_to_movement_context():
    content = _read_prompt()
    lowered = content.lower()

    assert "Conduct comprehensive research on Financial Services opportunities." in content
    assert "executive movement and buyer movement are the primary deliverables" in lowered
    assert "other account signals are secondary" in lowered


def test_financial_services_prompt_requires_recall_first_movement_inventory():
    content = _read_prompt()
    lowered = content.lower()

    assert "movement-led account brief" in lowered
    assert "primary deliverables are executive movement and buyer movement" in lowered
    assert "secondary deliverable is a concise set of other account signals" in lowered
    assert "Executive Movement Inventory" in content
    assert "Buyer Movement Inventory" in content
    assert "do not stop after finding only a few examples" in lowered
    assert "roughly 15-18 total movers" in lowered
    assert "coverage checklist across major executive lanes" in lowered
    assert "buyer-center coverage checklist" in lowered
    assert "do not move on unless you have found enough movers" in lowered
    assert "never include companies, partnerships, products, programs, or transactions as movers" in lowered
