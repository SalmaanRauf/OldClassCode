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

    assert "Conduct comprehensive research on Financial Services opportunities." in content
    assert "final signal summary concise and oriented to why the people movement matters" in content
    assert "bias coverage toward signals that explain why the movement matters now" in content


def test_financial_services_prompt_requires_recall_first_movement_inventory():
    content = _read_prompt()
    lowered = content.lower()

    assert "broad inventory of materially supported executive movers" in lowered
    assert "broad inventory of materially supported buyer movers" in lowered
    assert "Executive Movement Inventory" in content
    assert "Buyer Movement Inventory" in content
    assert "do not stop after finding only a few examples" in lowered
    assert "roughly 15-18 total movers" in lowered
    assert "general counsel, deputy general counsel, corporate secretary" in lowered
    assert "chief operating officer" in lowered
    assert "co-coo" in lowered
    assert "chief control office" in lowered
    assert "enterprise operations leaders" in lowered
    assert "legal name and common alias" in lowered
    assert "coverage checklist across major executive lanes" in lowered
    assert "buyer-center coverage checklist" in lowered
    assert "prefer recall over conservative pruning" in lowered
    assert "medium-confidence movers with explicit role-and-employer support" in lowered
    assert "downstream workflow will rank later" in lowered
    assert "do not compress multiple movers into prose" in lowered
    assert "do not move on unless you have found enough movers" in lowered
