"""
Tests for compact transition brief formatting.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.bd_schemas import CredentialMatch, MDReport, MDReportOpportunity, Opportunity
from models.transition_schemas import (
    AccountResolution,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.transition_brief_formatter import (
    build_transition_artifacts,
    build_transition_brief,
    format_transition_brief_markdown,
)
from services.transition_playbook_orchestrator import TransitionPlaybookRunResult
from services.transition_prompt_builder import TransitionPromptPackage


def _sample_result() -> TransitionPlaybookRunResult:
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
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate CIO priorities and warm paths at Fannie Mae.",
    )

    deep_research_response = {
        "summary": "Research found multiple likely CIO-era priorities at Fannie Mae.",
        "sections": [
            {
                "title": "Opportunity Scan",
                "content": "Full research section body that should stay out of the default compact brief.",
                "citations": [{"title": "Source A", "url": "https://example.com/a"}],
            }
        ],
        "citations": [{"title": "Source A", "url": "https://example.com/a"}],
        "metadata": {},
    }

    report = MDReport(
        trigger_summary="Transition playbook",
        executive_summary="Compact summary for the MD.",
        generated_at=datetime.now(),
        top_opportunities=[
            MDReportOpportunity(
                opportunity=Opportunity(
                    title="AI governance program",
                    scope="Help establish enterprise AI controls.",
                    confidence="High",
                ),
                validation_status="Validated",
                credentials_lookup_status="Matched",
                credentials=[
                    CredentialMatch(
                        title="AI Governance Transformation",
                        client_challenge="Needed to establish AI governance.",
                        value_provided="Created operating model and controls.",
                        url="https://example.com/cred1",
                    )
                ],
            )
        ],
        recommended_actions=[
            "Reconnect Bernadette Norrington with a CIO transition angle.",
            "Position AI governance as an early executive priority.",
        ],
        lookups_executed_count=1,
        credentials_status_counts={"Matched": 1, "No Match": 0, "Lookup Failed": 0},
    )

    actioning_context = {
        "person_profile": {
            "matched_person": {"name": "Jennifer Brady", "title": "Senior Director of Technology Risk"},
            "title_external": "Director, Technology Governance",
        },
        "from_company_context": {
            "account_team": {
                "account_mdd": {"name": "Bernadette Norrington"},
            },
            "relationship_network": {
                "connected_colleagues": {
                    "items": [{"name": "Bernadette Norrington"}, {"name": "Shawn Marion"}]
                }
            },
        },
        "to_company_context": {
            "relationship_network": {
                "protiviti_alumni": {"items": [{"name": "Jane Alum"}]},
                "connected_colleagues": {"items": [{"name": "Indre Anelauskas"}]},
            }
        },
        "ranked_opportunities_top10": [
            {
                "rank": 1,
                "opportunity": "AI governance program",
                "primary_key_buyer": "Mike Gabbay",
                "stage": "Opportunity Qualified",
            }
        ],
        "warnings": ["Org chart C-Suite/Marketing & Sales failed with status 500."],
    }

    return TransitionPlaybookRunResult(
        preflight=preflight,
        prompt_package=TransitionPromptPackage(
            industry_key="financial_services",
            system_prompt="SYSTEM",
            user_prompt="USER PROMPT",
        ),
        deep_research_response=deep_research_response,
        bd_report=report,
        actioning_context=actioning_context,
    )


def test_build_transition_brief_returns_compact_sections_and_hidden_artifacts() -> None:
    brief = build_transition_brief(_sample_result())

    assert "Jennifer Brady" in brief.transition_summary
    assert "Synthetic" in brief.transition_summary
    assert len(brief.top_opportunities) == 1
    assert len(brief.proof_and_warm_paths) == 1
    assert {artifact.artifact_type for artifact in brief.hidden_artifacts} >= {
        "deep_research_report",
        "proconnect_dossier",
    }


def test_format_transition_brief_markdown_keeps_visible_output_compact() -> None:
    brief = build_transition_brief(_sample_result())

    markdown = format_transition_brief_markdown(brief)

    assert "AI governance program" in markdown
    assert "Recommended Next Actions" in markdown
    assert "Full research section body that should stay out of the default compact brief." not in markdown


def test_build_transition_artifacts_contains_full_research_report_and_proconnect_dossier() -> None:
    artifacts = build_transition_artifacts(_sample_result())

    assert "deep_research_report" in artifacts
    assert "Full research section body that should stay out of the default compact brief." in artifacts["deep_research_report"]
    assert "Bernadette Norrington" in artifacts["proconnect_dossier"]
    assert "Jane Alum" in artifacts["proconnect_dossier"]
