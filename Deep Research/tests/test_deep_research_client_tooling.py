"""
Tests for Azure Deep Research tool-definition construction.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import deep_research_client as dr_module  # noqa: E402
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


def test_deep_research_client_registry_is_keyed_by_prompt(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, industry="general", instructions_override=None):
            self._industry = industry
            self._instructions_override = instructions_override
            created.append((industry, instructions_override))

    monkeypatch.setattr(dr_module, "DeepResearchClient", FakeClient)
    dr_module._deep_research_clients.clear()
    dr_module.deep_research_client = None

    first = dr_module.get_deep_research_client("general", "prompt-a")
    second = dr_module.get_deep_research_client("general", "prompt-a")
    third = dr_module.get_deep_research_client("general", "prompt-b")
    fourth = dr_module.get_deep_research_client("healthcare", "prompt-a")

    assert first is second
    assert third is not first
    assert fourth is not first
    assert len(created) == 3
