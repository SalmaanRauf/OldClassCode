from __future__ import annotations

import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import proconnect_stakeholder_payload as stakeholder_payload  # noqa: E402

from proconnect_stakeholder_payload import (  # noqa: E402
    build_account_context,
    build_from_company_context_lite,
    build_key_buyers_section,
    build_opportunities_section,
    build_person_profile_transition,
    build_projects_section,
    merge_person_candidates,
    probe_additional_endpoints,
    resolve_person_transition,
    run_stakeholder_case,
    summarize_probe_payloads,
)


def sample_account() -> dict:
    return {
        "id": "001-test",
        "name": "Capital One Financial Corporation",
        "modifiedDate": "2025-02-01T00:00:00Z",
        "annualRevenue": 45000000000,
        "headQuarters": "McLean, VA",
        "ipoDate": "1994-11-16T00:00:00Z",
        "isClient": True,
        "numberOfEmployees": 52000,
        "websiteUrl": "www.capitalone.com",
        "accountType": "Strategic",
        "tickerSymbol": "COF",
        "startYear": "1994",
        "industry": "Financial Services & Real Estate",
        "shortName": "Capital One",
        "hubId": "hub-1",
        "ownership": "Public",
        "subIndustry": "Banking and Capital Markets",
        "ranking": "Fortune 100",
        "companyPhotoUrl": "https://img.example.com/cof.png",
        "sfdcAccountIds": ["00130000000BYU2AAO"],
        "zoomInfoAccountId": "9012358",
        "isMSA": True,
        "isSanction": False,
        "isExternalOnly": False,
        "companyDescription": "A diversified bank.",
        "numberOfOpenOpportunity": 2,
        "numberOfAllOpportunity": 5,
        "numberOfProject": 3,
        "project": [
            {
                "projectId": "proj-1",
                "name": "Controls remediation",
                "endedDate": "2024-08-01T00:00:00Z",
                "openDate": "2024-01-15T00:00:00Z",
                "projectStatus": "Closed",
                "solution": "R&C",
                "engagementManagingDirector": "Ram Balakrishnan",
                "engagementManager": "Maria Davis",
                "primaryKeyBuyer": "Jennifer Brady",
                "primaryKeyBuyerId": "pkb-1",
                "isConfidential": False,
            }
        ],
        "allOpportunity": [
            {
                "opportunityId": "opp-1",
                "opportunityKey": "OPP-001",
                "name": "Technology risk assessment",
                "opportunityCloseDate": "2025-03-15T00:00:00Z",
                "opportunityCreatedDate": "2025-01-10T00:00:00Z",
                "opportunityManagingDirector": "Laura Brown",
                "primaryKeyBuyer": "Jennifer Brady",
                "primaryKeyBuyerId": "pkb-1",
                "solution": "TC",
                "solutionSegment": "Technology Consulting",
                "serviceOffering": "Technology Risk",
                "opportunityStage": "Opportunity Qualified",
                "engagementManager": "Melissa Desjardins",
                "isConfidential": True,
                "winLossExplanation": "Strong prior delivery",
                "reasonForLoss": None,
            }
        ],
        "keyBuyers": [
            {
                "id": "buyer-1",
                "firstName": "Jennifer",
                "lastName": "Brady",
                "title": "Senior Director of Technology Risk",
                "emailAddress": "jennifer.brady@capitalone.com",
                "linkedinUrl": "https://www.linkedin.com/in/jennifer-brady",
                "numberOfWins": 3,
                "lastOpportunityWonDate": "2024-07-24T00:00:00Z",
                "lastOpportunityStage": "Closed - Won",
                "function": "Technology",
                "closeWonOpps": [{"name": "IA Co-source"}],
            }
        ],
        "accountMDD": {
            "firstName": "Laura",
            "lastName": "Brown",
            "title": "Managing Director",
            "emailAddress": "laura.brown@protiviti.com",
        },
        "accountExecutive": {
            "firstName": "Ava",
            "lastName": "Exec",
            "title": "Account Executive",
            "emailAddress": "ava.exec@protiviti.com",
        },
        "accountPMO": {
            "firstName": "Pat",
            "lastName": "PMO",
            "title": "Program Manager",
        },
        "protivitiAlumni": [
            {
                "firstName": "Steed",
                "lastName": "Armistead",
                "title": "Data Steward",
            }
        ],
        "connectedColleague": [
            {
                "firstName": "Robert",
                "lastName": "Clark",
                "companyName": "Protiviti Inc.",
                "title": "Associate Director, R&C-Regulatory, Atlanta Office",
                "lastConnectedMethod": "Meeting",
                "lastConnectedDate": "Jan 2026",
                "numberOfInteractions": 2,
            }
        ],
        "parentCompany": "Capital One",
        "childCompanies": [{"id": "child-1", "name": "Capital One Bank"}],
    }


