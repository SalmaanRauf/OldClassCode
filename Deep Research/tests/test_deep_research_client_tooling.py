"""
Tests for Azure Deep Research tool-definition construction.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.deep_research_client import DeepResearchClient  # noqa: E402


def test_deep_research_client_uses_sdk_tool_helper_shape() -> None:
    client = object.__new__(DeepResearchClient)
    client._deep_model = "o3-deep-research"
    client._bing_connection = (
        "/subscriptions/00000000-0000-0000-0000-000000000000"
        "/resourceGroups/rg/providers/Microsoft.CognitiveServices"
        "/accounts/account/projects/project/connections/bing"
    )

    definitions = client._build_deep_research_tool_definitions()

    assert isinstance(definitions, list)
    assert definitions

    definition = definitions[0]
    payload = definition.as_dict() if hasattr(definition, "as_dict") else definition
    deep_research = payload["deep_research"]

    assert payload["type"] == "deep_research"
    assert deep_research["deep_research_model"] == "o3-deep-research"
    assert deep_research["bing_grounding_connections"][0]["connection_id"] == client._bing_connection
