"""
Tests for transition form mapping helpers.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transition_form_mapper import (  # type: ignore
    TRANSITION_REQUEST_SESSION_KEY,
    build_transition_request_from_form_response,
    persist_transition_request_session,
)


class FakeSession(dict):
    def set(self, key, value):
        self[key] = value

    def get(self, key, default=None):
        return super().get(key, default)


def test_required_fields_map_into_transition_request() -> None:
    request = build_transition_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "synthetic_scenario": True,
        }
    )

    assert request.person_name == "Jennifer Brady"
    assert request.from_company == "Capital One"
    assert request.to_company == "Fannie Mae"
    assert request.new_role == "Chief Information Officer"
    assert request.synthetic_scenario is True


def test_nested_output_payload_maps_into_transition_request() -> None:
    request = build_transition_request_from_form_response(
        {
            "submitted": True,
            "output": {
                "person_name": "Jennifer Brady",
                "from_company": "Capital One",
                "to_company": "Fannie Mae",
                "new_role": "Chief Information Officer",
                "synthetic_scenario": True,
            },
        }
    )

    assert request.person_name == "Jennifer Brady"
    assert request.from_company == "Capital One"
    assert request.to_company == "Fannie Mae"
    assert request.new_role == "Chief Information Officer"


def test_advanced_options_are_optional() -> None:
    request = build_transition_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
        }
    )

    assert request.department_hint is None
    assert request.geography is None
    assert request.industry_override is None
    assert request.additional_context is None


def test_blank_required_fields_raise_validation_error() -> None:
    try:
        build_transition_request_from_form_response(
            {
                "submitted": True,
                "output": {
                    "person_name": "",
                    "from_company": "",
                    "to_company": "",
                    "new_role": "",
                },
            }
        )
    except Exception as exc:
        message = str(exc)
        assert "person_name" in message or "must not be blank" in message
    else:
        raise AssertionError("Expected blank required fields to fail validation")


def test_synthetic_scenario_flag_persists_in_session() -> None:
    session = FakeSession()
    request = build_transition_request_from_form_response(
        {
            "person_name": "Jennifer Brady",
            "from_company": "Capital One",
            "to_company": "Fannie Mae",
            "new_role": "Chief Information Officer",
            "synthetic_scenario": True,
            "department_hint": "C-Suite",
        }
    )

    persist_transition_request_session(session, request)

    stored = session.get(TRANSITION_REQUEST_SESSION_KEY)
    assert stored["synthetic_scenario"] is True
    assert stored["department_hint"] == "C-Suite"
