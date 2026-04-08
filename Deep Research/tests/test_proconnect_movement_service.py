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


class _FakeLiveClient:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.account_calls: list[str] = []
        self.endpoint_calls: list[str] = []

    def search_prospects(self, search_text):
        self.search_calls.append(search_text)

        if search_text == "Capital One":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "value": [
                        {
                            "document": {
                                "accountId": "001-cap-one",
                                "companyName": "Capital One Financial Corporation",
                                "name": "Capital One Financial Corporation",
                            }
                        }
                    ]
                },
            }

        if search_text == "Sarah Chen":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "value": [
                        {
                            "document": {
                                "contactId": "contact-123",
                                "accountId": "001-cap-one",
                                "companyName": "Capital One Financial Corporation",
                                "name": "Sarah Chen",
                                "title": "VP, Model Risk",
                                "location": "McLean, VA, United States",
                                "linkedinUrl": "https://linkedin.com/in/sarah-chen",
                            }
                        },
                        {
                            "document": {
                                "contactId": "contact-999",
                                "accountId": "001-other",
                                "companyName": "Other Company",
                                "name": "Sarah Chen",
                                "title": "VP, Other Company",
                            }
                        },
                    ]
                },
            }

        return {"success": True, "status_code": 200, "data": {"value": []}}

    def get_account_by_id(self, account_id: str):
        self.account_calls.append(account_id)
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": "001-cap-one",
                "name": "Capital One Financial Corporation",
                "keyBuyers": [
                    {
                        "firstName": "Sarah",
                        "lastName": "Chen",
                        "title": "VP, Model Risk",
                        "projects": [{"name": "Model Risk Refresh"}],
                        "primaryKeyBuyerOf": [
                            {"name": "Model Risk Refresh", "opportunityStage": "Closed - Won"}
                        ],
                        "relationshipOwner": "Ben L",
                    }
                ],
            },
        }

    def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
        self.endpoint_calls.append(endpoint)

        if endpoint == "/api/prospects/contact-123":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "ContactId": "contact-123",
                    "FirstName": "Sarah",
                    "LastName": "Chen",
                    "Title": "Director, Model Risk",
                    "Location": "McLean, VA, United States",
                    "LinkedInUrl": "https://linkedin.com/in/sarah-chen",
                    "ExternalProspectView": {
                        "Title": "Director, Model Risk",
                        "Phone": "555-0101",
                        "Location": "McLean, VA, United States",
                        "LinkedInUrl": "https://linkedin.com/in/sarah-chen",
                    },
                },
            }

        raise AssertionError(f"Unexpected endpoint {endpoint}")


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


def test_light_enrichment_marks_exact_matched_person_as_known_without_delivery_history():
    def loader(name: str, company: str):
        return {
            "name": name,
            "title": "Senior Vice President",
            "location": "Washington, DC, United States",
            "linkedinUrl": "https://linkedin.com/in/jason-dandridge",
            "projects": [],
            "primaryKeyBuyerOf": [],
        }

    service = ProConnectMovementService(person_loader=loader)

    enriched = service.light_enrich_movements([_row("Jason Dandridge")])

    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is False
    assert enriched[0]["project_count"] == 0
    assert enriched[0]["win_count"] == 0
    assert enriched[0]["person_match_status"] == "matched"


def test_light_enrichment_uses_close_won_and_snake_case_relationship_owner_fields():
    def loader(name: str, company: str):
        return {
            "name": name,
            "title": "Head of Operations",
            "projectCount": 3,
            "closeWonOpps": [
                {"name": "Controls Review"},
                {"name": "RCSA Program"},
            ],
            "relationship_owner": "Ben L",
        }

    service = ProConnectMovementService(person_loader=loader)

    enriched = service.light_enrich_movements([_row("Jason Dandridge")])

    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is True
    assert enriched[0]["project_count"] == 3
    assert enriched[0]["win_count"] == 2
    assert enriched[0]["relationship_owner"] == "Ben L"


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


