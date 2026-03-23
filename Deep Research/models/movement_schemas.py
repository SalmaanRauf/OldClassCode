"""
Pydantic models for the people movement brief workflow.
"""
from __future__ import annotations

from typing import List, Literal, Optional

try:
    from pydantic import BaseModel, Field, field_validator
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass

    def Field(*args, **kwargs):  # type: ignore
        return None

    def field_validator(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func
        return decorator


MovementCategory = Literal["EXEC", "BUYER"]
MovementActionPosture = Literal[
    "Immediate Re-engagement",
    "Expansion Opportunity",
    "Monitor",
]
MovementLookupStatus = Literal["Matched", "No Match", "Lookup Failed"]


class MovementBriefRequest(BaseModel):
    """Structured user input for the named-move people movement workflow."""

    person_name: str = Field(..., description="Named mover driving the scan")
    from_company: str = Field(..., description="Source company")
    to_company: str = Field(..., description="Destination company")
    new_role: str = Field(..., description="New destination role")
    lookback_days: int = Field(180, ge=30, le=365, description="Movement lookback window")
    synthetic_scenario: bool = Field(
        True,
        description="Whether this move is hypothetical for planning/demo purposes",
    )
    geography: Optional[str] = Field(None, description="Optional geography hint")
    industry_override: Optional[str] = Field(None, description="Explicit industry override")
    additional_context: Optional[str] = Field(None, description="Optional extra context")

    @field_validator("person_name", "from_company", "to_company", "new_role")
    @classmethod
    def _reject_blank_required_fields(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("value must not be blank")
        return str(value).strip()


class MovementEvidence(BaseModel):
    """Source-backed evidence supporting a movement row."""

    evidence_quote: str = Field(..., description="Short quote supporting the movement")
    source_url: str = Field(..., description="Canonical source URL")
    source_title: Optional[str] = Field(None, description="Source title")
    source_marker: Optional[str] = Field(None, description="Optional footnote/source marker")
    corroborated: bool = Field(False, description="Whether the move is corroborated by more than one source")
    confidence_label: Optional[Literal["High", "Medium", "Low"]] = Field(
        None,
        description="Confidence label for display",
    )

    @field_validator("evidence_quote", "source_url")
    @classmethod
    def _reject_blank_required_fields(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("value must not be blank")
        return str(value).strip()


class MovementLeverageSummary(BaseModel):
    """Internal relationship leverage facts for a moved person."""

    known: bool = Field(False, description="Whether Protiviti has identifiable relationship evidence")
    worked_with: bool = Field(False, description="Whether Protiviti has explicit delivery evidence")
    project_count: int = Field(0, ge=0, description="Number of related projects")
    win_count: int = Field(0, ge=0, description="Number of related wins")
    relationship_owner: Optional[str] = Field(None, description="Internal relationship owner")
    person_match_status: Optional[str] = Field(None, description="Match status from ProConnect")


class MovementCredentialReference(BaseModel):
    """Minimal credential reference used inside proof packets."""

    title: str = Field(..., description="Credential title")
    url: str = Field(..., description="Credential URL")


class MovementCredentialsProof(BaseModel):
    """Credential proof packet attached to a prioritized movement row."""

    lookup_status: MovementLookupStatus = Field("No Match", description="Credential lookup outcome")
    summary: str = Field("", description="Short proof summary")
    matched_credentials: List[MovementCredentialReference] = Field(
        default_factory=list,
        description="Matched credential references",
    )


class MovementAction(BaseModel):
    """Action recommendation derived from a ranked movement row."""

    action_posture: MovementActionPosture = Field(..., description="Action posture classification")
    person_name: str = Field(..., description="Moved person tied to the action")
    likely_play: str = Field(..., description="Likely consulting play")
    why_now: str = Field(..., description="Why the action matters now")
    relationship_owner: Optional[str] = Field(None, description="Internal owner to move first")


class MovementRecord(BaseModel):
    """Source-backed movement record enriched with leverage and proof when available."""

    person_name: str = Field(..., description="Moved person")
    target_company: str = Field(..., description="Target company/account")
    previous_role: str = Field(..., description="Previous role")
    new_role: str = Field(..., description="New role")
    movement_type: str = Field(..., description="Movement type, e.g. Promoted or Joined")
    category: MovementCategory = Field(..., description="Movement category")
    company_context: str = Field(..., description="Internal, inbound, outbound, board_integration, etc.")
    evidence: MovementEvidence = Field(..., description="Primary source-backed evidence")
    leverage: Optional[MovementLeverageSummary] = Field(
        None,
        description="Internal relationship leverage summary",
    )
    credentials_proof: Optional[MovementCredentialsProof] = Field(
        None,
        description="Credential proof packet for prioritized movements",
    )


class MovementBrief(BaseModel):
    """Top-level people movement brief contract."""

    executive_summary: str = Field(..., description="Short account-level summary")
    signal_summary: List[str] = Field(default_factory=list, description="Account-level pressure summary")
    movement_rows: List[MovementRecord] = Field(
        default_factory=list,
        max_length=10,
        description="Visible movement table rows",
    )
    where_to_act: List[MovementAction] = Field(
        default_factory=list,
        max_length=3,
        description="Top action recommendations",
    )
    takeaway: str = Field(..., description="Closing takeaway")
