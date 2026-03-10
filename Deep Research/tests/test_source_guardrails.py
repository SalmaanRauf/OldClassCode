"""
Unit tests for deterministic source guardrails.
"""

from models.bd_schemas import SignalEvidence
from services.source_guardrails import SourceGuardrails


def test_enforce_on_signal_evidence_keeps_confirmed_when_same_domain_repeats():
    guardrails = SourceGuardrails(domain_cap=1)
    evidence = [
        SignalEvidence(
            signal_code="FS.REGULATORY.DEADLINE",
            signal_label="Regulatory Deadline",
            status="Confirmed",
            evidence_quote="Deadline due by July 1, 2026.",
            source_url="https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html",
            source_title="OCC",
            analysis="Deadline evidence.",
        ),
        SignalEvidence(
            signal_code="FS.STRESS_TEST.ISSUES",
            signal_label="Stress Test",
            status="Confirmed",
            evidence_quote="SCB updated after stress test.",
            source_url="https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-109.html",
            source_title="OCC",
            analysis="Stress signal evidence.",
        ),
    ]
    available_sources = {
        "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-36.html",
        "https://www.occ.gov/news-issuances/news-releases/2025/nr-occ-2025-109.html",
    }

    enforced = guardrails.enforce_on_signal_evidence(evidence, available_sources=available_sources)

    assert all(item.status == "Confirmed" for item in enforced)
