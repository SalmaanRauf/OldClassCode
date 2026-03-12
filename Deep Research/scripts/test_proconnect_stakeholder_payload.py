from __future__ import annotations

import sys
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from proconnect_stakeholder_payload import (  # noqa: E402
    build_account_context,
    build_from_company_context_lite,
    build_key_buyers_section,
    build_opportunities_section,
    build_person_profile_transition,
    build_projects_section,
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