def test_live_client_path_exact_matches_person_and_hydrates_detail_once():
    client = _FakeLiveClient()
    service = ProConnectMovementService(client=client)

    enriched = service.deep_enrich_movements([_row("Sarah Chen"), _row("Sarah Chen")], max_rows=5)

    assert len(enriched) == 2
    assert enriched[0]["person_match_status"] == "matched"
    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is True
    assert enriched[0]["project_count"] == 1
    assert enriched[0]["win_count"] == 1
    assert enriched[0]["relationship_owner"] == "Ben L"
    assert enriched[0]["person_detail"]["title"] == "Director, Model Risk"
    assert enriched[0]["person_detail"]["location"] == "McLean, VA, United States"
    assert enriched[0]["person_detail"]["linkedin_url"] == "https://linkedin.com/in/sarah-chen"

    assert client.search_calls == ["Capital One", "Sarah Chen"]
    assert client.account_calls == ["001-cap-one"]
    assert client.endpoint_calls == ["/api/prospects/contact-123"]


def test_live_client_path_prefers_richer_key_buyer_counts_over_sparse_search_counts():
    class RicherKeyBuyerClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return super().search_prospects(search_text)
            if search_text == "Sarah Chen":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-123",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One Financial Corporation",
                                    "name": "Sarah Chen",
                                    "title": "VP, Model Risk",
                                    "projectCount": 0,
                                    "winCount": 1,
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One Financial Corporation",
                    "keyBuyers": [
                        {
                            "firstName": "Sarah",
                            "lastName": "Chen",
                            "title": "VP, Model Risk",
                            "projectCount": 4,
                            "projects": [
                                {"name": "Model Risk Refresh"},
                                {"name": "Controls Review"},
                            ],
                            "closeWonOpps": [
                                {"name": "Model Risk Refresh"},
                                {"name": "Controls Review"},
                                {"name": "Audit Uplift"},
                            ],
                            "relationshipOwner": "Ben L",
                        }
                    ],
                },
            }

    client = RicherKeyBuyerClient()
    service = ProConnectMovementService(client=client)

    enriched = service.deep_enrich_movements([_row("Sarah Chen")], max_rows=5)

    assert enriched[0]["project_count"] == 4
    assert enriched[0]["win_count"] == 3


def test_live_client_path_recovers_account_scoped_projects_and_wins_when_person_payload_is_sparse():
    class AccountScopedEvidenceClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return super().search_prospects(search_text)
            if search_text == "Sarah Chen":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-123",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One Financial Corporation",
                                    "name": "Sarah Chen",
                                    "title": "VP, Model Risk",
                                    "projectCount": 0,
                                    "winCount": 0,
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One Financial Corporation",
                    "keyBuyers": [
                        {
                            "firstName": "Sarah",
                            "lastName": "Chen",
                            "title": "VP, Model Risk",
                            "relationshipOwner": "Ben L",
                        }
                    ],
                    "project": [
                        {"projectId": "p1", "name": "Model Risk Refresh", "primaryKeyBuyer": "Sarah Chen"},
                        {"projectId": "p2", "name": "Controls Review", "primaryKeyBuyer": "Sarah Chen"},
                    ],
                    "allOpportunity": [
                        {"opportunityId": "o1", "name": "Audit Uplift", "primaryKeyBuyer": "Sarah Chen", "opportunityStage": "Closed - Won"},
                        {"opportunityId": "o2", "name": "RCSA Refresh", "primaryKeyBuyer": "Sarah Chen", "opportunityStage": "Closed - Won"},
                    ],
                },
            }

    client = AccountScopedEvidenceClient()
    service = ProConnectMovementService(client=client)

    enriched = service.deep_enrich_movements([_row("Sarah Chen")], max_rows=5)

    assert enriched[0]["known"] is True
    assert enriched[0]["worked_with"] is True
    assert enriched[0]["project_count"] == 2
    assert enriched[0]["win_count"] == 2
    assert enriched[0]["relationship_owner"] == "Ben L"


def test_live_client_path_falls_back_to_same_first_last_name_within_account():
    class FirstLastFallbackClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return super().search_prospects(search_text)
            if search_text == "Sarah Chen":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-123",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One Financial Corporation",
                                    "name": "Sarah M. Chen",
                                    "title": "VP, Model Risk",
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

    client = FirstLastFallbackClient()
    service = ProConnectMovementService(client=client)

    enriched = service.deep_enrich_movements([_row("Sarah Chen")], max_rows=5)

    assert enriched[0]["person_match_status"] == "matched"
    assert enriched[0]["known"] is True


