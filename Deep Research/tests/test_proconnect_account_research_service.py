"""
Tests for account-first ProConnect research collection.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.proconnect_account_research_service import ProConnectAccountResearchService  # noqa: E402


class _RichAccountClient:
    def __init__(self) -> None:
        self.endpoint_calls: list[str] = []

    def search_prospects(self, search_text):
        assert search_text == "Fannie Mae"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "value": [
                    {
                        "document": {
                            "accountId": "001-fm",
                            "companyName": "Federal National Mortgage Association (Fannie Mae)",
                            "name": "Federal National Mortgage Association (Fannie Mae)",
                            "companyTicker": "FNMA",
                            "companyUrl": "https://www.fanniemae.com",
                        }
                    }
                ]
            },
        }

    def get_account_by_id(self, account_id: str):
        assert account_id == "001-fm"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": "001-fm",
                "name": "Federal National Mortgage Association (Fannie Mae)",
                "zoomInfoAccountId": "72074644",
                "industry": "Financial Services & Real Estate",
                "websiteUrl": "https://www.fanniemae.com",
                "tickerSymbol": "FNMA",
                "isClient": True,
                "isMSA": True,
                "accountPMO": {
                    "firstName": "Taylor",
                    "lastName": "Reed",
                    "title": "Account PMO",
                    "emailAddress": "taylor.reed@protiviti.com",
                },
                "accountMDD": {
                    "firstName": "Gary",
                    "lastName": "Callaghan",
                    "title": "Managing Director",
                    "emailAddress": "gary.callaghan@protiviti.com",
                },
                "accountExecutive": {
                    "firstName": "Jane",
                    "lastName": "Doe",
                    "title": "Account Executive",
                    "emailAddress": "jane.doe@protiviti.com",
                },
                "protivitiAlumni": [
                    {
                        "firstName": "Alex",
                        "lastName": "Morgan",
                        "title": "Chief Audit Executive",
                    }
                ],
                "connectedColleagues": [
                    {
                        "employee": {
                            "name": "Jordan Lee",
                            "title": "Managing Director",
                            "companyName": "Protiviti",
                        },
                        "lastConnectedMethod": "Call",
                        "lastConnectedDate": "2026-04-01",
                        "numberOfInteractions": 3,
                    }
                ],
                "keyBuyers": [
                    {
                        "firstName": "Kathy",
                        "lastName": "Memenza",
                        "title": "SVP, Enterprise Risk",
                        "emailAddress": "kathy@example.com",
                        "function": "Risk Management",
                        "numberOfWins": 2,
                        "closeWonOpps": [
                            {"opportunityId": "w-1", "name": "Controls Advisory"}
                        ],
                    },
                    {
                        "firstName": "Steve",
                        "lastName": "Stone",
                        "title": "Head of Internal Audit",
                        "function": "Accounting and Finance",
                        "wins": 1,
                    },
                ],
                "project": [
                    {
                        "projectId": "p-1",
                        "name": "Finance Transformation",
                        "projectStatus": "Active",
                        "solution": "Finance Transformation",
                        "endedDate": None,
                        "openDate": "2025-07-01",
                    },
                    {
                        "projectId": "p-2",
                        "name": "SOX Advisory",
                        "projectStatus": "Closed",
                        "solution": "Internal Audit",
                        "endedDate": "2024-12-31",
                    },
                ],
                "numberOfProject": 2,
                "openOpportunity": [
                    {
                        "opportunityId": "o-1",
                        "name": "First Line Controls Testing",
                        "opportunityStage": "Client Negotiation / Review",
                        "opportunityCloseDate": "2026-05-30",
                        "solution": "Internal Audit",
                        "serviceOffering": "Controls Testing",
                        "primaryKeyBuyer": "Kathy Memenza",
                    }
                ],
                "allOpportunity": [
                    {
                        "opportunityId": "o-1",
                        "name": "First Line Controls Testing",
                        "opportunityStage": "Client Negotiation / Review",
                        "opportunityCloseDate": "2026-05-30",
                        "solution": "Internal Audit",
                        "serviceOffering": "Controls Testing",
                        "primaryKeyBuyer": "Kathy Memenza",
                    },
                    {
                        "opportunityId": "w-1",
                        "name": "Controls Advisory",
                        "opportunityStage": "Closed - Won",
                        "opportunityCloseDate": "2025-08-15",
                        "solution": "Risk and Compliance",
                        "serviceOffering": "Advisory",
                        "primaryKeyBuyer": "Kathy Memenza",
                    },
                ],
                "numberOfOpenOpportunity": 1,
                "numberOfAllOpportunity": 2,
            },
        }

    def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
        del zoom_info_account_id, page, size
        if department == "C-Suite" and sfdc_job_function == "Executive":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "employees": [
                        {
                            "id": "exec-1",
                            "firstName": "Priscilla",
                            "lastName": "Almodovar",
                            "title": "Chief Executive Officer",
                            "department": "C-Suite",
                        }
                    ]
                },
            }
        if department == "Finance" and sfdc_job_function == "Accounting and Finance":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "employees": [
                        {
                            "id": "fin-1",
                            "firstName": "Chris",
                            "lastName": "Richardson",
                            "title": "Chief Audit Executive",
                            "department": "Finance",
                        }
                    ]
                },
            }
        return {"success": True, "status_code": 200, "data": {"employees": []}}

    def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
        del params, retry_on_5xx, retry_delay_seconds, stop_on_auth
        self.endpoint_calls.append(endpoint)
        if endpoint == "/api/Intent":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "signals": [
                        {
                            "intentTopic": "Controls modernization",
                            "intentStrength": "High",
                            "intentDate": "2026-04-01",
                        }
                    ]
                },
            }
        if endpoint == "/api/Scoop":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "items": [
                        {
                            "headlineType": "Hiring",
                            "date": "2026-03-18",
                            "description": "Expanded enterprise risk hiring.",
                        }
                    ]
                },
            }
        raise AssertionError(f"Unexpected endpoint {endpoint}")


class _ThinCoverageClient:
    def search_prospects(self, search_text):
        assert search_text == "TargetCo"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "value": [
                    {
                        "document": {
                            "accountId": "001-target",
                            "companyName": "TargetCo",
                            "name": "TargetCo",
                        }
                    }
                ]
            },
        }

    def get_account_by_id(self, account_id: str):
        assert account_id == "001-target"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": "001-target",
                "name": "TargetCo",
                "industry": "Technology",
                "websiteUrl": "https://target.example.com",
                "numberOfOpenOpportunity": 0,
                "numberOfAllOpportunity": 0,
                "numberOfProject": 0,
                "keyBuyers": [],
                "project": [],
                "allOpportunity": [],
            },
        }

    def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
        raise AssertionError("Org chart should not be called when zoomInfoAccountId is missing")

    def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
        raise AssertionError("Probe endpoints should not be called when zoomInfoAccountId is missing")


class _AllOpportunityFallbackClient:
    def search_prospects(self, search_text):
        assert search_text == "FallbackCo"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "value": [
                    {
                        "document": {
                            "accountId": "001-fallback",
                            "companyName": "FallbackCo",
                            "name": "FallbackCo",
                        }
                    }
                ]
            },
        }

    def get_account_by_id(self, account_id: str):
        assert account_id == "001-fallback"
        return {
            "success": True,
            "status_code": 200,
            "data": {
                "id": "001-fallback",
                "name": "FallbackCo",
                "isClient": None,
                "isMSA": None,
                "project": [],
                "numberOfProject": 0,
                "openOpportunity": [],
                "allOpportunity": [
                    {
                        "opportunityId": "open-1",
                        "name": "Enterprise Controls Refresh",
                        "opportunityStage": "Qualification",
                    },
                    {
                        "opportunityId": "closed-1",
                        "name": "Closed Deal",
                        "opportunityStage": "Closed - Won",
                    },
                ],
            },
        }

    def get_org_chart(self, zoom_info_account_id, department, sfdc_job_function, page=None, size=None):
        raise AssertionError("Org chart should not be called when zoomInfoAccountId is missing")

    def get_endpoint(self, endpoint, params=None, retry_on_5xx=0, retry_delay_seconds=0.25, stop_on_auth=False):
        raise AssertionError("Probe endpoints should not be called when zoomInfoAccountId is missing")


def test_collect_account_research_shapes_company_name_only_resolution_into_account_first_output() -> None:
    service = ProConnectAccountResearchService(client=_RichAccountClient())

    result = service.collect_account_research("Fannie Mae", department_hint="Finance")

    assert set(result) == {
        "account_resolution",
        "account_status",
        "known_protiviti_team",
        "known_relationships",
        "known_buyers",
        "open_opportunities",
        "past_work",
        "org_chart_coverage",
        "optional_internal_signals",
        "coverage_gaps",
        "diagnostics",
    }

    assert result["account_resolution"]["query"] == "Fannie Mae"
    assert result["account_resolution"]["resolved"] is True
    assert result["account_resolution"]["account_id"] == "001-fm"
    assert result["account_resolution"]["company_name"] == "Federal National Mortgage Association (Fannie Mae)"
    assert result["account_resolution"]["selected_candidate"]["score"] >= 0.95

    assert result["account_status"]["worked_before"] is True
    assert result["account_status"]["account_activity_status"] == "active"
    assert result["account_status"]["is_client"] is True
    assert result["account_status"]["is_msa"] is True

    assert result["known_protiviti_team"]["account_mdd"]["name"] == "Gary Callaghan"
    assert result["known_relationships"]["warm_intro_path_available"] is True
    assert result["known_relationships"]["relationship_routes"] == [
        "protiviti_alumni",
        "connected_colleagues",
    ]
    assert result["known_buyers"][0]["name"] == "Kathy Memenza"
    assert result["open_opportunities"] == [
        {
            "opportunity_id": "o-1",
            "opportunity_key": None,
            "opportunity": "First Line Controls Testing",
            "close_date": "2026-05-30",
            "created_date": None,
            "md_d": None,
            "primary_key_buyer": "Kathy Memenza",
            "primary_key_buyer_id": None,
            "solution": "Internal Audit",
            "solution_segment": None,
            "service_name": "Controls Testing",
            "stage": "Client Negotiation / Review",
            "em": None,
            "is_confidential": None,
            "win_loss_explanation": None,
            "reason_for_loss": None,
        }
    ]
    assert result["past_work"]["total_projects"] == 2
    assert result["past_work"]["closed_won_opportunities"][0]["opportunity_id"] == "w-1"
    assert result["org_chart_coverage"]["available"] is True
    assert result["org_chart_coverage"]["people_count"] == 2
    assert result["org_chart_coverage"]["focus_department"] == "Finance"
    assert result["optional_internal_signals"]["intent_signals"][0]["topic"] == "Controls modernization"
    assert result["optional_internal_signals"]["recent_activity"][0]["description"] == "Expanded enterprise risk hiring."
    assert result["coverage_gaps"] == []
    assert result["diagnostics"]["warnings"] == []


def test_collect_account_research_adds_caveats_instead_of_overclaiming_when_coverage_is_thin() -> None:
    service = ProConnectAccountResearchService(client=_ThinCoverageClient())

    result = service.collect_account_research("TargetCo")

    assert result["account_resolution"]["resolved"] is True
    assert result["account_status"]["account_activity_status"] == "unknown"
    assert result["account_status"]["worked_before"] is False
    assert result["known_relationships"]["warm_intro_path_available"] is False
    assert result["known_relationships"]["relationship_routes"] == []
    assert result["known_buyers"] == []
    assert result["open_opportunities"] == []
    assert result["past_work"]["total_projects"] == 0
    assert result["org_chart_coverage"]["available"] is False
    assert result["org_chart_coverage"]["people_count"] == 0
    assert result["optional_internal_signals"] is None
    assert "Org chart unavailable until zoomInfoAccountId is present." in result["coverage_gaps"]
    assert "Optional internal signals were not collected because zoomInfoAccountId is missing." in result["coverage_gaps"]
    assert result["diagnostics"]["warnings"] == ["Missing zoomInfoAccountId; org chart unavailable."]


def test_collect_account_research_preserves_unknown_client_and_msa_state() -> None:
    service = ProConnectAccountResearchService(client=_AllOpportunityFallbackClient())

    result = service.collect_account_research("FallbackCo")

    assert result["account_status"]["is_client"] is None
    assert result["account_status"]["is_msa"] is None
    assert result["account_status"]["summary"] == "No known ProConnect work found."


def test_collect_account_research_falls_back_to_all_opportunities_when_open_list_is_empty() -> None:
    service = ProConnectAccountResearchService(client=_AllOpportunityFallbackClient())

    result = service.collect_account_research("FallbackCo")

    assert result["open_opportunities"] == [
        {
            "opportunity_id": "open-1",
            "opportunity_key": None,
            "opportunity": "Enterprise Controls Refresh",
            "close_date": None,
            "created_date": None,
            "md_d": None,
            "primary_key_buyer": None,
            "primary_key_buyer_id": None,
            "solution": None,
            "solution_segment": None,
            "service_name": None,
            "stage": "Qualification",
            "em": None,
            "is_confidential": None,
            "win_loss_explanation": None,
            "reason_for_loss": None,
        }
    ]
