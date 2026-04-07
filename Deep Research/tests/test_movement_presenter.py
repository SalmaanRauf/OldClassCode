"""
Tests for movement presenter payloads.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.movement_schemas import (  # noqa: E402
    MovementAction,
    MovementBriefRequest,
    MovementBrief,
    MovementCredentialReference,
    MovementCredentialsProof,
    MovementEvidence,
    MovementLeverageSummary,
    MovementRecord,
)
from models.transition_schemas import (  # noqa: E402
    AccountResolution,
    OpportunityHypothesis,
    QuickRelationshipIndicators,
    TransitionPersonResolution,
    TransitionPreflight,
    TransitionRequest,
)
from services.movement_presenter import (  # noqa: E402
    ACTION_ADJUST_MOVEMENT,
    ACTION_EDIT_MOVEMENT_PROMPT,
    ACTION_RUN_MOVEMENT_RESEARCH,
    ACTION_VIEW_MOVEMENT_PROMPT,
    MOVEMENT_TABLE_COLUMNS,
    build_movement_brief_payload,
    build_movement_form_props,
    build_movement_preflight_review,
)
from services.movement_prompt_builder import MovementPromptPackage  # noqa: E402


def _movement(index: int, *, with_proof: bool = False) -> MovementRecord:
    leverage = MovementLeverageSummary(
        known=index % 2 == 0,
        worked_with=index % 3 == 0,
        project_count=index,
        win_count=index // 2,
        relationship_owner="Ben L." if index < 4 else None,
        person_match_status="matched" if index < 4 else "unmatched",
    )
    proof = None
    if with_proof:
        proof = MovementCredentialsProof(
            lookup_status="Matched",
            summary="Existing delivery with adjacent control team.",
            matched_credentials=[
                MovementCredentialReference(
                    title="Controls Transformation Program",
                    url="https://example.com/credential",
                    why_relevant="Relevant to technology controls and operating-model uplift.",
                )
            ],
        )

    return MovementRecord(
        person_name=f"Person {index + 1}",
        target_company="Capital One",
        previous_role=f"Previous Role {index + 1}",
        new_role=f"New Role {index + 1}",
        movement_type="Promoted" if index % 2 == 0 else "Joined",
        category="BUYER" if index % 2 == 0 else "EXEC",
        company_context="internal" if index % 2 == 0 else "inbound",
        evidence=MovementEvidence(
            evidence_quote=f"Person {index + 1} moved into a new role.",
            source_url=f"https://example.com/{index + 1}",
            source_title=f"Source {index + 1}",
            source_marker=f"S{index + 1}",
            corroborated=index < 2,
            confidence_label="High" if index < 2 else "Medium",
        ),
        leverage=leverage if index < 6 else None,
        credentials_proof=proof,
    )


def _brief(movement_rows, where_to_act, signal_summary=None):
    model_construct = getattr(MovementBrief, "model_construct", None)
    if model_construct is None:
        model_construct = MovementBrief.construct
    return model_construct(
        executive_summary="Executive Summary text.",
        signal_summary=signal_summary or [
            "Account pressure is concentrated in governance and operating model change.",
            "People movement is strongest at the target account.",
            "Buyer movement creates re-engagement scope.",
            "Executive movement creates governance scope.",
            "Trailing context that should be trimmed.",
        ],
        movement_rows=movement_rows,
        where_to_act=where_to_act,
        takeaway="Move first on the strongest movers and validate adjacent scope.",
    )


def _request() -> MovementBriefRequest:
    return MovementBriefRequest(
        person_name="Jennifer Brady",
        from_company="Capital One",
        to_company="Fannie Mae",
        new_role="Chief Information Officer",
        lookback_days=180,
        synthetic_scenario=True,
        geography="United States",
        industry_override="financial_services",
        additional_context="POC demo scenario",
    )


def _preflight() -> TransitionPreflight:
    return TransitionPreflight(
        request=TransitionRequest(
            person_name="Jennifer Brady",
            from_company="Capital One",
            to_company="Fannie Mae",
            new_role="Chief Information Officer",
            synthetic_scenario=True,
            industry_override="financial_services",
            additional_context="POC demo scenario",
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
                title="AI governance program",
                rationale="CIO transition increases pressure around AI oversight.",
                confidence="High",
            )
        ],
        inferred_industry="financial_services",
        suggested_research_prompt="Investigate executive and buyer movement at Fannie Mae over the last 180 days.",
    )


def test_build_movement_form_props_trims_and_defaults():
    props = build_movement_form_props(
        industry_options=[{"value": "financial_services", "label": "Financial Services"}],
        person_name="  Jennifer Brady  ",
        from_company="  Capital One  ",
        to_company="  Fannie Mae  ",
        new_role="  Chief Information Officer  ",
        lookback_days=365,
        synthetic_scenario=False,
        industry_override="  general  ",
        geography="  United States  ",
        additional_context="  Focus on buyer movement  ",
        show_advanced=True,
    )

    assert props["title"] == "Build a People Movement Brief"
    assert props["description"].startswith("Validate the move")
    assert props["person_name"] == "Jennifer Brady"
    assert props["from_company"] == "Capital One"
    assert props["to_company"] == "Fannie Mae"
    assert props["new_role"] == "Chief Information Officer"
    assert props["lookback_days"] == 365
    assert props["synthetic_scenario"] is False
    assert props["industry_override"] == "general"
    assert props["geography"] == "United States"
    assert props["additional_context"] == "Focus on buyer movement"
    assert props["show_advanced"] is True
    assert props["industry_options"] == [{"value": "financial_services", "label": "Financial Services"}]
    assert props["primary_cta_label"] == "Generate Research Plan"
    assert props["secondary_cta_label"] == "Cancel"
    assert props["scan_hint"].startswith("Start from the named move")


def test_build_movement_preflight_review_shows_move_context_and_prompt_actions():
    payload = build_movement_preflight_review(
        _request(),
        _preflight(),
        MovementPromptPackage(
            industry_key="financial_services",
            system_prompt="FS prompt",
            user_prompt="Generated move prompt.",
        ),
        run_id="run-123",
    )

    assert "People Movement Brief Review" in payload["content"]
    assert "click `Run Research` to start Deep Research" in payload["content"]
    assert "Jennifer Brady" in payload["content"]
    assert "Capital One -> Fannie Mae" in payload["content"]
    assert "180 days" in payload["content"]
    assert "Synthetic" in payload["content"]
    assert "AI governance program" in payload["content"]
    assert payload["actions"] == [
        {"name": ACTION_RUN_MOVEMENT_RESEARCH, "label": "Run Research", "payload": {"run_id": "run-123", "mode": "movement"}},
        {"name": ACTION_EDIT_MOVEMENT_PROMPT, "label": "Edit Prompt", "payload": {"run_id": "run-123", "mode": "movement"}},
        {"name": ACTION_ADJUST_MOVEMENT, "label": "Adjust Movement", "payload": {"run_id": "run-123", "mode": "movement"}},
    ]
    assert payload["view_prompt_action"]["name"] == ACTION_VIEW_MOVEMENT_PROMPT
    assert payload["view_prompt_action"]["payload"] == {"run_id": "run-123", "mode": "movement"}


def test_build_movement_preflight_review_surfaces_match_and_review_diagnostics():
    preflight = _preflight()
    preflight.person_resolution.match_status = "candidate"
    preflight.person_resolution.match_diagnostics = [
        "No exact account-scoped match. Closest candidate is Jennifer A Brady via from key buyers (score 0.96)."
    ]
    preflight.person_resolution.candidate_suggestions = [
        "Jennifer A Brady (Senior Director of Technology Risk; from key buyers; score 0.96)"
    ]
    preflight.review_diagnostics = [
        "Source account lookup did not resolve cleanly for Capital One; using raw company text."
    ]

    payload = build_movement_preflight_review(
        _request(),
        preflight,
        MovementPromptPackage(
            industry_key="financial_services",
            system_prompt="FS prompt",
            user_prompt="Generated move prompt.",
        ),
        run_id="run-123",
    )

    content = payload["content"]
    assert "Match diagnostics" in content
    assert "Closest candidate is Jennifer A Brady" in content
    assert "Candidate suggestions" in content
    assert "Review diagnostics" in content


def test_build_movement_brief_payload_caps_visible_rows_and_actions_and_keeps_detail_content():
    movement_rows = [_movement(index, with_proof=(index == 0)) for index in range(12)]
    where_to_act = [
        MovementAction(
            action_posture="Immediate Re-engagement",
            person_name=f"Person {index + 1}",
            likely_play=f"Likely play {index + 1}",
            why_now=f"Why now {index + 1}",
            relationship_owner="Ben L." if index == 0 else None,
        )
        for index in range(4)
    ]

    payload = build_movement_brief_payload(
        _brief(movement_rows, where_to_act),
        request=_request(),
        preflight=_preflight(),
        person_details_by_name={
            "Person 1": {
                "name": "Person 1",
                "title": "Chief Risk Officer",
                "location": "New York",
                "linkedin_url": "https://linkedin.com/in/person-1",
                "internal_connections": ["Ben L.", "Dana R.", "Morgan T."],
            }
        },
        row_action_context_by_row_id={
            "movement-row-4": {
                "action_posture": "Expansion Opportunity",
                "action_summary": "Row-specific expansion play for a non-top-3 mover.",
            }
        },
        row_action_context_by_person_name={
            "Person 6": {
                "action_posture": "Monitor",
                "action_summary": "Person-keyed monitoring note.",
            }
        },
    )

    assert payload["table_columns"] == MOVEMENT_TABLE_COLUMNS
    assert MOVEMENT_TABLE_COLUMNS[7] == "# Current Projects"
    assert len(payload["movement_rows"]) == 12
    assert len(payload["where_to_act"]) == 3
    assert payload["stats"]["visible_rows"] == 12
    assert payload["stats"]["actions"] == 3
    assert payload["stats"]["exec_rows"] == 6
    assert payload["stats"]["buyer_rows"] == 6
    assert payload["signal_summary"] == [
        "Account pressure is concentrated in governance and operating model change.",
        "People movement is strongest at the target account.",
        "Buyer movement creates re-engagement scope.",
        "Executive movement creates governance scope.",
    ]
    assert payload["move_summary"]["person_name"] == "Jennifer Brady"
    assert payload["move_summary"]["from_company"] == "Capital One Financial Corporation"
    assert payload["move_summary"]["to_company"] == "Federal National Mortgage Association (Fannie Mae)"
    assert payload["move_summary"]["new_role"] == "Chief Information Officer"
    assert payload["move_summary"]["lookback_days"] == 180
    assert payload["move_summary"]["synthetic_scenario"] is True
    assert payload["move_summary"]["warm_intro_path_available"] is True
    assert payload["move_summary"]["source_worked_before"] is True
    assert payload["move_summary"]["destination_worked_before"] is True
    assert payload["destination_account_opportunity_context"] == [
        {
            "title": "AI governance program",
            "confidence": "High",
            "rationale": "CIO transition increases pressure around AI oversight.",
        }
    ]
    assert payload["movement_rows"][0]["signal"] == "BUYER"
    assert payload["movement_rows"][0]["has_credential_proof"] is True
    assert payload["movement_rows"][0]["has_person_detail"] is True
    assert payload["movement_rows"][0]["relationship_owner"] == "Ben L."
    assert payload["movement_rows"][0]["action_summary"] == "Likely play 1"
    assert payload["movement_rows"][3]["action_posture"] == "Expansion Opportunity"
    assert payload["movement_rows"][3]["action_summary"] == "Row-specific expansion play for a non-top-3 mover."
    assert payload["movement_rows"][5]["action_posture"] == "Monitor"
    assert payload["movement_rows"][5]["action_summary"] == "Person-keyed monitoring note."
    assert "movement-row-1" in payload["row_details_by_id"]

    detail = payload["row_details_by_id"]["movement-row-1"]
    assert detail["evidence_quote"] == "Person 1 moved into a new role."
    assert detail["source_url"] == "https://example.com/1"
    assert detail["source_title"] == "Source 1"
    assert "source_marker" not in detail
    assert detail["internal_connections"] == ["Ben L.", "Dana R.", "Morgan T."]
    assert detail["credential_summary"] == "Existing delivery with adjacent control team."
    assert detail["lookup_status"] == "Matched"
    assert detail["matched_credentials"] == [
        {
            "title": "Controls Transformation Program",
            "url": "https://example.com/credential",
            "why_relevant": "Relevant to technology controls and operating-model uplift.",
        }
    ]
    assert detail["person_detail"] == {
        "name": "Person 1",
        "title": "Chief Risk Officer",
        "location": "New York",
        "linkedin_url": "https://linkedin.com/in/person-1",
    }
    assert detail["action_posture"] == "Immediate Re-engagement"
    assert detail["action_summary"] == "Likely play 1"
    assert payload["where_to_act"][0]["relationship_owner"] == "Ben L."


def test_build_movement_brief_payload_keeps_all_rows_and_three_actions():
    movement_rows = [_movement(index) for index in range(12)]
    where_to_act = [
        MovementAction(
            action_posture="Expansion Opportunity",
            person_name=f"Person {index + 1}",
            likely_play=f"Likely play {index + 1}",
            why_now=f"Why now {index + 1}",
            relationship_owner=None,
        )
        for index in range(5)
    ]

    payload = build_movement_brief_payload(
        _brief(movement_rows, where_to_act),
        request=_request(),
        preflight=_preflight(),
    )

    assert len(payload["movement_rows"]) == 12
    assert len(payload["row_details_by_id"]) == 12
    assert len(payload["where_to_act"]) == 3
    assert len(payload["destination_account_opportunity_context"]) == 1
    assert payload["movement_rows"][-1]["row_id"] == "movement-row-12"
    assert payload["where_to_act"][-1]["person_name"] == "Person 3"


def test_build_movement_brief_payload_prepends_named_mover_board_row_from_preflight_context():
    movement_rows = [_movement(index) for index in range(3)]
    payload = build_movement_brief_payload(
        _brief(movement_rows, []),
        request=_request(),
        preflight=_preflight(),
        named_mover_context={
            "person_profile": {
                "direct_person_evidence": True,
                "relationship_owner": "Bernadette Norrington",
                "project_count": 4,
                "win_count": 2,
                "claim_policy_note": "Direct person-level evidence found in ProConnect; person-level claim allowed.",
                "matched_person": {
                    "name": "Jennifer Brady",
                    "title": "Senior Director of Technology Risk",
                    "company_scope": "from",
                },
            },
            "from_company_context": {
                "account_team": {
                    "account_executive": {"name": "Bernadette Norrington"},
                },
                "relationship_network": {
                    "connected_colleagues": {"items": [{"name": "Bernadette Norrington"}]},
                    "protiviti_alumni": {"items": []},
                },
            },
            "to_company_context": {
                "relationship_network": {
                    "connected_colleagues": {"items": []},
                    "protiviti_alumni": {"items": []},
                }
            },
            "named_mover_credentials_proof": {
                "lookup_status": "Matched",
                "summary": "Matched credentials: Technology Controls Refresh.",
                "matched_credentials": [
                    {
                        "title": "Technology Controls Refresh",
                        "url": "https://example.com/named-mover-credential",
                        "why_relevant": "Fits a new FS technology leader focused on controls modernization.",
                    }
                ],
            },
        },
    )

    assert payload["movement_rows"][0]["person_name"] == "Jennifer Brady"
    assert payload["movement_rows"][0]["previous_role"] == "Senior Director of Technology Risk"
    assert payload["movement_rows"][0]["new_role"] == "Chief Information Officer"
    assert payload["movement_rows"][0]["known"] is True
    assert payload["movement_rows"][0]["worked_with"] is True
    assert payload["movement_rows"][0]["project_count"] == 4
    assert payload["movement_rows"][0]["win_count"] == 2
    assert payload["movement_rows"][0]["relationship_owner"] == "Bernadette Norrington"
    assert payload["movement_rows"][0]["has_credential_proof"] is True
    assert payload["movement_rows"][0]["is_focus_move"] is True

    detail = payload["row_details_by_id"]["movement-row-1"]
    assert detail["source_title"] == "Scenario input + ProConnect preflight"
    assert detail["source_url"] is None
    assert detail["person_detail"]["match_scope"] == "from"
    assert detail["lookup_status"] == "Matched"
    assert detail["internal_connections"] == ["Bernadette Norrington"]
    assert detail["matched_credentials"][0]["why_relevant"] == (
        "Fits a new FS technology leader focused on controls modernization."
    )


def test_build_movement_brief_payload_named_mover_uses_list_evidence_when_counts_are_sparse():
    payload = build_movement_brief_payload(
        _brief([], []),
        request=_request(),
        preflight=_preflight(),
        named_mover_context={
            "person_profile": {
                "direct_person_evidence": True,
                "relationship_owner": "Bernadette Norrington",
                "project_count": 0,
                "win_count": 1,
                "projects": [
                    {"name": "Technology Controls Refresh"},
                    {"name": "Cyber Risk Remediation"},
                    {"name": "Identity Access Uplift"},
                ],
                "matched_person": {
                    "name": "Jennifer Brady",
                    "title": "Senior Director of Technology Risk",
                    "company_scope": "from",
                    "projects": [
                        {"name": "Technology Controls Refresh"},
                        {"name": "Cyber Risk Remediation"},
                        {"name": "Identity Access Uplift"},
                    ],
                    "closeWonOpps": [
                        {"name": "IA Co-source"},
                        {"name": "Controls Testing"},
                    ],
                },
            },
            "from_company_context": {
                "account_team": {
                    "account_executive": {"name": "Bernadette Norrington"},
                },
                "relationship_network": {
                    "connected_colleagues": {"items": [{"name": "Bernadette Norrington"}]},
                    "protiviti_alumni": {"items": []},
                },
                "top_key_buyers": [
                    {
                        "name": "Jennifer Brady",
                        "wins_5y": 2,
                    }
                ],
            },
            "to_company_context": {
                "relationship_network": {
                    "connected_colleagues": {"items": []},
                    "protiviti_alumni": {"items": []},
                }
            },
        },
        footer_actions=[
            {"name": "movement_new_scan", "label": "Start New Scan", "payload": {"mode": "movement"}},
        ],
    )

    assert payload["movement_rows"][0]["project_count"] == 3
    assert payload["movement_rows"][0]["win_count"] == 2
    assert payload["footer_actions"][0]["label"] == "Start New Scan"