def test_build_account_context_includes_extended_company_summary_fields() -> None:
    context = build_account_context(sample_account())

    assert context["headquarters"] == "McLean, VA"
    assert context["sub_industry"] == "Banking and Capital Markets"
    assert context["annual_revenue"] == 45000000000
    assert context["number_of_employees"] == 52000
    assert context["last_updated"] == "2025-02-01T00:00:00Z"
    assert context["account_activity_status"] == "active"
    assert context["parent_company"] == "Capital One"
    assert context["child_companies"] == [{"account_id": "child-1", "company_name": "Capital One Bank"}]


def test_build_from_company_context_lite_exposes_relationship_network_and_recent_engagement() -> None:
    context = build_from_company_context_lite(sample_account())

    assert context["historical_solution_footprint"]["most_recent_engagement_date"] == "2025-03-15T00:00:00Z"
    assert context["prior_relationship_indicators"]["warm_intro_path_available"] is True
    assert context["account_team"]["account_executive"]["name"] == "Ava Exec"
    assert context["relationship_network"]["protiviti_alumni"]["items"] == [
        {"name": "Steed Armistead", "title": "Data Steward"}
    ]
    assert context["relationship_network"]["connected_colleagues"]["items"] == [
        {
            "name": "Robert Clark",
            "employer": "Protiviti Inc.",
            "title": "Associate Director, R&C-Regulatory, Atlanta Office",
            "last_connected_method": "Meeting",
            "last_connected_date": "Jan 2026",
            "number_of_interactions": 2,
        }
    ]


def test_build_from_company_context_lite_handles_plural_connected_colleagues_shape() -> None:
    account = sample_account()
    account["connectedColleagues"] = [
        {
            "employee": {
                "name": "Bernadette Norrington",
                "title": "Managing Director",
                "company": "Protiviti Inc.",
            },
            "lastContactType": "Email",
            "lastContactTime": "2025-05-02T00:00:00Z",
            "numberOfInteractions": 6,
        }
    ]
    account.pop("connectedColleague", None)

    context = build_from_company_context_lite(account)

    assert context["relationship_network"]["connected_colleagues"]["items"] == [
        {
            "name": "Bernadette Norrington",
            "employer": "Protiviti Inc.",
            "title": "Managing Director",
            "last_connected_method": "Email",
            "last_connected_date": "2025-05-02T00:00:00Z",
            "number_of_interactions": 6,
        }
    ]


def test_sections_preserve_richer_proconnect_metadata() -> None:
    account = sample_account()
    project = build_projects_section(account)["items"][0]
    opportunity = build_opportunities_section(account)["items"][0]
    buyer = build_key_buyers_section(account)["items"][0]

    assert project["open_date"] == "2024-01-15T00:00:00Z"
    assert project["ended_date"] == "2024-08-01T00:00:00Z"
    assert project["project_status"] == "Closed"
    assert project["is_confidential"] is False

    assert opportunity["is_confidential"] is True
    assert opportunity["win_loss_explanation"] == "Strong prior delivery"
    assert opportunity["reason_for_loss"] is None

    assert buyer["email_address"] == "jennifer.brady@capitalone.com"
    assert buyer["linkedin_url"] == "https://www.linkedin.com/in/jennifer-brady"
    assert buyer["last_opportunity_stage"] == "Closed - Won"
    assert buyer["function"] == "Technology"
    assert buyer["close_won_opportunities"] == [{"name": "IA Co-source"}]


