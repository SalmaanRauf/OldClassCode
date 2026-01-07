"""Utilities for loading cached company profiles shared with the agentic research system."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict


logger = logging.getLogger(__name__)

_PROFILE_DIR = (
    Path(__file__).resolve().parents[2]
    / "agentic-research-system"
    / "data"
    / "company_profiles"
)


def _normalize_company_name(name: str) -> str:
    return " ".join(name.replace("_", " ").split()).strip()


def load_company_profiles() -> Dict[str, Dict]:
    """Load all available company profile JSON files.

    Returns a dictionary keyed by canonical company name with the raw profile payloads.
    """
    profiles: Dict[str, Dict] = {}

    if not _PROFILE_DIR.exists():
        logger.warning("Company profile directory missing: %s", _PROFILE_DIR)
        return profiles

    for profile_path in _PROFILE_DIR.glob("*_profile.json"):
        slug = profile_path.stem.replace("_profile", "")
        try:
            with profile_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                continue
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load profile %s: %s", profile_path.name, exc)
            continue

        canonical_name = data.get("company_name") or _normalize_company_name(slug)
        data.setdefault("company_name", canonical_name)

        slug_name = _normalize_company_name(slug)
        for name in {canonical_name, slug_name}:
            profiles[name] = data

    logger.debug("Loaded %d company profiles from %s", len(profiles), _PROFILE_DIR)
    return profiles
