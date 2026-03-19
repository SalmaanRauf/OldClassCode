"""
Tests for movement credential proof packets.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import MovementEvidence, MovementRecord  # noqa: E402
from services.movement_credentials_service import MovementCredentialsService  # noqa: E402


def _row(name: str) -> MovementRecord:
    return MovementRecord(
        person_name=name,
        target_company="Capital One",
        previous_role="Director",
        new_role="Vice President",
        movement_type="Promoted",
        category="BUYER",
        company_context="internal",
        evidence=MovementEvidence(
            evidence_quote=f"{name} was promoted.",
            source_url=f"https://example.com/{name.lower().replace(' ', '-')}",
        ),
    )


def test_credentials_service_prefers_person_account_linked_matches():
    def lookup(row):
        return {
            "lookup_status": "Matched",
            "summary": f"Prior delivery for {row.person_name} adjacent team.",
            "matched_credentials": [
                {"title": "Model Risk Remediation", "url": "https://example.com/cred"}
            ],
        }

    service = MovementCredentialsService(lookup=lookup)

    packets = service.build_proof_packets([{"movement": _row("Sarah Chen")}])

    assert packets["Sarah Chen"].lookup_status == "Matched"
    assert packets["Sarah Chen"].matched_credentials[0].title == "Model Risk Remediation"


def test_credentials_service_keeps_no_match_packets_explicit():
    service = MovementCredentialsService(
        lookup=lambda row: {"lookup_status": "No Match", "summary": "No internal proof found."}
    )

    packets = service.build_proof_packets([{"movement": _row("Unknown Person")}])

    assert packets["Unknown Person"].lookup_status == "No Match"
    assert packets["Unknown Person"].summary == "No internal proof found."


def test_credentials_service_defaults_lookup_failures_without_dropping_row():
    def lookup(_row):
        raise RuntimeError("service unavailable")

    service = MovementCredentialsService(lookup=lookup)

    packets = service.build_proof_packets([{"movement": _row("Sarah Chen")}])

    assert packets["Sarah Chen"].lookup_status == "Lookup Failed"
    assert "service unavailable" in packets["Sarah Chen"].summary