def test_build_person_profile_transition_includes_last_updated_metadata() -> None:
    warnings: list[str] = []
    profile = build_person_profile_transition(
        person_requested="Jennifer Brady",
        person_resolution={
            "status": "matched",
            "match_source": "from_key_buyers",
            "match_scope": "from",
            "matched": {
                "name": "Jennifer Brady",
                "title": "Senior Director of Technology Risk",
                "titleSalesforce": "Senior Director of Technology Risk",
                "titleExternal": "Senior Director, Technology Risk",
                "location": "McLean, VA",
                "isInSalesforce": True,
                "isProtivitiAlumni": False,
                "hasRoberthalfContact": False,
                "emailAddress": "jennifer.brady@capitalone.com",
                "phone": "555-0100",
                "linkedinUrl": "https://www.linkedin.com/in/jennifer-brady",
                "pastJobExperience": ["Bank A"],
                "education": ["University X"],
                "lastUpdated": "2024-09-17",
            },
        },
        candidate_people=[],
        to_account=sample_account(),
        from_account=sample_account(),
        warnings=warnings,
    )

    assert profile["last_updated"] == "2024-09-17"


def test_build_person_profile_transition_recovers_project_and_win_counts_from_account_scope() -> None:
    warnings: list[str] = []
    profile = build_person_profile_transition(
        person_requested="Jennifer Brady",
        person_resolution={
            "status": "matched",
            "match_source": "from_key_buyers",
            "match_scope": "from",
            "matched": {
                "name": "Jennifer Brady",
                "title": "Senior Director of Technology Risk",
                "titleSalesforce": "Senior Director of Technology Risk",
                "relationshipOwner": "Bernadette Norrington",
                "projectCount": 0,
                "winCount": 0,
            },
        },
        candidate_people=[],
        to_account=sample_account(),
        from_account=sample_account(),
        warnings=warnings,
    )

    assert profile["project_count"] == 1
    assert profile["win_count"] == 3


def test_build_person_profile_transition_preserves_person_level_connections() -> None:
    warnings: list[str] = []
    profile = build_person_profile_transition(
        person_requested="Jennifer Brady",
        person_resolution={
            "status": "matched",
            "match_source": "from_key_buyers",
            "match_scope": "from",
            "matched": {
                "name": "Jennifer Brady",
                "title": "Senior Director of Technology Risk",
                "connections": [
                    {"employee": {"name": "Bernadette Norrington"}},
                    {"employee": {"name": "Maeve Raak"}},
                    {"employee": {"name": "Shawn Marion"}},
                ],
            },
        },
        candidate_people=[],
        to_account=sample_account(),
        from_account=sample_account(),
        warnings=warnings,
    )

    assert profile["matched_person"]["connections"] == [
        {"employee": {"name": "Bernadette Norrington"}},
        {"employee": {"name": "Maeve Raak"}},
        {"employee": {"name": "Shawn Marion"}},
    ]


def test_merge_person_candidates_prefers_richer_relationship_counts_over_zero_placeholders() -> None:
    merged = merge_person_candidates(
        candidates=[
            {
                "name": "Jennifer Brady",
                "projectCount": 0,
                "winCount": 1,
                "projects": [],
                "closeWonOpps": [{"name": "Legacy Win"}],
                "_source": "person_search",
            },
            {
                "name": "Jennifer Brady",
                "projectCount": 4,
                "winCount": 3,
                "projects": [{"name": "Project 1"}, {"name": "Project 2"}],
                "closeWonOpps": [{"name": "Win 1"}, {"name": "Win 2"}, {"name": "Win 3"}],
                "_source": "from_key_buyers",
            },
        ],
        selected={
            "name": "Jennifer Brady",
            "projectCount": 0,
            "winCount": 1,
            "projects": [],
            "closeWonOpps": [{"name": "Legacy Win"}],
            "_source": "person_search",
        },
        title_hints=[],
    )

    assert merged["projectCount"] == 4
    assert merged["winCount"] == 3
    assert len(merged["projects"]) == 2
    assert len(merged["closeWonOpps"]) == 3


