"""
Tests for runtime ProConnect transition service.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transition_schemas import TransitionRequest
from services.proconnect_transition_service import ProConnectTransitionService


def _sample_transition_case() -> dict:
    return {
        "warnings": ["Org chart Finance/Strategy failed with status 500."],
        "transition_payload": {
            "movement_event": {
                "person_full_name": "Jennifer Brady",
                "from_company": "Capital One",
                "to_company": "Fannie Mae",
                "from_account_id": "00130000000BYU2AAO",
                "to_account_id": "00130000000BYUIAA4",
                "from_account_resolved": True,
                "to_account_resolved": True,
            },
            "person_profile": {
                "person_requested": "Jennifer Brady",
                "match_status": "matched",
                "matched_person": {
                    "name": "Jennifer Brady",
                    "title": "Senior Director of Technology Risk",
                    "source": "from_key_buyers",
                },
                "title_salesforce": "Senior Director of Technology Risk",
                "direct_person_evidence": True,
            },
            "from_company_context": {
                "worked_before": True,
                "prior_relationship_indicators": {
                    "warm_intro_path_available": True,
                    "key_buyer_count": 24,
                },
                "relationship_network": {
                    "connected_colleagues": {
                        "items": [
                            {"name": "A"},
                            {"name": "B"},
                        ]
                    }
                },
                "top_key_buyers": [{"name": "Buyer 1"}, {"name": "Buyer 2"}],
            },
            "to_company_context": {
                "account_context": {
                    "company_name": "Federal National Mortgage Association (Fannie Mae)",
                    "industry": "Financial Services & Real Estate",
                    "worked_before": True,
                },
                "relationship_network": {
                    "warm_intro_path_available": True,
                    "connected_colleagues": {"items": [{"name": "Indre Anelauskas"}]},
                },
                "key_buyers": {
                    "items": [
                        {"name": "Mike Gabbay"},
                        {"name": "Chris Richardson"},
                    ]
                },
                "account_team": {
                    "account_mdd": {"name": "Gary Callaghan"},
                },
            },
            "movement_evidence": {
                "ranked_opportunities_top10": [
                    {
                        "rank": 1,
                        "rank_band": "High",
                        "opportunity": "AI & CoPilot Advisory",
                        "stage": "Potential Opportunity Identified",
                        "primary_key_buyer": "Kathy Memenza",
                    },
                    {
                        "rank": 2,
                        "rank_band": "Medium",
                        "opportunity": "Enterprise First Line Controls Testing Program",
                        "stage": "Client Negotiation / Review",
                        "primary_key_buyer": "Steve Stone",
                    },
                ]
            },
        },
    }


def test_build_preflight_uses_existing_case_runner_and_returns_compact_indicators() -> None:
    calls: list[dict] = []

    def fake_case_runner(**kwargs):
        calls.append(kwargs)
        return _sample_transition_case()

    service = ProConnectTransitionService(client=object(), case_runner=fake_case_runner)
    request = TransitionRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        synthetic_scenario=True,
        department_hint="C-Suite",
    )

    preflight = service.build_preflight(request)

    assert len(calls) == 1
    assert calls[0]["person"] == "Jennifer Brady"
    assert calls[0]["from_company"] == "Capital One"
    assert calls[0]["to_company"] == "Fannie Mae"
    assert calls[0]["department_hint"] == "C-Suite"

    assert preflight.person_resolution.match_status == "matched"
    assert preflight.person_resolution.match_source == "from_key_buyers"
    assert preflight.from_account.resolved is True
    assert preflight.to_account.resolved is True
    assert preflight.quick_indicators.warm_intro_path_available is True
    assert preflight.quick_indicators.source_key_buyer_count == 24
    assert preflight.quick_indicators.source_connected_colleague_count == 2
    assert preflight.quick_indicators.destination_connected_colleague_count == 1
    assert preflight.inferred_industry == "financial_services"
    assert preflight.opportunity_hypotheses[0].title == "AI & CoPilot Advisory"
    assert preflight.person_resolution.match_diagnostics[0].startswith("Matched Jennifer Brady")
    assert "Org chart Finance/Strategy failed with status 500." in preflight.review_diagnostics


def test_build_actioning_context_exposes_deeper_relationship_and_opportunity_context() -> None:
    service = ProConnectTransitionService(
        client=object(),
        case_runner=lambda **_: _sample_transition_case(),
    )
    request = TransitionRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
    )

    context = service.build_actioning_context(request)

    assert context["person_profile"]["match_status"] == "matched"
    assert context["from_company_context"]["prior_relationship_indicators"]["key_buyer_count"] == 24
    assert context["to_company_context"]["account_team"]["account_mdd"]["name"] == "Gary Callaghan"
    assert context["ranked_opportunities_top10"][0]["opportunity"] == "AI & CoPilot Advisory"
    assert context["warnings"] == ["Org chart Finance/Strategy failed with status 500."]


def test_build_preflight_promotes_top_candidate_when_exact_match_is_missing() -> None:
    candidate_case = _sample_transition_case()
    candidate_case["transition_payload"]["person_profile"]["match_status"] = "not_found"
    candidate_case["transition_payload"]["person_profile"]["matched_person"] = None
    candidate_case["transition_payload"]["person_profile"]["candidate_suggestions"] = [
        {
            "name": "Jennifer A Brady",
            "title": "Senior Director of Technology Risk",
            "source": "from_key_buyers",
            "company_scope": "from",
            "linked_account_id": "00130000000BYU2AAO",
            "score": 0.96,
        }
    ]

    service = ProConnectTransitionService(
        client=object(),
        case_runner=lambda **_: candidate_case,
    )
    request = TransitionRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
    )

    preflight = service.build_preflight(request)

    assert preflight.person_resolution.match_status == "candidate"
    assert preflight.person_resolution.matched_name == "Jennifer A Brady"
    assert preflight.person_resolution.match_source == "from_key_buyers"
    assert preflight.person_resolution.candidate_suggestions == [
        "Jennifer A Brady (Senior Director of Technology Risk; from key buyers; score 0.96)"
    ]
