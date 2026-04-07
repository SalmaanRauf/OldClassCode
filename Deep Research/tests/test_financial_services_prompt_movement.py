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


def test_financial_services_prompt_requires_high_value_movement_inventory():
    content = _read_prompt()
    lowered = content.lower()

    assert "top 8-10 commercially relevant executive movers" in lowered
    assert "top 8-10 commercially relevant buyer movers" in lowered
    assert "Executive Movement Inventory" in content
    assert "Buyer Movement Inventory" in content
    assert "do not stop after finding only a few examples" in lowered
    assert "prioritize active appointments, external hires, promotions, and real scope expansions over departures" in lowered
    assert "prefer a balanced inventory over an executive-heavy list" in lowered