def test_resolve_person_transition_merges_sparse_key_buyer_with_richer_person_search() -> None:
    candidates = [
        {
            "name": "Jennifer Brady",
            "title": "Senior Director of Technology Risk",
            "emailAddress": "jennifer.brady@capitalone.com",
            "_source": "from_key_buyers",
            "_company_scope": "from",
            "linked_account_id": "00130000000BYU2AAO",
            "linked_company_name": "Capital One Financial Corporation",
        },
        {
            "name": "Jennifer Brady",
            "title": "Senior Director of Technology Risk",
            "titleExternal": "Senior Director, Technology Risk",
            "location": "McLean, VA",
            "isInSalesforce": True,
            "linkedinUrl": "https://www.linkedin.com/in/jennifer-brady-crisc-3719303",
            "pastJobExperience": ["Bank A"],
            "education": ["University X"],
            "lastUpdated": "2024-09-17",
            "_source": "person_search",
            "_company_scope": "from",
            "linked_account_id": "00130000000BYU2AAO",
            "linked_company_name": "Capital One Financial Corporation",
        },
    ]

    resolution = resolve_person_transition(
        person_name="Jennifer Brady",
        candidates=candidates,
        to_account_id="00130000000BYUIAA4",
        from_account_id="00130000000BYU2AAO",
        to_title_hints=[],
        from_title_hints=["Senior Director of Technology Risk"],
    )

    matched = resolution["matched"]
    assert resolution["match_source"] == "from_key_buyers"
    assert matched["emailAddress"] == "jennifer.brady@capitalone.com"
    assert matched["location"] == "McLean, VA"
    assert matched["isInSalesforce"] is True
    assert matched["titleExternal"] == "Senior Director, Technology Risk"
    assert matched["linkedinUrl"] == "https://www.linkedin.com/in/jennifer-brady-crisc-3719303"
    assert matched["pastJobExperience"] == ["Bank A"]
    assert matched["education"] == ["University X"]
    assert matched["lastUpdated"] == "2024-09-17"


def test_probe_additional_endpoints_uses_har_backed_account_routes() -> None:
    calls: list[tuple[str, dict | None]] = []

    class FakeClient:
        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            calls.append((endpoint, params))
            return {
                "success": True,
                "status_code": 200,
                "data": [{"topic": "Technology Risk"}],
            }

    payloads, warnings = probe_additional_endpoints(
        client=FakeClient(),
        account_id="001-from",
        zoom_info_account_id="9012358",
    )

    assert warnings == []
    assert calls == [
        ("/api/Intent", {"zoomInfoAccountId": "9012358"}),
        ("/api/Scoop", {"zoomInfoAccountId": "9012358"}),
    ]
    assert [payload["endpoint"] for payload in payloads] == ["/api/Intent", "/api/Scoop"]


