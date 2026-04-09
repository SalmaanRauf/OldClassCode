"""
Tests for ProConnect stakeholder payload person-profile merging.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.proconnect_stakeholder_payload as stakeholder_payload  # noqa: E402
from scripts.proconnect_stakeholder_payload import (  # noqa: E402
    build_person_profile_transition,
    collect_org_chart_people,
    enrich_person_resolution_from_prospect_detail,
)


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


def test_collect_org_chart_people_preserves_distinct_people_with_different_ids(monkeypatch) -> None:
    monkeypatch.setattr(
        stakeholder_payload,
        "DEPARTMENT_TO_SFDC_FUNCTIONS",
        {
            "Finance": ["Compliance"],
            "Legal": ["Compliance"],
        },
    )

    class FakeClient:
        def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
            del zoom_info_account_id, page, size
            if department == "Finance" and sfdc_job_function == "Compliance":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "employees": [
                            {
                                "id": "finance-1",
                                "firstName": "Alex",
                                "lastName": "Morgan",
                                "title": "Director, Compliance",
                            }
                        ]
                    },
                }
            if department == "Legal" and sfdc_job_function == "Compliance":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "employees": [
                            {
                                "id": "legal-1",
                                "firstName": "Alex",
                                "lastName": "Morgan",
                                "title": "Director, Compliance",
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"employees": []}}

    items, people, warnings = collect_org_chart_people(
        client=FakeClient(),
        zoom_info_account_id="72074644",
        department_hint="Finance",
    )

    assert warnings == []
    assert len(people) == 2
    assert len(items) == 2
    assert {item["category_or_department"] for item in items} == {"Finance", "Legal"}


def test_enrich_person_resolution_from_prospect_detail_prefers_richer_nested_candidate() -> None:
    class FakeClient:
        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            del params, retry_on_5xx, retry_delay_seconds, stop_on_auth
            assert endpoint == "/api/prospects/contact-42"
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "contactId": "contact-42",
                    "name": "Danielle McCoy",
                    "title": "Senior Vice President, Deputy General Counsel and Deputy Corporate Secretary",
                    "location": "Washington, DC, United States",
                    "details": {
                        "contactId": "contact-42",
                        "accountId": "001-to",
                        "name": "Danielle McCoy",
                        "title": "Senior Vice President, Deputy General Counsel and Deputy Corporate Secretary",
                        "location": "Washington, DC, United States",
                        "relationshipOwner": "Germaal Ross",
                        "projectCount": 2,
                        "winCount": 1,
                        "projects": [
                            {"projectId": "p-1", "name": "Legal Controls Modernization"},
                            {"projectId": "p-2", "name": "Deputy GC Advisory"},
                        ],
                        "closeWonOpps": [
                            {"opportunityId": "w-1", "name": "Controls Review"}
                        ],
                    },
                },
            }

    matched = {
        "id": "contact-42",
        "contactId": "contact-42",
        "name": "Danielle McCoy",
        "title": "Senior Vice President, Deputy General Counsel and Deputy Corporate Secretary",
        "_source": "to_org_chart_department",
        "_company_scope": "to",
        "linked_account_id": "001-to",
        "linked_company_name": "Federal National Mortgage Association (Fannie Mae)",
    }
    person_resolution = {
        "status": "matched",
        "match_source": "to_org_chart_department",
        "match_scope": "to",
        "match_strategy": "exact_name_to_account",
        "matched": matched,
    }

    warnings: list[str] = []
    enriched_resolution = enrich_person_resolution_from_prospect_detail(
        client=FakeClient(),
        person_name="Danielle McCoy",
        person_resolution=person_resolution,
        candidate_people=[matched],
        warnings=warnings,
    )
    profile = build_person_profile_transition(
        person_requested="Danielle McCoy",
        person_resolution=enriched_resolution,
        candidate_people=[enriched_resolution["matched"]],
        to_account={},
        from_account=None,
        warnings=warnings,
    )

    assert warnings == []
    assert profile["project_count"] == 2
    assert profile["win_count"] == 1
    assert len(profile["matched_person"]["projects"]) == 2
    assert len(profile["matched_person"]["closeWonOpps"]) == 1
    assert profile["relationship_owner"] == "Germaal Ross"


def test_enrich_person_resolution_from_prospect_detail_aggregates_nested_evidence_fragments() -> None:
    class FakeClient:
        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            del params, retry_on_5xx, retry_delay_seconds, stop_on_auth
            assert endpoint == "/api/prospects/contact-77"
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "contactId": "contact-77",
                    "accountId": "001-to",
                    "name": "Jason Dandridge",
                    "title": "Head of Operations",
                    "location": "Washington, DC, United States",
                    "relationshipSnapshot": {
                        "relationshipOwner": "Taylor Smith"
                    },
                    "projectPortfolio": {
                        "projectCount": 2,
                        "projects": [
                            {"projectId": "p-10", "name": "Ops Transformation"},
                            {"projectId": "p-11", "name": "Shared Services Modernization"},
                        ],
                    },
                    "closedWonSummary": {
                        "winCount": 1,
                        "closeWonOpps": [
                            {"opportunityId": "w-10", "name": "Controls Improvement Program"}
                        ],
                    },
                },
            }

    matched = {
        "id": "contact-77",
        "contactId": "contact-77",
        "name": "Jason Dandridge",
        "title": "Head of Operations",
        "_source": "person_search",
        "_company_scope": "to",
        "linked_account_id": "001-to",
        "linked_company_name": "Federal National Mortgage Association (Fannie Mae)",
    }
    person_resolution = {
        "status": "matched",
        "match_source": "person_search",
        "match_scope": "to",
        "match_strategy": "exact_name_to_account",
        "matched": matched,
    }

    warnings: list[str] = []
    enriched_resolution = enrich_person_resolution_from_prospect_detail(
        client=FakeClient(),
        person_name="Jason Dandridge",
        person_resolution=person_resolution,
        candidate_people=[matched],
        warnings=warnings,
    )
    profile = build_person_profile_transition(
        person_requested="Jason Dandridge",
        person_resolution=enriched_resolution,
        candidate_people=[enriched_resolution["matched"]],
        to_account={},
        from_account=None,
        warnings=warnings,
    )

    assert warnings == []
    assert profile["project_count"] == 2
    assert profile["win_count"] == 1
    assert len(profile["matched_person"]["projects"]) == 2
    assert len(profile["matched_person"]["closeWonOpps"]) == 1
    assert profile["relationship_owner"] == "Taylor Smith"
    assert enriched_resolution["detail_diagnostics"]["selected_path"] == "root"


def test_build_person_profile_transition_ignores_unaligned_detail_evidence_warning() -> None:
    matched = {
        "id": "contact-88",
        "contactId": "contact-88",
        "name": "Nancy Jardini",
        "title": "Deputy General Counsel",
        "_source": "person_search",
        "_company_scope": "to",
        "linked_account_id": "001-to",
    }
    person_resolution = {
        "status": "matched",
        "match_scope": "to",
        "match_source": "person_search",
        "matched": matched,
        "detail_diagnostics": {
            "max_observed_project_count": 0,
            "max_observed_win_count": 10,
            "max_aligned_project_count": 0,
            "max_aligned_win_count": 0,
        },
    }

    warnings: list[str] = []
    profile = build_person_profile_transition(
        person_requested="Nancy Jardini",
        person_resolution=person_resolution,
        candidate_people=[matched],
        to_account={},
        from_account=None,
        warnings=warnings,
    )

    assert profile["project_count"] == 0
    assert profile["win_count"] == 0
    assert warnings == []


def test_build_person_profile_transition_requires_name_match_for_key_buyer_merge() -> None:
    matched = {
        "id": "contact-jason",
        "contactId": "contact-jason",
        "name": "Jason Dandridge",
        "title": "Head of Operations",
        "_source": "person_search",
        "_company_scope": "to",
        "linked_account_id": "001-to",
    }
    person_resolution = {
        "status": "matched",
        "match_scope": "to",
        "match_source": "person_search",
        "matched": matched,
    }
    to_account = {
        "keyBuyers": [
            {
                "id": "contact-jason",
                "firstName": "Mike",
                "lastName": "Gabbay",
                "relationshipOwner": "Wrong Owner",
                "winCount": 7,
                "closeWonOpps": [{"opportunityId": "w-1", "name": "Wrong Win"}],
            }
        ],
        "project": [],
        "allOpportunity": [],
    }

    profile = build_person_profile_transition(
        person_requested="Jason Dandridge",
        person_resolution=person_resolution,
        candidate_people=[matched],
        to_account=to_account,
        from_account=None,
        warnings=[],
    )

    assert profile["win_count"] == 0
    assert profile["relationship_owner"] is None
    assert profile["matched_person"]["closeWonOpps"] == []


def test_build_person_profile_transition_does_not_trust_unscoped_person_search_delivery_counts() -> None:
    matched = {
        "id": "contact-danielle",
        "contactId": "contact-danielle",
        "name": "Danielle McCoy",
        "title": "Senior Vice President, Deputy General Counsel & Deputy Corporate Secretary",
        "_source": "person_search",
        "_company_scope": "to",
        "linked_account_id": "001-to",
        "winCount": 10,
        "closeWonOpps": [{"opportunityId": "w-1", "name": "Wrong Win"}],
    }
    person_resolution = {
        "status": "matched",
        "match_scope": "to",
        "match_source": "person_search",
        "matched": matched,
    }

    profile = build_person_profile_transition(
        person_requested="Danielle McCoy",
        person_resolution=person_resolution,
        candidate_people=[matched],
        to_account={"keyBuyers": [], "project": [], "allOpportunity": []},
        from_account=None,
        warnings=[],
    )

    assert profile["project_count"] == 0
    assert profile["win_count"] == 0
    assert profile["matched_person"]["closeWonOpps"] == []
