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


class _SequenceChat:
    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)
        self.calls = 0

    async def get_chat_message_content(self, **kwargs):
        payload = self._payloads[self.calls]
        self.calls += 1
        return _FakeResult(json.dumps(payload))


class _SequenceKernel:
    def __init__(self, payloads: list[dict]):
        self.chat = _SequenceChat(payloads)

    def get_service(self, name: str):
        assert name == "atlas"
        return self.chat


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


@pytest.mark.asyncio
async def test_digest_unions_rows_across_general_exec_and_buyer_passes():
    kernel = _SequenceKernel([
        {
            "movement_records": [
                {
                    "person_name": "Priscilla Almodovar",
                    "target_company": "Fannie Mae",
                    "previous_role": "Chief Executive Officer",
                    "new_role": "Departed",
                    "movement_type": "Departure",
                    "category": "EXEC",
                    "company_context": "leadership_change",
                    "evidence_quote": "Priscilla Almodovar stepped down as CEO.",
                    "source_url": "https://example.com/priscilla",
                    "source_title": "CEO transition",
                }
            ]
        },
        {
            "movement_records": [
                {
                    "person_name": "Peter Akwaboah",
                    "target_company": "Federal National Mortgage Association (Fannie Mae)",
                    "previous_role": "Chief Operating Officer",
                    "new_role": "Acting Chief Executive Officer",
                    "movement_type": "Interim CEO appointment",
                    "category": "EXEC",
                    "company_context": "leadership_change",
                    "evidence_quote": "Peter Akwaboah became Acting CEO.",
                    "source_url": "https://example.com/akwaboah",
                    "source_title": "Acting CEO announcement",
                }
            ]
        },
        {
            "movement_records": [
                {
                    "person_name": "Thomas Klein",
                    "target_company": "Fannie Mae",
                    "previous_role": "Enterprise Deputy General Counsel",
                    "new_role": "Acting General Counsel",
                    "movement_type": "Promotion",
                    "category": "BUYER",
                    "company_context": "internal",
                    "evidence_quote": "Thomas Klein was elevated to Acting General Counsel.",
                    "source_url": "https://example.com/klein",
                    "source_title": "Legal leadership update",
                }
            ]
        },
    ])
    digestor = FSMovementDigestor(kernel=kernel)

    rows, diagnostics = await digestor.digest(
        trigger=BDTrigger(
            sector="Financial Services",
            signals=["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"],
            company_focus="Fannie Mae",
            user_prompt_context="Find executive and buyer movement at Fannie Mae.",
        ),
        deep_research_markdown="Movement notes here.",
        target_company_aliases=["Fannie Mae", "Federal National Mortgage Association (Fannie Mae)"],
    )

    assert [(row.person_name, row.category) for row in rows] == [
        ("Priscilla Almodovar", "EXEC"),
        ("Peter Akwaboah", "EXEC"),
        ("Thomas Klein", "BUYER"),
    ]
    assert diagnostics["movements_returned"] == 3
    assert diagnostics["pass_results"] == [
        {"focus": "general", "count": 1, "skip_reasons": {}},
        {"focus": "executive", "count": 1, "skip_reasons": {}},
        {"focus": "buyer", "count": 1, "skip_reasons": {}},
    ]


