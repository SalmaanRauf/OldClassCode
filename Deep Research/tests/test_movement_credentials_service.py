"""
Tests for movement credential proof packets.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import CredentialMatch, CredentialsResponse, Opportunity  # noqa: E402
from services.movement_credentials_service import MovementCredentialsService  # noqa: E402


def _derived(person_name: str, title: str, opportunity_id: str):
    return SimpleNamespace(
        opportunity_id=opportunity_id,
        person_name=person_name,
        opportunity=Opportunity(
            opportunity_id=opportunity_id,
            title=title,
            agency="Fannie Mae",
            scope="Derived scope",
            confidence="High",
        ),
    )


def test_credentials_service_prefers_person_account_linked_matches():
    service = MovementCredentialsService()

    packets = service.build_proof_packets(
        [_derived("Sarah Chen", "Sarah Chen Play", "mov_1")],
        {
            "mov_1": CredentialsResponse(
                opportunity_id="mov_1",
                opportunity_title="Sarah Chen Play",
                matches=[
                    CredentialMatch(
                        title="Model Risk Remediation",
                        client_challenge="Challenge",
                        value_provided="Value",
                        url="https://example.com/cred",
                    )
                ],
                lookup_status="Matched",
            )
        },
    )

    assert packets["mov_1"].lookup_status == "Matched"
    assert packets["mov_1"].matched_credentials[0].title == "Model Risk Remediation"
    assert "Matched credentials" in packets["mov_1"].summary


def test_credentials_service_keeps_no_match_packets_explicit():
    service = MovementCredentialsService()

    packets = service.build_proof_packets(
        [_derived("Unknown Person", "Unknown Person Play", "mov_2")],
        {
            "mov_2": CredentialsResponse(
                opportunity_id="mov_2",
                opportunity_title="Unknown Person Play",
                matches=[],
                lookup_status="No Match",
            )
        },
    )

    assert packets["mov_2"].lookup_status == "No Match"
    assert packets["mov_2"].summary == "No materially aligned credentials identified."


def test_credentials_service_defaults_missing_lookup_results_without_dropping_row():
    service = MovementCredentialsService()

    packets = service.build_proof_packets([_derived("Sarah Chen", "Sarah Chen Play", "mov_3")], {})

    assert packets["mov_3"].lookup_status == "Lookup Failed"
    assert "did not return a result" in packets["mov_3"].summary
