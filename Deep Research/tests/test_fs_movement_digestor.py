"""
Tests for the financial-services movement digestor.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import BDTrigger  # noqa: E402
from services.fs_movement_digestor import FSMovementDigestor  # noqa: E402


class _FakeResult:
    def __init__(self, text: str):
        self._text = text

    def __str__(self) -> str:
        return self._text


class _FakeChat:
    def __init__(self, payload: dict):
        self._payload = payload

    async def get_chat_message_content(self, **kwargs):
        return _FakeResult(json.dumps(self._payload))


class _FakeKernel:
    def __init__(self, payload: dict):
        self._payload = payload

    def get_service(self, name: str):
        assert name == "atlas"
        return _FakeChat(self._payload)


def _trigger() -> BDTrigger:
    return BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"],
        company_focus="Capital One",
        user_prompt_context="Find executive and buyer movement at Capital One.",
    )


@pytest.mark.asyncio
async def test_digest_parses_exec_and_buyer_rows_from_atlas_payload():
    digestor = FSMovementDigestor(kernel=_FakeKernel({
        "movement_records": [
            {
                "person_name": "Sarah Chen",
                "target_company": "Capital One",
                "previous_role": "Director, Model Risk",
                "new_role": "VP, Model Risk",
                "movement_type": "Promoted",
                "category": "BUYER",
                "company_context": "internal",
                "evidence_quote": "Sarah Chen was promoted to VP, Model Risk.",
                "source_url": "https://example.com/sarah-chen",
                "source_title": "Capital One leadership update",
            },
            {
                "person_name": "Jane Doe",
                "target_company": "Capital One",
                "previous_role": "Chief Risk Officer",
                "new_role": "Board Member",
                "movement_type": "Joined",
                "category": "EXEC",
                "company_context": "board_integration",
                "evidence_quote": "Jane Doe joined the board.",
                "source_url": "https://example.com/jane-doe",
                "source_title": "Capital One board update",
            },
        ]
    }))

    rows, diagnostics = await digestor.digest(
        trigger=_trigger(),
        deep_research_markdown="Movement notes here.",
    )

    assert diagnostics["status"] == "Succeeded"
    assert [row.category for row in rows] == ["BUYER", "EXEC"]


@pytest.mark.asyncio
async def test_digest_preserves_source_quote_and_url():
    digestor = FSMovementDigestor(kernel=_FakeKernel({
        "movement_records": [
            {
                "person_name": "Sarah Chen",
                "target_company": "Capital One",
                "previous_role": "Director, Model Risk",
                "new_role": "VP, Model Risk",
                "movement_type": "Promoted",
                "category": "BUYER",
                "company_context": "internal",
                "evidence_quote": "Sarah Chen was promoted to VP, Model Risk.",
                "source_url": "https://example.com/sarah-chen",
                "source_title": "Capital One leadership update",
            }
        ]
    }))

    rows, _ = await digestor.digest(trigger=_trigger(), deep_research_markdown="Movement notes here.")

    assert rows[0].evidence.evidence_quote == "Sarah Chen was promoted to VP, Model Risk."
    assert rows[0].evidence.source_url == "https://example.com/sarah-chen"


@pytest.mark.asyncio
async def test_digest_keeps_lower_formality_buyer_source_when_valid():
    digestor = FSMovementDigestor(kernel=_FakeKernel({
        "movement_records": [
            {
                "person_name": "Lisa Grant",
                "target_company": "Capital One",
                "previous_role": "Data Platform Lead",
                "new_role": "Head of Data Programs",
                "movement_type": "Promoted",
                "category": "BUYER",
                "company_context": "internal",
                "evidence_quote": "Thrilled to step into my new Head of Data Programs role.",
                "source_url": "https://www.linkedin.com/posts/lisa-grant-role-update",
                "source_title": "LinkedIn self-disclosure",
                "confidence_label": "Low",
            }
        ]
    }))

    rows, _ = await digestor.digest(trigger=_trigger(), deep_research_markdown="Movement notes here.")

    assert len(rows) == 1
    assert rows[0].evidence.source_url.startswith("https://www.linkedin.com/")
    assert rows[0].evidence.confidence_label == "Low"


@pytest.mark.asyncio
async def test_digest_filters_peer_company_movement_not_tied_to_target_company():
    digestor = FSMovementDigestor(kernel=_FakeKernel({
        "movement_records": [
            {
                "person_name": "Peer Exec",
                "target_company": "Discover",
                "previous_role": "CFO",
                "new_role": "Board Member",
                "movement_type": "Joined",
                "category": "EXEC",
                "company_context": "peer_company",
                "evidence_quote": "Peer Exec joined the Discover board.",
                "source_url": "https://example.com/discover-board",
                "source_title": "Discover board update",
            }
        ]
    }))

    rows, diagnostics = await digestor.digest(
        trigger=_trigger(),
        deep_research_markdown="Movement notes here.",
    )

    assert rows == []
    assert diagnostics["movements_returned"] == 0


@pytest.mark.asyncio
async def test_digest_normalizes_categories_dedupes_rows_and_keeps_partial_role_rows():
    digestor = FSMovementDigestor(kernel=_FakeKernel({
        "movement_records": [
            {
                "person_name": "Thomas Klein",
                "target_company": "Federal National Mortgage Association (Fannie Mae)",
                "previous_role": "Enterprise Deputy General Counsel",
                "new_role": "Acting General Counsel",
                "movement_type": "Promotion",
                "category": "buyer",
                "company_context": "internal",
                "evidence_quote": "Thomas Klein was elevated to Acting General Counsel.",
                "source_url": "https://example.com/thomas-klein",
                "source_title": "Leadership update",
            },
            {
                "person_name": "Thomas Klein",
                "target_company": "Fannie Mae",
                "previous_role": "Enterprise Deputy General Counsel",
                "new_role": "Acting General Counsel",
                "movement_type": "Promotion",
                "category": "BUYER",
                "company_context": "internal",
                "evidence_quote": "Thomas Klein was elevated to Acting General Counsel.",
                "source_url": "https://example.com/thomas-klein",
                "source_title": "Leadership update",
            },
            {
                "person_name": "Priscilla Almodovar",
                "target_company": "Fannie Mae",
                "previous_role": "",
                "new_role": "Departed",
                "movement_type": "Departure",
                "category": "exec",
                "company_context": "leadership_change",
                "evidence_quote": "Priscilla Almodovar stepped down as CEO.",
                "source_url": "https://example.com/priscilla-almodovar",
                "source_title": "CEO transition",
            },
        ]
    }))

    rows, diagnostics = await digestor.digest(
        trigger=BDTrigger(
            sector="Financial Services",
            signals=["FS.EXEC.TRANSITION"],
            company_focus="Fannie Mae",
            user_prompt_context="Find executive and buyer movement at Fannie Mae.",
        ),
        deep_research_markdown="Movement notes here.",
        target_company_aliases=["Fannie Mae", "Federal National Mortgage Association (Fannie Mae)"],
    )

    assert diagnostics["status"] == "Succeeded"
    assert diagnostics["movements_returned"] == 2
    assert [(row.person_name, row.category) for row in rows] == [
        ("Thomas Klein", "BUYER"),
        ("Priscilla Almodovar", "EXEC"),
    ]
    assert rows[1].previous_role == ""