def test_run_stakeholder_case_uses_har_backed_probe_data_and_person_detail(monkeypatch) -> None:
    to_account = sample_account()
    to_account.update(
        {
            "id": "001-to",
            "name": "Federal National Mortgage Association (Fannie Mae)",
            "zoomInfoAccountId": "72074644",
            "websiteUrl": "www.fanniemae.com",
            "tickerSymbol": "FNMA",
            "shortName": "Fannie Mae",
            "hubId": "hub-to",
            "project": [],
            "allOpportunity": [],
            "keyBuyers": [],
            "protivitiAlumni": [],
            "connectedColleague": [],
        }
    )
    from_account = sample_account()
    from_account.update({"id": "001-from", "zoomInfoAccountId": "9012358"})

    def fake_resolve_account_context(client, company_name, key_person_name, account_id_override, label, required):
        account = to_account if label == "To company" else from_account
        return {
            "resolution": {
                "query": company_name,
                "search_status_code": 200,
                "search_success": True,
                "candidate_count": 1,
                "candidates": [{"accountId": account["id"], "name": account["name"]}],
                "selected_candidate": {"accountId": account["id"], "name": account["name"]},
                "selected_score": 1.0,
                "account_fetch_status_code": 200,
                "resolved_account": True,
                "account_id_override": False,
            },
            "account": account,
            "checks": [],
            "warnings": [],
            "errors": [],
            "auth_failure": False,
        }

    def fake_collect_org_chart_people(client, zoom_info_account_id, department_hint):
        return [], [], []

    class FakeClient:
        def __init__(self) -> None:
            self.endpoint_calls: list[tuple[str, dict | None]] = []

        def search_prospects(self, search_text):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "value": [
                        {
                            "document": {
                                "contactId": "contact-123",
                                "accountId": "001-from",
                                "companyName": "Capital One Financial Corporation",
                                "name": "Jennifer Brady",
                                "title": "Senior Director of Technology Risk",
                                "location": "Mclean, VA, United States",
                            }
                        }
                    ]
                },
            }

        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            self.endpoint_calls.append((endpoint, params))

            if endpoint == "/api/Intent":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": [
                        {
                            "Topic": "Technology Risk",
                            "AudienceStrength": "High",
                            "SignalDate": "2026-03-01",
                        }
                    ],
                }

            if endpoint == "/api/Scoop":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": [
                        {
                            "Category": "Profile Update",
                            "Description": "Viewed Jennifer Brady profile",
                            "PublishedDate": "2026-03-01",
                        }
                    ],
                }

            if endpoint == "/api/prospects/contact-123":
                return {
                    "success": True,
                    "status_code": 200,
                    "data": {
                        "ContactId": "contact-123",
                        "FirstName": "Jennifer",
                        "LastName": "Brady",
                        "Title": "Senior Director of Technology Risk",
                        "IsInSalesforce": True,
                        "IsProtivitiAlumni": False,
                        "HasRoberthalfContact": False,
                        "PhotoUrl": "https://img.example.com/jennifer-brady.png",
                        "LastUpdated": "2024-09-17",
                        "PastJobExperience": ["Bank A"],
                        "Education": ["University X"],
                        "ExternalProspectView": {
                            "Title": "Director, Technology Governance",
                            "Phone": "(703) 420-3804",
                            "Education": [],
                        },
                    },
                }

            raise AssertionError(f"Unexpected endpoint {endpoint}")

    client = FakeClient()

    monkeypatch.setattr(stakeholder_payload, "resolve_account_context", fake_resolve_account_context)
    monkeypatch.setattr(stakeholder_payload, "collect_org_chart_people", fake_collect_org_chart_people)

    result = run_stakeholder_case(
        client=client,
        person="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        department_hint="C-Suite",
        from_account_id_override=None,
        to_account_id_override=None,
        research_inputs=None,
        enable_probes=True,
    )

    profile = result["transition_payload"]["person_profile"]
    assert profile["match_status"] == "matched"
    assert profile["last_updated"] == "2024-09-17"
    assert profile["title_external"] == "Director, Technology Governance"
    assert profile["in_salesforce"] is True
    assert profile["protiviti_alumni"] is False
    assert profile["contact_at_robert_half"] is False
    assert profile["photo_url"] == "https://img.example.com/jennifer-brady.png"
    assert profile["phone"] == "(703) 420-3804"
    assert profile["past_job_experience"] == ["Bank A"]
    assert profile["education"] == ["University X"]

    from_optional = result["transition_payload"]["optional_sections"]["from_company"]
    assert from_optional["intent_signals"] == [
        {
            "topic": "Technology Risk",
            "strength": "High",
            "date": "2026-03-01",
            "source": "probe:/api/Intent",
        }
    ]
    assert from_optional["recent_activity"] == [
        {
            "type": "Profile Update",
            "date": "2026-03-01",
            "description": "Viewed Jennifer Brady profile",
            "source": "probe:/api/Scoop",
        }
    ]
    assert ("/api/prospects/contact-123", None) in client.endpoint_calls


def test_parse_person_like_record_preserves_relationship_fields() -> None:
    record = stakeholder_payload.parse_person_like_record(
        {
            "firstName": "Jason",
            "lastName": "Dandridge",
            "title": "Head of Operations",
            "location": "Washington, DC, United States",
            "relationshipOwner": "Ben L",
            "projectCount": 4,
            "projects": [{"name": "Control Environment Assessment"}],
            "closeWonOpps": [{"name": "RCSA Program Development and Implementation"}],
            "connections": [{"employee": {"name": "Ben L"}}],
        }
    )

    assert record is not None
    assert record["relationshipOwner"] == "Ben L"
    assert record["projectCount"] == 4
    assert len(record["projects"]) == 1
    assert len(record["closeWonOpps"]) == 1
    assert len(record["connections"]) == 1


