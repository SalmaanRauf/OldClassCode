"""
Helpers for mapping Chainlit transition-form submissions into workflow models.
"""
from __future__ import annotations

from typing import Any, Dict

from models.transition_schemas import TransitionRequest


TRANSITION_REQUEST_SESSION_KEY = "transition_request"
TRANSITION_PREFLIGHT_SESSION_KEY = "transition_preflight"
TRANSITION_PROMPT_SESSION_KEY = "transition_prompt"
TRANSITION_PROMPT_OVERRIDE_SESSION_KEY = "transition_prompt_override"
TRANSITION_ARTIFACTS_SESSION_KEY = "transition_artifacts"
TRANSITION_EDIT_PENDING_SESSION_KEY = "transition_edit_pending"


def build_transition_request_from_form_response(response: Dict[str, Any]) -> TransitionRequest:
    """Map CustomElement response fields into a TransitionRequest."""
    return TransitionRequest(
        person_name=str(response.get("person_name") or "").strip(),
        from_company=str(response.get("from_company") or "").strip(),
        to_company=str(response.get("to_company") or "").strip(),
        new_role=str(response.get("new_role") or "").strip(),
        synthetic_scenario=bool(response.get("synthetic_scenario")),
        department_hint=_optional_text(response.get("department_hint")),
        geography=_optional_text(response.get("geography")),
        industry_override=_optional_text(response.get("industry_override")),
        additional_context=_optional_text(response.get("additional_context")),
    )


def persist_transition_request_session(session: Any, request: TransitionRequest) -> Dict[str, Any]:
    """Persist the transition request in a Chainlit-like session store."""
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    session.set(TRANSITION_REQUEST_SESSION_KEY, payload)
    return payload


def load_transition_request_session(session: Any) -> TransitionRequest | None:
    """Load a persisted transition request from a Chainlit-like session store."""
    payload = session.get(TRANSITION_REQUEST_SESSION_KEY)
    if not payload:
        return None
    if isinstance(payload, TransitionRequest):
        return payload
    if hasattr(TransitionRequest, "model_validate"):
        return TransitionRequest.model_validate(payload)
    return TransitionRequest.parse_obj(payload)


def build_transition_form_props(industry_options: list[dict[str, str]] | None = None) -> Dict[str, Any]:
    """Build default CustomElement props for the transition form."""
    return {
        "person_name": "",
        "from_company": "",
        "to_company": "",
        "new_role": "",
        "synthetic_scenario": True,
        "department_hint": "",
        "geography": "",
        "industry_override": "",
        "additional_context": "",
        "industry_options": industry_options or [],
    }


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