def test_live_client_path_falls_back_to_org_chart_people_when_search_and_key_buyers_miss():
    class OrgChartFallbackClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return super().search_prospects(search_text)
            if search_text == "John Roscoe":
                return {"success": True, "status_code": 200, "data": {"value": []}}
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One Financial Corporation",
                    "zoomInfoAccountId": "zi-cap-one",
                    "keyBuyers": [],
                },
            }

        def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
            assert zoom_info_account_id == "zi-cap-one"
            if department == "C-Suite" and sfdc_job_function == "Executive":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "employees": [
                            {
                                "id": "contact-roscoe",
                                "name": "John Roscoe",
                                "title": "Co-President",
                                "department": "C-Suite",
                                "location": "Washington, DC, United States",
                                "linkedinUrl": "https://linkedin.com/in/john-roscoe",
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"employees": []}}

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            if endpoint == "/api/prospects/contact-roscoe":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "ContactId": "contact-roscoe",
                        "FirstName": "John",
                        "LastName": "Roscoe",
                        "Title": "Co-President",
                        "Location": "Washington, DC, United States",
                        "LinkedInUrl": "https://linkedin.com/in/john-roscoe",
                    },
                }
            raise AssertionError(f"Unexpected endpoint {endpoint}")

    client = OrgChartFallbackClient()
    service = ProConnectMovementService(client=client)

    enriched = service.deep_enrich_movements([_row("John Roscoe")], max_rows=5)

    assert enriched[0]["person_match_status"] == "matched"
    assert enriched[0]["person_detail"]["title"] == "Co-President"
    assert enriched[0]["person_detail"]["linkedin_url"] == "https://linkedin.com/in/john-roscoe"


def test_live_client_path_prefers_person_detail_linkedin_and_connections_over_stale_search_fields():
    class JasonDetailClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"value": [{"document": {"accountId": "001-cap-one", "name": "Capital One"}}]},
                }
            if search_text == "Jason Dandridge":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-jason",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One",
                                    "name": "Jason Dandridge",
                                    "title": "Head of Operations",
                                    "linkedinUrl": "https://linkedin.com/in/mike-gabbay",
                                    "winCount": 10,
                                    "closeWonOpps": [{"name": "Wrong Win"}],
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One",
                    "keyBuyers": [],
                    "project": [],
                    "allOpportunity": [],
                },
            }

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            if endpoint == "/api/prospects/contact-jason":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "contactId": "contact-jason",
                        "accountId": "001-cap-one",
                        "name": "Jason Dandridge",
                        "title": "Chief Control Officer & Head of Enterprise Operations",
                        "location": "Washington, DC, United States",
                        "linkedinUrl": "https://linkedin.com/in/jason-dandridge",
                        "connectedColleagues": [{"employee": {"name": "Taylor Smith"}}],
                    },
                }
            raise AssertionError(f"Unexpected endpoint {endpoint}")

    service = ProConnectMovementService(client=JasonDetailClient())
    enriched = service.deep_enrich_movements([_row("Jason Dandridge")], max_rows=5)

    assert enriched[0]["win_count"] == 0
    assert enriched[0]["worked_with"] is False
    assert enriched[0]["person_detail"]["linkedin_url"] == "https://linkedin.com/in/jason-dandridge"
    assert enriched[0]["person_detail"]["internal_connections"] == ["Taylor Smith"]


def test_live_client_path_does_not_use_unscoped_person_wins_without_matching_account_evidence():
    class InflatedWinsClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"value": [{"document": {"accountId": "001-cap-one", "name": "Capital One"}}]},
                }
            if search_text == "Danielle M. McCoy":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-danielle",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One",
                                    "name": "Danielle Mccoy",
                                    "title": "Senior Vice President, Deputy General Counsel & Deputy Corporate Secretary",
                                    "winCount": 10,
                                    "closeWonOpps": [
                                        {"name": "Fannie Mae - IT Audit Support"},
                                        {"name": "Fannie Mae - IA IT Staff Aug"},
                                    ],
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One",
                    "keyBuyers": [],
                    "project": [],
                    "allOpportunity": [],
                },
            }

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            if endpoint == "/api/prospects/contact-danielle":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "contactId": "contact-danielle",
                        "accountId": "001-cap-one",
                        "name": "Danielle McCoy",
                        "title": "Senior Vice President, Deputy General Counsel & Deputy Corporate Secretary",
                    },
                }
            raise AssertionError(f"Unexpected endpoint {endpoint}")

    service = ProConnectMovementService(client=InflatedWinsClient())
    enriched = service.deep_enrich_movements([_row("Danielle M. McCoy")], max_rows=5)

    assert enriched[0]["project_count"] == 0
    assert enriched[0]["win_count"] == 0
    assert enriched[0]["worked_with"] is False


