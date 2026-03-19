"""
Tests for shared financial-services signal registry helpers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.signal_registry_service import SignalRegistryService


def test_extract_fs_signal_aliases_from_text_prefers_longest_aliases_once():
    service = SignalRegistryService()

    aliases = service.extract_fs_signal_aliases_from_text(
        "Research executive transition, buyer movement, people movement, and regulatory deadline updates."
    )

    assert "executive transition" in aliases
    assert "buyer movement" in aliases
    assert "people movement" in aliases
    assert "regulatory deadline" in aliases
    assert aliases.count("executive transition") == 1


def test_extract_fs_signal_codes_from_text_expands_all_requested_phrase():
    service = SignalRegistryService()

    codes = service.extract_fs_signal_codes_from_text(
        "Research all relevant signals for a financial-services account."
    )

    assert "FS.EXEC.TRANSITION" in codes
    assert "FS.REGULATORY.DEADLINE" in codes
    assert len(codes) >= 5


def test_canonicalize_fs_signals_includes_buyer_movement():
    service = SignalRegistryService()

    codes = service.canonicalize_fs_signals(["Buyer Movement"])

    assert codes == ["FS.BUYER.MOVEMENT"]


def test_extract_fs_signal_codes_from_text_preserves_exec_then_buyer_order():
    service = SignalRegistryService()

    codes = service.extract_fs_signal_codes_from_text(
        "Please research executive movement and buyer movement signals."
    )

    assert codes[:2] == ["FS.EXEC.TRANSITION", "FS.BUYER.MOVEMENT"]