def test_extract_person_search_candidates_preserves_relationship_fields_when_present() -> None:
    candidates = stakeholder_payload.extract_person_search_candidates(
        {
            "value": [
                {
                    "document": {
                        "contactId": "contact-1",
                        "accountId": "001-to",
                        "companyName": "Federal National Mortgage Association (Fannie Mae)",
                        "name": "Jason Dandridge",
                        "title": "Head of Operations",
                        "relationshipOwner": "Ben L",
                        "projectCount": 3,
                        "projects": [{"name": "Controls Review"}],
                        "closeWonOpps": [{"name": "Controls Review"}],
                        "connections": [{"employee": {"name": "Ben L"}}],
                    }
                }
            ]
        }
    )

    assert candidates[0]["relationshipOwner"] == "Ben L"
    assert candidates[0]["projectCount"] == 3
    assert len(candidates[0]["projects"]) == 1
    assert len(candidates[0]["closeWonOpps"]) == 1
    assert len(candidates[0]["connections"]) == 1


def test_summarize_probe_payloads_surfaces_top_level_keys_and_node_paths() -> None:
    summaries = summarize_probe_payloads(
        [
            {
                "endpoint": "/api/userHistory",
                "params": {"accountId": "001-from"},
                "status_code": 200,
                "success": True,
                "data": {
                    "PersonProfile": {
                        "Name": "Jennifer Brady",
                        "PhotoUrl": "https://img.example.com/jennifer-brady.png",
                    },
                    "IntentSignals": [
                        {
                            "Topic": "Technology Risk",
                            "AudienceStrength": "High",
                        }
                    ],
                },
            }
        ]
    )

    assert summaries == [
        {
            "endpoint": "/api/userHistory",
            "status_code": 200,
            "success": True,
            "params": {"accountId": "001-from"},
            "data_type": "dict",
            "top_level_keys": ["IntentSignals", "PersonProfile"],
            "response_kind": "json",
            "data_usable": True,
            "raw_text_length": None,
            "raw_text_preview": None,
            "dict_node_samples": [
                {"path": "$", "keys": ["IntentSignals", "PersonProfile"]},
                {"path": "$.PersonProfile", "keys": ["Name", "PhotoUrl"]},
                {"path": "$.IntentSignals[0]", "keys": ["AudienceStrength", "Topic"]},
            ],
        }
    ]


def test_summarize_probe_payloads_includes_raw_text_preview_when_response_is_plain_text() -> None:
    summaries = summarize_probe_payloads(
        [
            {
                "endpoint": "/api/userHistory",
                "params": {"accountId": "001-from"},
                "status_code": 200,
                "success": True,
                "data": {"raw_text": "<html><body>not json</body></html>"},
            }
        ]
    )

    assert summaries == [
        {
            "endpoint": "/api/userHistory",
            "status_code": 200,
            "success": True,
            "params": {"accountId": "001-from"},
            "data_type": "dict",
            "top_level_keys": ["raw_text"],
            "response_kind": "html",
            "data_usable": False,
            "raw_text_length": 34,
            "raw_text_preview": "<html><body>not json</body></html>",
            "dict_node_samples": [{"path": "$", "keys": ["raw_text"]}],
        }
    ]


def test_probe_additional_endpoints_warns_when_probe_returns_proconnect_html_shell() -> None:
    class FakeClient:
        def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "raw_text": (
                        '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
                        '<link rel="icon" href="/proconnect-logo.png"/></head><body></body></html>'
                    )
                },
            }

    payloads, warnings = probe_additional_endpoints(
        client=FakeClient(),
        account_id="001-from",
        zoom_info_account_id="9012358",
    )

    assert len(payloads) == 2
    assert any("returned ProConnect app HTML instead of JSON" in warning for warning in warnings)
