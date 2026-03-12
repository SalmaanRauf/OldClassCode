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
    resolve_person_transition,
    run_stakeholder_case,
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


def test_run_stakeholder_case_uses_from_probe_data_for_person_and_relationships(monkeypatch) -> None:
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

    def fake_probe_additional_endpoints(client, account_id, zoom_info_account_id):
        if account_id != "001-from":
            return [], []

        return (
            [
                {
                    "endpoint": "/api/userHistory",
                    "params": {"accountId": account_id},
                    "status_code": 200,
                    "success": True,
                    "data": {
                        "personProfile": {
                            "name": "Jennifer Brady",
                            "titleExternal": "Senior Director, Technology Risk",
                            "isInSalesforce": True,
                            "isProtivitiAlumni": False,
                            "hasRoberthalfContact": False,
                            "photoUrl": "https://img.example.com/jennifer-brady.png",
                            "lastUpdated": "2024-09-17",
                        },
                        "recentActivities": [
                            {
                                "activityType": "Profile View",
                                "activityDate": "2026-03-01",
                                "description": "Viewed Jennifer Brady profile",
                            }
                        ],
                        "intentSignals": [
                            {
                                "topic": "Technology Risk",
                                "intentStrength": "High",
                                "intentDate": "2026-03-01",
                            }
                        ],
                        "internalConnections": [
                            {
                                "name": "Taylor Smith",
                                "title": "Managing Director, R&C-Risk, New York Office",
                                "lastConnected": "Other, Oct 2023",
                                "numberOfInteractions": 1,
                            }
                        ],
                    },
                }
            ],
            [],
        )

    class FakeClient:
        def search_prospects(self, search_text):
            return {"success": True, "status_code": 200, "data": {"value": []}}

    monkeypatch.setattr(stakeholder_payload, "resolve_account_context", fake_resolve_account_context)
    monkeypatch.setattr(stakeholder_payload, "collect_org_chart_people", fake_collect_org_chart_people)
    monkeypatch.setattr(stakeholder_payload, "probe_additional_endpoints", fake_probe_additional_endpoints)

    result = run_stakeholder_case(
        client=FakeClient(),
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
    assert profile["title_external"] == "Senior Director, Technology Risk"
    assert profile["in_salesforce"] is True
    assert profile["protiviti_alumni"] is False
    assert profile["contact_at_robert_half"] is False
    assert profile["photo_url"] == "https://img.example.com/jennifer-brady.png"

    from_relationships = result["transition_payload"]["from_company_context"]["relationship_network"]
    assert {
        "name": "Taylor Smith",
        "employer": None,
        "title": "Managing Director, R&C-Risk, New York Office",
        "last_connected_method": "Other",
        "last_connected_date": "Oct 2023",
        "number_of_interactions": 1,
    } in from_relationships["connected_colleagues"]["items"]

    from_optional = result["transition_payload"]["optional_sections"]["from_company"]
    assert from_optional["intent_signals"] == [
        {
            "topic": "Technology Risk",
            "strength": "High",
            "date": "2026-03-01",
            "source": "probe:/api/userHistory",
        }
    ]
    assert from_optional["recent_activity"] == [
        {
            "type": "Profile View",
            "date": "2026-03-01",
            "description": "Viewed Jennifer Brady profile",
            "source": "probe:/api/userHistory",
        }
    ]
