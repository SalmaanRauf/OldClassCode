"""
Runtime policy controls for BD/Deep Research behavior.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from config.config import AppConfig

RuntimeProfile = Literal["production", "demo"]
FailureVisibility = Literal["factual", "suppressed"]
SourcePolicyMode = Literal["quality_first", "balanced", "volume_first"]


@dataclass(frozen=True)
class RuntimePolicy:
    profile: RuntimeProfile = "production"
    failure_visibility: FailureVisibility = "factual"
    source_policy_mode: SourcePolicyMode = "balanced"
    report_style: str = "production"

    @property
    def is_demo(self) -> bool:
        return self.profile == "demo"

    @property
    def is_production(self) -> bool:
        return self.profile == "production"

    @property
    def show_failures(self) -> bool:
        return self.failure_visibility == "factual"


def _normalize_profile(value: str) -> RuntimeProfile:
    normalized = (value or "").strip().lower()
    if normalized == "demo":
        return "demo"
    return "production"


def _normalize_failure_visibility(value: str, profile: RuntimeProfile) -> FailureVisibility:
    normalized = (value or "").strip().lower()
    if normalized in {"suppressed", "hide"}:
        return "suppressed"
    if normalized in {"factual", "show"}:
        return "factual"
    # Auto-default: demo suppresses, production shows.
    return "suppressed" if profile == "demo" else "factual"


def _normalize_source_policy(value: str) -> SourcePolicyMode:
    normalized = (value or "").strip().lower()
    if normalized in {"balanced", "balance"}:
        return "balanced"
    if normalized in {"volume_first", "volume", "citation_volume"}:
        return "volume_first"
    return "quality_first"


def get_runtime_policy() -> RuntimePolicy:
    profile = _normalize_profile(
        os.getenv("BD_RUNTIME_PROFILE", getattr(AppConfig, "BD_RUNTIME_PROFILE", "production"))
    )
    failure_visibility = _normalize_failure_visibility(
        os.getenv("BD_FAILURE_VISIBILITY", getattr(AppConfig, "BD_FAILURE_VISIBILITY", "")),
        profile=profile,
    )
    source_policy_mode = _normalize_source_policy(
        os.getenv(
            "BD_SOURCE_POLICY_MODE",
            getattr(AppConfig, "BD_SOURCE_POLICY_MODE", "balanced"),
        )
    )
    report_style = (
        os.getenv("BD_REPORT_STYLE", getattr(AppConfig, "BD_REPORT_STYLE", "")) or ""
    ).strip().lower()
    if not report_style:
        report_style = "demo" if profile == "demo" else "production"
    return RuntimePolicy(
        profile=profile,
        failure_visibility=failure_visibility,
        source_policy_mode=source_policy_mode,
        report_style=report_style,
    )
