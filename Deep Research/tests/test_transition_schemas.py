"""
Contract tests for Transition Playbook schemas.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.transition_schemas import (  # type: ignore
    AccountResolution,
    HiddenArtifactRef,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    RecommendedAction,
    TransitionBrief,
    TransitionOpportunityCard,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionProofCard,
    TransitionRequest,
)


def _dump(model):
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def test_transition_request_captures_required_fields_and_overrides() -> None:
    request = TransitionRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        synthetic_scenario=True,
        department_hint="C-Suite",
        geography="United States",
        industry_override="financial_services",
        additional_context="Demo scenario for MD review.",
    )

    payload = _dump(request)

    assert payload["person_name"] == "Jennifer Brady"
    assert payload["from_company"] == "Capital One"
    assert payload["to_company"] == "Fannie Mae"
    assert payload["new_role"] == "Chief Information Officer"
    assert payload["synthetic_scenario"] is True
    assert payload["department_hint"] == "C-Suite"
    assert payload["geography"] == "United States"
    assert payload["industry_override"] == "financial_services"
    assert payload["additional_context"] == "Demo scenario for MD review."


def test_transition_preflight_exposes_resolution_state_indicators_and_hypotheses() -> None:
    preflight = TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
        ),
        person_resolution=TransitionPersonResolution(
            requested_name="Jennifer Brady",
            match_status="matched",
            matched_name="Jennifer Brady",
            matched_title="Senior Director of Technology Risk",
            match_source="from_key_buyers",
            direct_person_evidence=True,
        ),
        from_account=AccountResolution(
            company_name="Capital One Financial Corporation",
            resolved=True,
            account_id="00130000000BYU2AAO",
        ),
        to_account=AccountResolution(
            company_name="Federal National Mortgage Association (Fannie Mae)",
            resolved=True,
            account_id="00130000000BYUIAA4",
        ),
        quick_indicators=QuickRelationshipIndicators(
            warm_intro_path_available=True,
            source_worked_before=True,
            destination_worked_before=True,
            source_key_buyer_count=24,
            destination_key_buyer_count=14,
            source_connected_colleague_count=5,
            destination_connected_colleague_count=1,
        ),
        opportunity_hypotheses=[
            OpportunityHypothesis(
                title="Technology governance modernization",
                rationale="Move into CIO scope suggests near-term demand for governance and operating-model support.",
                confidence="High",
            ),
            OpportunityHypothesis(
                title="AI risk and controls program",
                rationale="Role expansion creates executive pressure around AI controls and oversight.",
                confidence="Medium",
            ),
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate likely CIO priorities and Protiviti-suited opportunities at Fannie Mae.",
    )

    payload = _dump(preflight)

    assert payload["person_resolution"]["match_status"] == "matched"
    assert payload["from_account"]["resolved"] is True
    assert payload["to_account"]["resolved"] is True
    assert payload["quick_indicators"]["warm_intro_path_available"] is True
    assert payload["inferred_industry"] == "financial_services"
    assert payload["opportunity_hypotheses"][0]["title"] == "Technology governance modernization"
    assert "CIO priorities" in payload["suggested_research_prompt"]


def test_transition_brief_keeps_compact_sections_and_hidden_artifact_metadata() -> None:
    brief = TransitionBrief(
        transition_summary="Synthetic move validated. Warm path available and prior work exists at both accounts.",
        top_opportunities=[
            TransitionOpportunityCard(
                title="Enterprise technology risk reset",
                why_now="New CIO entry point and open technology risk activity at destination account.",
                role_fit="Direct fit for a CIO modernizing governance and control coverage.",
                confidence="High",
            )
        ],
        proof_and_warm_paths=[
            TransitionProofCard(
                opportunity_title="Enterprise technology risk reset",
                credential_summary="Matched credentials from financial-services technology risk work.",
                warm_path_summary="Bernadette Norrington and one connected colleague provide a warm route.",
                internal_sponsors=["Bernadette Norrington", "Gary Callaghan"],
            )
        ],
        recommended_actions=[
            RecommendedAction(
                title="Brief account leadership",
                owner_hint="Account MD",
                rationale="Warm path exists and opportunity is high-confidence.",
            )
        ],
        hidden_artifacts=[
            HiddenArtifactRef(
                artifact_type="deep_research_report",
                label="View Full Research Report",
                artifact_key="deep-research-full",
            ),
            HiddenArtifactRef(
                artifact_type="proconnect_dossier",
                label="View ProConnect Dossier",
                artifact_key="proconnect-dossier",
            ),
        ],
    )

    payload = _dump(brief)

    assert payload["transition_summary"].startswith("Synthetic move validated")
    assert len(payload["top_opportunities"]) == 1
    assert payload["proof_and_warm_paths"][0]["internal_sponsors"] == [
        "Bernadette Norrington",
        "Gary Callaghan",
    ]
    assert payload["recommended_actions"][0]["title"] == "Brief account leadership"
    assert payload["hidden_artifacts"][0]["artifact_type"] == "deep_research_report"
    assert payload["hidden_artifacts"][1]["artifact_type"] == "proconnect_dossier"
