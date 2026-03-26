"""
Tests for ProConnect stakeholder payload person-profile merging.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.proconnect_stakeholder_payload import build_person_profile_transition  # noqa: E402


def test_build_person_profile_transition_unions_projects_and_wins_from_multiple_sources() -> None:
    matched = {
        "id": "contact-1",
        "name": "Jennifer Brady",
        "title": "Senior Director of Technology Risk",
        "_source": "from_key_buyers",
        "_company_scope": "from",
        "linked_account_id": "001-source",
        "projectCount": 0,
        "winCount": 1,
        "closeWonOpps": [{"opportunityId": "w-1", "name": "Controls Testing"}],
    }
    person_resolution = {
        "status": "matched",
        "match_scope": "from",
        "match_source": "from_key_buyers",
        "matched": matched,
    }
    from_account = {
        "keyBuyers": [
            {
                "firstName": "Jennifer",
                "lastName": "Brady",
                "contactId": "contact-1",
                "relationshipOwner": "Bernadette Norrington",
                "projects": [
                    {"projectId": "p-1", "name": "Technology Controls Refresh"},
                    {"projectId": "p-2", "name": "Cyber Risk Remediation"},
                ],
                "closeWonOpps": [{"opportunityId": "w-2", "name": "IA Co-source"}],
            }
        ],
        "project": [
            {"projectId": "p-2", "name": "Cyber Risk Remediation", "primaryKeyBuyerId": "contact-1"},
            {"projectId": "p-3", "name": "Identity Access Uplift", "primaryKeyBuyerId": "contact-1"},
        ],
        "allOpportunity": [
            {
                "opportunityId": "w-1",
                "name": "Controls Testing",
                "opportunityStage": "Closed - Won",
                "primaryKeyBuyerId": "contact-1",
            },
            {
                "opportunityId": "w-3",
                "name": "SOX Advisory",
                "opportunityStage": "Closed - Won",
                "primaryKeyBuyerId": "contact-1",
            },
        ],
    }

    profile = build_person_profile_transition(
        person_requested="Jennifer Brady",
        person_resolution=person_resolution,
        candidate_people=[matched],
        to_account={},
        from_account=from_account,
        warnings=[],
    )

    assert profile["project_count"] == 3
    assert profile["win_count"] == 3
    assert len(profile["matched_person"]["projects"]) == 3
    assert len(profile["matched_person"]["closeWonOpps"]) == 3
    assert profile["relationship_owner"] == "Bernadette Norrington"
