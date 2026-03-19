"""
Tests for two-pass ProConnect movement enrichment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import MovementEvidence, MovementRecord  # noqa: E402
from services.proconnect_movement_service import ProConnectMovementService  # noqa: E402


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


def _loader(name: str, company: str):
    payloads = {
        "Sarah Chen": {
            "name": "Sarah Chen",
            "title": "VP, Model Risk",
            "location": "McLean, VA, United States",
            "linkedinUrl": "https://linkedin.com/in/sarah-chen",
            "connections": [{"employee": {"name": "Ben L"}}],
            "projects": [{"name": "Model Risk Refresh"}, {"name": "Controls Review"}],
            "primaryKeyBuyerOf": [
                {"name": "Model Risk Refresh", "opportunityStage": "Closed - Won"},
                {"name": "Controls Review", "opportunityStage": "Closed - Won"},
            ],
            "relationshipOwner": "Ben L",
        },
        "Lisa Grant": {
            "name": "Lisa Grant",
            "title": "Head of Data Programs",
            "location": "McLean, VA, United States",
            "linkedinUrl": "https://linkedin.com/in/lisa-grant",
            "connections": [],
            "projects": [{"name": "Data Controls"}],
            "primaryKeyBuyerOf": [],
            "relationshipOwner": "Naomi K",
        },
    }
    return payloads.get(name)


def test_light_enrichment_summarizes_known_and_worked_with_fields():
    service = ProConnectMovementService(person_loader=_loader)

    enriched = service.light_enrich_movements([_row("Sarah Chen"), _row("Unknown Person")])

    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is True
    assert enriched[0]["project_count"] == 2
    assert enriched[0]["win_count"] == 2
    assert enriched[0]["relationship_owner"] == "Ben L"
    assert enriched[0]["person_match_status"] == "matched"

    assert enriched[1]["known"] is False
    assert enriched[1]["worked_with"] is False
    assert enriched[1]["project_count"] == 0
    assert enriched[1]["win_count"] == 0
    assert enriched[1]["person_match_status"] == "no_match"


def test_deep_enrichment_includes_person_detail_only_for_selected_rows():
    service = ProConnectMovementService(person_loader=_loader)

    enriched = service.deep_enrich_movements(
        [_row("Sarah Chen"), _row("Lisa Grant"), _row("Unknown Person")],
        max_rows=2,
    )

    assert len(enriched) == 2
    assert enriched[0]["person_detail"]["title"] == "VP, Model Risk"
    assert enriched[1]["person_detail"]["title"] == "Head of Data Programs"
    assert "linkedin_url" in enriched[0]["person_detail"]


def test_worked_with_is_conservative_when_only_relationship_exists():
    def loader(name: str, company: str):
        return {
            "name": name,
            "title": "Executive",
            "connections": [{"employee": {"name": "Owner"}}],
            "projects": [],
            "primaryKeyBuyerOf": [],
        }

    service = ProConnectMovementService(person_loader=loader)

    enriched = service.light_enrich_movements([_row("Board Member")])

    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is False
    assert enriched[0]["project_count"] == 0
    assert enriched[0]["win_count"] == 0


def test_deep_enrichment_preserves_default_values_when_no_match_exists():
    service = ProConnectMovementService(person_loader=lambda *_: None)

    enriched = service.deep_enrich_movements([_row("Unknown Person")], max_rows=5)

    assert enriched[0]["known"] is False
    assert enriched[0]["worked_with"] is False
    assert enriched[0]["project_count"] == 0
    assert enriched[0]["win_count"] == 0
    assert enriched[0]["relationship_owner"] is None
    assert enriched[0]["person_match_status"] == "no_match"
    assert enriched[0]["person_detail"] == {}