def test_live_client_path_requires_name_match_for_key_buyer_merge():
    class KeyBuyerBleedClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {"value": [{"document": {"accountId": "001-cap-one", "name": "Capital One"}}]},
                }
            if search_text == "Jason Dandridge":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-jason",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One",
                                    "name": "Jason Dandridge",
                                    "title": "Head of Operations",
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_account_by_id(self, account_id: str):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "id": "001-cap-one",
                    "name": "Capital One",
                    "keyBuyers": [
                        {
                            "id": "contact-jason",
                            "firstName": "Mike",
                            "lastName": "Gabbay",
                            "title": "CIO",
                            "linkedinUrl": "https://linkedin.com/in/mike-gabbay",
                            "winCount": 7,
                            "closeWonOpps": [{"name": "Wrong Buyer Win"}],
                        }
                    ],
                    "project": [],
                    "allOpportunity": [],
                },
            }

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            if endpoint == "/api/prospects/contact-jason":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "contactId": "contact-jason",
                        "accountId": "001-cap-one",
                        "name": "Jason Dandridge",
                        "title": "Chief Control Officer & Head of Enterprise Operations",
                        "linkedinUrl": "https://linkedin.com/in/jason-dandridge",
                    },
                }
            raise AssertionError(f"Unexpected endpoint {endpoint}")

    service = ProConnectMovementService(client=KeyBuyerBleedClient())
    enriched = service.deep_enrich_movements([_row("Jason Dandridge")], max_rows=5)

    assert enriched[0]["win_count"] == 0
    assert enriched[0]["relationship_owner"] is None
    assert enriched[0]["person_detail"]["linkedin_url"] == "https://linkedin.com/in/jason-dandridge"


def test_person_loader_takes_precedence_over_live_client_support():
    class GuardedClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            raise AssertionError("live client should not be used when person_loader is provided")

        def get_account_by_id(self, account_id: str):
            raise AssertionError("live client should not be used when person_loader is provided")

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            raise AssertionError("live client should not be used when person_loader is provided")

    service = ProConnectMovementService(
        person_loader=_loader,
        client=GuardedClient(),
    )

    enriched = service.deep_enrich_movements([_row("Sarah Chen")], max_rows=5)

    assert enriched[0]["person_match_status"] == "matched"
    assert enriched[0]["person_detail"]["title"] == "VP, Model Risk"
    assert enriched[0]["person_detail"]["location"] == "McLean, VA, United States"


def test_live_client_path_tries_parenthetical_alias_variant_for_person_search():
    class AliasClient(_FakeLiveClient):
        def search_prospects(self, search_text):
            if search_text == "Capital One":
                return super().search_prospects(search_text)
            if search_text == "Thomas (Tom) Klein":
                return {"success": True, "status_code": 200, "data": {"value": []}}
            if search_text == "Tom Klein":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "value": [
                            {
                                "document": {
                                    "contactId": "contact-456",
                                    "accountId": "001-cap-one",
                                    "companyName": "Capital One Financial Corporation",
                                    "name": "Tom Klein",
                                    "title": "Acting General Counsel",
                                    "relationshipOwner": "Germaal Ross",
                                    "projectCount": 2,
                                    "closeWonOpps": [{"name": "Legal Controls"}],
                                }
                            }
                        ]
                    },
                }
            return {"success": True, "status_code": 200, "data": {"value": []}}

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            if endpoint == "/api/prospects/contact-456":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "ContactId": "contact-456",
                        "FirstName": "Tom",
                        "LastName": "Klein",
                        "Title": "Acting General Counsel",
                        "RelationshipOwner": "Germaal Ross",
                    },
                }
            return super().get_endpoint(
                endpoint,
                params=params,
                retry_on_5xx=retry_on_5xx,
                retry_delay_seconds=retry_delay_seconds,
                stop_on_auth=stop_on_auth,
            )

    client = AliasClient()
    service = ProConnectMovementService(client=client)
    row = _row("Thomas (Tom) Klein")

    enriched = service.deep_enrich_movements([row], max_rows=5)

    assert enriched[0]["person_match_status"] == "matched"
    assert enriched[0]["relationship_owner"] == "Germaal Ross"
    assert enriched[0]["project_count"] == 2
