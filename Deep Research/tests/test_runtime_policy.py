"""
Unit tests for runtime policy defaults and normalization.
"""
import os

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.runtime_policy import get_runtime_policy


def test_runtime_policy_defaults_to_production_balanced():
    os.environ.pop("BD_RUNTIME_PROFILE", None)
    os.environ.pop("BD_FAILURE_VISIBILITY", None)
    os.environ.pop("BD_SOURCE_POLICY_MODE", None)

    policy = get_runtime_policy()

    assert policy.profile == "production"
    assert policy.show_failures is True
    assert policy.source_policy_mode == "balanced"


def test_runtime_policy_demo_defaults_to_failure_suppression():
    os.environ["BD_RUNTIME_PROFILE"] = "demo"
    os.environ.pop("BD_FAILURE_VISIBILITY", None)
    try:
        policy = get_runtime_policy()
    finally:
        os.environ.pop("BD_RUNTIME_PROFILE", None)

    assert policy.profile == "demo"
    assert policy.show_failures is False


def test_runtime_policy_explicit_visibility_override_wins():
    os.environ["BD_RUNTIME_PROFILE"] = "demo"
    os.environ["BD_FAILURE_VISIBILITY"] = "factual"
    try:
        policy = get_runtime_policy()
    finally:
        os.environ.pop("BD_RUNTIME_PROFILE", None)
        os.environ.pop("BD_FAILURE_VISIBILITY", None)

    assert policy.profile == "demo"
    assert policy.show_failures is True
