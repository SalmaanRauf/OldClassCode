"""
Helpers for normalizing Chainlit custom-element submission payloads.
"""
from __future__ import annotations

from typing import Any, Iterable


def extract_element_response_payload(
    response: Any,
    *,
    expected_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Unwrap common nested payload shapes returned by AskElementMessage.

    Chainlit element responses may surface submitted values either at the top level
    or nested under keys such as ``output`` or ``payload`` depending on the client
    path. This helper accepts either shape and returns the best matching dict.
    """

    if not isinstance(response, dict):
        return {}

    keys = tuple(str(key) for key in (expected_keys or ()))
    candidates: list[Any] = [
        response.get("output"),
        response.get("value"),
        response.get("values"),
        response.get("payload"),
        response.get("data"),
        response,
    ]

    if keys:
        for candidate in candidates:
            if isinstance(candidate, dict) and any(key in candidate for key in keys):
                return candidate

    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate

    return {}
