"""
Signal registry utilities for canonicalizing user-provided signal inputs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional


class SignalRegistryService:
    """Loads signal registry metadata and resolves canonical signal selections."""

    FS_CODE_MAP: Dict[str, str] = {
        "CONSENT_ORDER": "FS.CONSUMER.LITIGATION_SETTLEMENT",
        "MODEL_RISK": "FS.MODEL_RISK.FINDINGS",
        "CRO_TRANSITION": "FS.EXEC.TRANSITION",
        "BUYER_MOVEMENT": "FS.BUYER.MOVEMENT",
        "STRESS_TEST": "FS.STRESS_TEST.ISSUES",
        "REG_DEADLINE": "FS.REGULATORY.DEADLINE",
        "AML_BSA": "FS.AML.BSA_FINDINGS",
        "CECL": "FS.CECL.IMPLEMENTATION",
    }

    FS_ALIAS_MAP: Dict[str, str] = {
        "all": "__ALL__",
        "all signals": "__ALL__",
        "all relevant signals": "__ALL__",
        "all signal": "__ALL__",
        "executive movement": "FS.EXEC.TRANSITION",
        "people movement": "FS.EXEC.TRANSITION",
        "buyer movement": "FS.BUYER.MOVEMENT",
        "buyer promotion": "FS.BUYER.MOVEMENT",
        "buyer transition": "FS.BUYER.MOVEMENT",
        "buyer promotion / scope expansion": "FS.BUYER.MOVEMENT",
        "leadership movement": "FS.EXEC.TRANSITION",
        "leadership change": "FS.EXEC.TRANSITION",
        "executive transition": "FS.EXEC.TRANSITION",
        "cro transition": "FS.EXEC.TRANSITION",
        "cfo transition": "FS.EXEC.TRANSITION",
        "cco transition": "FS.EXEC.TRANSITION",
        "cro/cfo transition": "FS.EXEC.TRANSITION",
        "consent order": "FS.CONSUMER.LITIGATION_SETTLEMENT",
        "enforcement": "FS.CONSUMER.LITIGATION_SETTLEMENT",
        "regulatory deadline": "FS.REGULATORY.DEADLINE",
        "model risk": "FS.MODEL_RISK.FINDINGS",
        "stress test": "FS.STRESS_TEST.ISSUES",
        "aml": "FS.AML.BSA_FINDINGS",
        "bsa": "FS.AML.BSA_FINDINGS",
        "cecl": "FS.CECL.IMPLEMENTATION",
    }

    def __init__(self, registry_path: Optional[Path] = None):
        if registry_path is None:
            registry_path = Path(__file__).parent.parent / "prompts" / "signal_registry.json"
        self._registry_path = registry_path
        self._registry = self._load_registry()
        self._fs_signal_labels = self._build_fs_labels()
        self._supported_codes = set(self._fs_signal_labels.keys())

    def _load_registry(self) -> Dict[str, object]:
        if not self._registry_path.exists():
            return {}
        try:
            return json.loads(self._registry_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _build_fs_labels(self) -> Dict[str, str]:
        labels: Dict[str, str] = {}
        fs = self._registry.get("financial_services", {}) if isinstance(self._registry, dict) else {}
        signals = fs.get("signals", {}) if isinstance(fs, dict) else {}
        if not isinstance(signals, dict):
            return labels
        for raw_key, payload in signals.items():
            if raw_key not in self.FS_CODE_MAP:
                continue
            label = payload.get("label") if isinstance(payload, dict) else None
            labels[self.FS_CODE_MAP[raw_key]] = str(label or raw_key).strip()
        return labels

    def resolve_sector_key(self, sector: str) -> str:
        normalized = re.sub(r"[\s_]+", " ", (sector or "").strip().lower())
        if normalized in {"financial services", "financial service", "banking"}:
            return "financial_services"
        return normalized.replace(" ", "_")

    def is_financial_services(self, sector: str) -> bool:
        return self.resolve_sector_key(sector) == "financial_services"

    def get_fs_signal_codes(self) -> List[str]:
        return list(self.FS_CODE_MAP.values())

    def get_signal_label(self, signal_code: str) -> str:
        return self._fs_signal_labels.get(signal_code, signal_code)

    @staticmethod
    def _normalize_signal_token(value: str) -> str:
        normalized = (value or "").strip().lower()
        normalized = normalized.replace("&", " and ")
        normalized = re.sub(r"[_/\-,]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def canonicalize_fs_signals(self, raw_signals: List[str]) -> List[str]:
        """Canonicalize input signals for FS sector.

        Unknown values are ignored to avoid accidental ontology drift.
        """
        canonical: List[str] = []
        seen = set()

        def _append(code: str) -> None:
            if code in self._supported_codes and code not in seen:
                canonical.append(code)
                seen.add(code)

        tokens = [str(value).strip() for value in raw_signals if str(value).strip()]
        if not tokens:
            return canonical

        expanded_all = False
        for token in tokens:
            lowered = token.lower().strip()
            normalized = self._normalize_signal_token(token)
            mapped = self.FS_ALIAS_MAP.get(lowered) or self.FS_ALIAS_MAP.get(normalized)
            if mapped == "__ALL__":
                expanded_all = True
                continue
            if mapped:
                _append(mapped)
                continue

            # Accept canonical values directly.
            if token in self._supported_codes:
                _append(token)
                continue

            # Accept registry raw keys if caller passes them.
            upper = token.upper().replace(" ", "_")
            mapped_raw = self.FS_CODE_MAP.get(upper)
            if mapped_raw:
                _append(mapped_raw)

        if expanded_all:
            for code in self.get_fs_signal_codes():
                _append(code)

        return canonical

    def extract_fs_signal_aliases_from_text(self, text: str) -> List[str]:
        """Find financial-services signal aliases mentioned in free text."""
        lowered = (text or "").lower()
        normalized_query = self._normalize_signal_token(text or "")
        aliases: List[str] = []
        seen = set()

        for alias in sorted(self.FS_ALIAS_MAP.keys(), key=len, reverse=True):
            raw_pattern = r"\b" + re.escape(alias).replace(r"\ ", r"\s+") + r"\b"
            normalized_alias = self._normalize_signal_token(alias)
            normalized_pattern = (
                r"\b" + re.escape(normalized_alias).replace(r"\ ", r"\s+") + r"\b"
                if normalized_alias
                else None
            )
            if re.search(raw_pattern, lowered) or (
                normalized_pattern and re.search(normalized_pattern, normalized_query)
            ):
                if alias not in seen:
                    aliases.append(alias)
                    seen.add(alias)

        return aliases

    def extract_fs_signal_codes_from_text(self, text: str) -> List[str]:
        """Extract canonical FS signal codes from free text."""
        canonical = self.canonicalize_fs_signals(self.extract_fs_signal_aliases_from_text(text))
        if canonical:
            return canonical
        if re.search(r"\ball(?:\s+relevant)?\s+signals?\b", text or "", re.IGNORECASE):
            return self.get_fs_signal_codes()
        return []


_signal_registry_service: Optional[SignalRegistryService] = None


def get_signal_registry_service() -> SignalRegistryService:
    global _signal_registry_service
    if _signal_registry_service is None:
        _signal_registry_service = SignalRegistryService()
    return _signal_registry_service
