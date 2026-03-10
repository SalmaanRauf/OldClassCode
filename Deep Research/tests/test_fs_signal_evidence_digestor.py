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


def test_digest_keeps_confirmed_for_allowed_non_tier1_source():
    markdown = """
# Sources
- https://www.newsweek.com/capital-one-settlement-heres-whos-eligible-425-million-payout-2074310
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.CONSUMER.LITIGATION_SETTLEMENT",
                "signal_label": "Consumer Litigation Settlement",
                "status": "Confirmed",
                "evidence_quote": "Capital One reached a $425 million settlement.",
                "source_url": "https://www.newsweek.com/capital-one-settlement-heres-whos-eligible-425-million-payout-2074310",
                "source_title": "Newsweek",
                "analysis": "Settlement evidence is explicit.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.CONSUMER.LITIGATION_SETTLEMENT"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.CONSUMER.LITIGATION_SETTLEMENT"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"


def test_digest_recovers_exec_transition_when_appointment_language_exists():
    markdown = """
Capital One appointed Natalie Hyche Kelly as Business Chief Risk Officer for its new Global Payments Network.

# Sources
- https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No transition found.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, allowed_sources = asyncio.run(
        digestor.digest(
            trigger=_build_trigger(),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(allowed_sources) == 1
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "fintechmagazine.com" in signal_evidence[0].source_url


def test_digest_accepts_linkedin_exec_transition_source_when_allowed():
    markdown = """
I am joining Capital One as the Business Chief Risk Officer for its new Global Payments Network.

# Sources
- https://www.linkedin.com/posts/example_exec_post
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Confirmed",
                "evidence_quote": "I am joining Capital One as the Business Chief Risk Officer...",
                "source_url": "https://www.linkedin.com/posts/example_exec_post",
                "source_title": "Executive LinkedIn Post",
                "analysis": "Direct self-disclosure of role and scope.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "linkedin.com" in signal_evidence[0].source_url


def test_digest_non_exec_signal_not_forced_to_social_source():
    markdown = """
I am joining Capital One as the Business Chief Risk Officer for its new Global Payments Network.

# Sources
- https://www.linkedin.com/posts/example_exec_post
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.REGULATORY.DEADLINE",
                "signal_label": "Regulatory Deadline",
                "status": "Insufficient",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No deadline evidence provided.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.REGULATORY.DEADLINE"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.REGULATORY.DEADLINE"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].signal_code == "FS.REGULATORY.DEADLINE"
    assert signal_evidence[0].status == "Insufficient"
    assert signal_evidence[0].source_url == ""


def test_digest_recovers_exec_transition_for_regional_crro_language():
    markdown = """
I rejoined Capital One in a new role as Chief Risk & Regulatory Officer for APAC & Middle East, Global Payments Network.

# Sources
- https://www.linkedin.com/posts/example_regional_exec_post
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No transition identified.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "linkedin.com" in signal_evidence[0].source_url


def test_digest_recovers_exec_transition_for_board_appointment_language():
    markdown = """
Capital One appointed Thomas G. Maheras to serve on the Capital One Board of Directors with committee assignments following close.

# Sources
- https://www.sec.gov/Archives/edgar/data/927628/000119312525122059/d934475dex991.htm
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No transition identified.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "sec.gov" in signal_evidence[0].source_url


def test_digest_recovery_prefers_people_movement_specific_sources():
    markdown = """
Capital One appointed a Business Chief Risk Officer for its new Global Payments Network.

# Sources
- https://www.bankingdive.com/news/generic-financial-services-update/123456/
- https://www.linkedin.com/posts/example_exec_post
- https://www.sec.gov/Archives/edgar/data/927628/000119312525122059/d934475dex991.htm
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No transition identified.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert (
        "sec.gov" in signal_evidence[0].source_url
        or "linkedin.com" in signal_evidence[0].source_url
    )


def test_digest_demotes_peer_company_people_movement_without_capital_one_linkage():
    markdown = """
Citi appointed a new Chief Financial Officer to oversee enterprise finance transformation.

# Sources
- https://www.bankingdive.com/news/citi-mark-mason-cfo-step-down-march-gonzalo-luchetti-fraser-sieg-luft-habner/806137/
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Confirmed",
                "evidence_quote": "Citi appointed a new Chief Financial Officer.",
                "source_url": "https://www.bankingdive.com/news/citi-mark-mason-cfo-step-down-march-gonzalo-luchetti-fraser-sieg-luft-habner/806137/",
                "source_title": "Banking Dive",
                "analysis": "Leadership transition reported.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Insufficient"
    assert "target company scope" in signal_evidence[0].analysis.lower()


def test_digest_exec_transition_enrichment_keeps_multiple_capital_one_movements():
    markdown = """
Natalie Hyche Kelly is joining Capital One as Business Chief Risk Officer for the Global Payments Network.
Bharat Panchal rejoined in a new role as Chief Risk & Regulatory Officer for APAC & Middle East, Global Payments Network at Capital One.

# Sources
- https://fintechmagazine.com/news/people-move-natalie-hyche-kelly
- https://www.linkedin.com/posts/example_exec_post
- https://www.linkedin.com/posts/example_regional_exec_post
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "No transition identified.",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    entry = signal_evidence[0]
    assert entry.status == "Confirmed"
    assert "target-company movements observed" in (entry.analysis or "").lower()
    assert "natalie hyche kelly" in (entry.analysis or "").lower()
    assert "bharat panchal" in (entry.analysis or "").lower()
    assert "movement sources:" in (entry.analysis or "").lower()
    assert "fintechmagazine.com" in (entry.source_url or "").lower()


def test_digest_exec_transition_excludes_bing_search_wrapper_sources():
    markdown = """
Natalie Hyche Kelly is joining Capital One as Business Chief Risk Officer for the Global Payments Network.

# Sources
- https://www.bing.com/search?q=FinTech+Magazine+people+moves+capital+one
- https://fintechmagazine.com/news/people-move-natalie-hyche-kelly
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert diagnostics["discovery_source_count"] >= diagnostics["confirmation_source_count"]
    assert diagnostics["filtered_search_wrapper_count"] >= 1
    assert all("bing.com/search" not in source for source in allowed_sources)
    assert len(signal_evidence) == 1
    assert "bing.com/search" not in (signal_evidence[0].source_url or "")


def test_digest_diagnostics_split_discovery_and_confirmation_sources():
    markdown = """
# Sources
- https://www.bing.com/search?q=capital+one+people+moves
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Confirmed",
                "evidence_quote": "Capital One appointed a Business Chief Risk Officer.",
                "source_url": "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
                "source_title": "FinTech Magazine",
                "analysis": "Executive movement confirmed.",
            },
            {
                "signal_code": "FS.REGULATORY.DEADLINE",
                "signal_label": "Regulatory Deadline",
                "status": "Confirmed",
                "evidence_quote": "Submission due by July 1, 2026.",
                "source_url": "https://www.fdic.gov/resolutions/2025-capital-one-interim-resolution-plan-public-section.pdf",
                "source_title": "FDIC",
                "analysis": "Deadline confirmed.",
            },
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, allowed_sources = asyncio.run(
        digestor.digest(
            trigger=_build_trigger(),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION", "FS.REGULATORY.DEADLINE"],
            source_urls=[
                "https://www.bing.com/search?q=capital+one+people+moves",
                "https://fintechmagazine.com/news/people-move-natalie-hyche-kelly",
                "https://www.fdic.gov/resolutions/2025-capital-one-interim-resolution-plan-public-section.pdf",
            ],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert diagnostics["discovery_source_count"] == 3
    assert diagnostics["confirmation_source_count"] == 2
    assert diagnostics["allowed_source_count"] == 2
    assert diagnostics["source_coverage_alert"] is None
    assert len(allowed_sources) == 2
    assert all("bing.com/search" not in source for source in allowed_sources)
    assert sum(1 for item in signal_evidence if item.status == "Confirmed") >= 2


def test_digest_exec_transition_recovers_lower_tier_source_when_movement_near_url():
    markdown = """
Capital One appointed a Business Chief Risk Officer for the Global Payments Network.
Reference coverage: https://regionalbankwatch.example.com/capital-one-risk-leadership-update

# Sources
- https://regionalbankwatch.example.com/capital-one-risk-leadership-update
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert "https://regionalbankwatch.example.com/capital-one-risk-leadership-update" in allowed_sources
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "regionalbankwatch.example.com" in (signal_evidence[0].source_url or "")


def test_digest_exec_transition_links_fintech_people_move_slug_to_entity_mentions():
    markdown = """
Natalie Hyche Kelly is joining Capital One as Business Chief Risk Officer for the Global Payments Network.

# Sources
- https://fintechmagazine.com/news/people-move-natalie-hyche-kelly
"""
    payload = {
        "signal_evidence": [
            {
                "signal_code": "FS.EXEC.TRANSITION",
                "signal_label": "CRO/CFO Transition",
                "status": "Rejected",
                "evidence_quote": "",
                "source_url": "",
                "source_title": "",
                "analysis": "",
            }
        ]
    }

    digestor = FSSignalEvidenceDigestor(
        kernel=_FakeKernel(json.dumps(payload)),
        exec_settings=object(),
    )

    import asyncio
    signal_evidence, diagnostics, _allowed_sources = asyncio.run(
        digestor.digest(
            trigger=BDTrigger(
                sector="Financial Services",
                signals=["FS.EXEC.TRANSITION"],
                company_focus="Capital One",
            ),
            deep_research_markdown=markdown,
            requested_signal_codes=["FS.EXEC.TRANSITION"],
        )
    )

    assert diagnostics["status"] == "Succeeded"
    assert len(signal_evidence) == 1
    assert signal_evidence[0].status == "Confirmed"
    assert "fintechmagazine.com/news/people-move-natalie-hyche-kelly" in (
        (signal_evidence[0].analysis or "").lower() + " " + (signal_evidence[0].source_url or "").lower()
    )
