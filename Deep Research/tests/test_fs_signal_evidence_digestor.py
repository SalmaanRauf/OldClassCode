"""
Unit tests for financial-services signal evidence digestor.
"""
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import BDTrigger
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor


class _FakeChat:
    def __init__(self, payload: str):
        self._payload = payload

    async def get_chat_message_content(self, **kwargs):  # pragma: no cover - exercised via digest
        return self._payload


class _FakeKernel:
    def __init__(self, payload: str):
        self._payload = payload

    def get_service(self, name: str):
        return _FakeChat(self._payload)


def _build_trigger() -> BDTrigger:
    return BDTrigger(
        sector="Financial Services",
        signals=["FS.EXEC.TRANSITION", "FS.REGULATORY.DEADLINE"],
        company_focus="Capital One",
    )


async def _digest_with_payload(payload: dict, markdown: str):
    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )
    return await digestor.digest(
        trigger=_build_trigger(),
        deep_research_markdown=markdown,
        requested_signal_codes=["FS.EXEC.TRANSITION", "FS.REGULATORY.DEADLINE"],
    )


def test_digest_parses_signal_evidence_and_rejects_unlisted_urls():
    markdown = """
# Sources
- https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "Executive Transition",
                "status": "Confirmed",
                "evidence_quote": "Capital One appointed a Business Chief Risk Officer for its new Global Payments Network.",
                "source_url": "https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro",
                "source_title": "FinTech Magazine",
                "analysis": "Named risk leadership is aligned with strategic network expansion.",
            },
            {
                "signal_code": "FS.REGULATORY.DEADLINE",
                "signal_label": "Regulatory Deadline",
                "status": "Confirmed",
                "evidence_quote": "Submission date has been extended to July 1, 2026.",
                "source_url": "https://example.com/not-allowed-source",
                "source_title": "Unknown Source",
                "analysis": "Deadline cadence remains active.",
            },
        ]
    }

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(_digest_with_payload(payload, markdown))

    assert diagnostics["status"] == "Succeeded"
    assert diagnostics["parse_outcome"] == "json_parsed_with_signal_evidence"
    assert len(signal_evidence) == 2

    exec_signal = next(item for item in signal_evidence if item.signal_code == "FS.EXEC.TRANSITION")
    reg_signal = next(item for item in signal_evidence if item.signal_code == "FS.REGULATORY.DEADLINE")

    assert exec_signal.status == "Confirmed"
    assert exec_signal.source_url.startswith("https://fintechmagazine.com/")
    assert reg_signal.status == "Rejected"


def test_digest_adds_missing_requested_signals_as_insufficient():
    markdown = """
# Sources
- https://www.fdic.gov/resolutions/2025-capital-one-interim-resolution-plan-public-section.pdf
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.REGULATORY.DEADLINE",
                "signal_label": "Regulatory Deadline",
                "status": "Confirmed",
                "evidence_quote": "submission date ... extended to on or prior to July 1, 2026",
                "source_url": "https://www.fdic.gov/resolutions/2025-capital-one-interim-resolution-plan-public-section.pdf",
                "source_title": "FDIC Public Section",
                "analysis": "Interim submission requirement and final date are explicit.",
            }
        ]
    }

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(_digest_with_payload(payload, markdown))

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 2
    missing = next(item for item in signal_evidence if item.signal_code == "FS.EXEC.TRANSITION")
    assert missing.status == "Insufficient"