@pytest.mark.asyncio
async def test_digest_dedupes_same_person_same_source_even_if_role_text_varies():
    trigger = BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION"],
        company_focus="Fannie Mae",
        user_prompt_context="Find executive movement at Fannie Mae.",
        time_window_days=180,
    )
    digestor = FSMovementDigestor(
        kernel=_FakeKernel(
            {
                "movement_records": [
                    {
                        "person_name": "Priscilla Almodóvar",
                        "target_company": "Fannie Mae",
                        "previous_role": "CEO and President",
                        "new_role": "Stepped down",
                        "movement_type": "Departure",
                        "category": "EXEC",
                        "company_context": "internal",
                        "effective_date": "2025-10-22",
                        "evidence_quote": "Priscilla Almodóvar stepped down in October 2025.",
                        "source_url": "https://example.com/fannie-leadership",
                        "source_title": "Leadership update",
                    },
                    {
                        "person_name": "Priscilla Almodóvar",
                        "target_company": "Federal National Mortgage Association (Fannie Mae)",
                        "previous_role": "President and Chief Executive Officer",
                        "new_role": "Departed",
                        "movement_type": "CEO Departure",
                        "category": "EXEC",
                        "company_context": "internal",
                        "effective_date": "2025-10-22",
                        "evidence_quote": "Priscilla Almodóvar stepped down in October 2025.",
                        "source_url": "https://example.com/fannie-leadership",
                        "source_title": "Leadership update",
                    },
                ]
            }
        )
    )

    rows, diagnostics = await digestor.digest(
        trigger=trigger,
        deep_research_markdown="Movement notes here.",
        target_company_aliases=["Fannie Mae", "Federal National Mortgage Association (Fannie Mae)"],
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(rows) == 1
    assert rows[0].person_name == "Priscilla Almodóvar"


@pytest.mark.asyncio
async def test_digest_filters_rows_outside_requested_lookback_when_effective_date_is_known():
    trigger = BDTrigger(
        sector="Financial Services",
        signals=["FS.BUYER.MOVEMENT"],
        company_focus="Fannie Mae",
        user_prompt_context="Find buyer movement at Fannie Mae.",
        time_window_days=180,
    )
    digestor = FSMovementDigestor(
        kernel=_FakeKernel(
            {
                "movement_records": [
                    {
                        "person_name": "Cissy Yang",
                        "target_company": "Fannie Mae",
                        "previous_role": "Senior Audit Leader, Credit Suisse",
                        "new_role": "SVP & Chief Audit Executive",
                        "movement_type": "Audit Executive Appointment",
                        "category": "BUYER",
                        "company_context": "internal",
                        "effective_date": "2025-09-12",
                        "evidence_quote": "Cissy Yang was appointed on September 12, 2025.",
                        "source_url": "https://example.com/cissy-yang",
                        "source_title": "Leadership update",
                    },
                    {
                        "person_name": "Tom Klein",
                        "target_company": "Fannie Mae",
                        "previous_role": "Deputy General Counsel",
                        "new_role": "Acting General Counsel",
                        "movement_type": "Promotion/Appointment",
                        "category": "BUYER",
                        "company_context": "internal",
                        "effective_date": "2025-10-24",
                        "evidence_quote": "Tom Klein was promoted on October 24, 2025.",
                        "source_url": "https://example.com/tom-klein",
                        "source_title": "Leadership update",
                    },
                ]
            }
        )
    )

    rows, diagnostics = await digestor.digest(
        trigger=trigger,
        deep_research_markdown="Movement notes here.",
        target_company_aliases=["Fannie Mae"],
    )

    assert diagnostics["status"] == "Succeeded"
    assert [row.person_name for row in rows] == ["Tom Klein"]


@pytest.mark.asyncio
async def test_digest_defaults_missing_company_context_and_tracks_skip_reasons():
    digestor = FSMovementDigestor(
        kernel=_FakeKernel(
            {
                "movement_records": [
                    {
                        "person_name": "Thomas Klein",
                        "target_company": "Fannie Mae",
                        "previous_role": "Deputy General Counsel",
                        "new_role": "Acting General Counsel",
                        "movement_type": "Promotion/Appointment",
                        "category": "BUYER",
                        "evidence_quote": "Thomas Klein was promoted to Acting General Counsel.",
                        "source_url": "https://example.com/tom-klein",
                        "source_title": "Leadership update",
                    },
                    {
                        "person_name": "Missing Source",
                        "target_company": "Fannie Mae",
                        "previous_role": "Risk Executive",
                        "new_role": "Chief Risk Officer",
                        "movement_type": "Appointment",
                        "category": "BUYER",
                        "company_context": "internal",
                        "evidence_quote": "Missing source URL should be rejected.",
                        "source_url": "",
                    },
                ]
            }
        )
    )

    rows, diagnostics = await digestor.digest(
        trigger=BDTrigger(
            sector="Financial Services",
            signals=["FS.BUYER.MOVEMENT"],
            company_focus="Fannie Mae",
            user_prompt_context="Find buyer movement at Fannie Mae.",
        ),
        deep_research_markdown="Movement notes here.",
        target_company_aliases=["Fannie Mae"],
    )

    assert [row.person_name for row in rows] == ["Thomas Klein"]
    assert rows[0].company_context == "internal"
    assert diagnostics["skip_reasons"]["missing_source"] >= 1
