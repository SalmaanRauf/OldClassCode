"""
Pydantic models for the Transition Playbook workflow.

These contracts intentionally stay narrower than the existing BD report models.
They represent:
- transition intake
- ProConnect preflight/validation output
- compact final brief output
"""
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


TransitionConfidence = Literal["High", "Medium", "Low"]
TransitionMatchStatus = Literal["matched", "candidate", "not_found", "not_requested"]
ArtifactType = Literal["deep_research_report", "proconnect_dossier", "evidence_sources"]


class TransitionRequest(BaseModel):
    """User input for a transition scenario."""

    person_name: str = Field(..., description="Person involved in the transition scenario")
    from_company: str = Field(..., description="Source company name")
    to_company: str = Field(..., description="Destination company name")
    new_role: str = Field(..., description="New role/title at destination company")
    synthetic_scenario: bool = Field(
        False,
        description="Whether this scenario is hypothetical for planning/demo purposes",
    )
    department_hint: Optional[str] = Field(None, description="Optional department hint for lookup narrowing")
    geography: Optional[str] = Field(None, description="Optional geography hint")
    industry_override: Optional[str] = Field(None, description="Explicit prompt-industry override")
    additional_context: Optional[str] = Field(None, description="Extra user-supplied planning context")

    @field_validator("person_name", "from_company", "to_company", "new_role")
    @classmethod
    def _reject_blank_required_fields(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("value must not be blank")
        return str(value).strip()


class TransitionPersonResolution(BaseModel):
    """Compact person-resolution state for preflight display."""

    requested_name: str = Field(..., description="Original person name requested by the user")
    match_status: TransitionMatchStatus = Field("not_requested", description="Resolution state")
    matched_name: Optional[str] = Field(None, description="Resolved person display name")
    matched_title: Optional[str] = Field(None, description="Resolved current title")
    match_source: Optional[str] = Field(None, description="Winning evidence source")
    match_scope: Optional[str] = Field(None, description="Whether the match tied to the source or destination account")
    linked_account_id: Optional[str] = Field(None, description="Resolved linked account identifier for the matched person")
    direct_person_evidence: bool = Field(False, description="Whether direct person-level evidence exists")
    match_diagnostics: List[str] = Field(
        default_factory=list,
        description="Human-readable explanation of why the match succeeded or failed",
    )
    candidate_suggestions: List[str] = Field(
        default_factory=list,
        description="Top candidate suggestions when exact matching is not available",
    )


class AccountResolution(BaseModel):
    """Compact account-resolution state for preflight display."""

    company_name: str = Field(..., description="Resolved or requested company name")
    resolved: bool = Field(False, description="Whether the account was resolved")
    account_id: Optional[str] = Field(None, description="Resolved account identifier")


class QuickRelationshipIndicators(BaseModel):
    """Small relationship summary for the preflight review surface."""

    warm_intro_path_available: bool = Field(False, description="Whether a warm path exists")
    source_worked_before: bool = Field(False, description="Whether Protiviti has prior source-account work")
    destination_worked_before: bool = Field(False, description="Whether Protiviti has prior destination-account work")
    source_key_buyer_count: int = Field(0, description="Source-account key buyer count")
    destination_key_buyer_count: int = Field(0, description="Destination-account key buyer count")
    source_connected_colleague_count: int = Field(0, description="Source-account connected colleague count")
    destination_connected_colleague_count: int = Field(0, description="Destination-account connected colleague count")


class OpportunityHypothesis(BaseModel):
    """Pre-research opportunity hypothesis generated from ProConnect context."""

    title: str = Field(..., description="Short opportunity hypothesis title")
    rationale: str = Field(..., description="Why this hypothesis is plausible")
    confidence: TransitionConfidence = Field("Medium", description="Hypothesis confidence")


class TransitionPreflight(BaseModel):
    """Validated transition context shown before Deep Research is launched."""

    request: TransitionRequest = Field(..., description="Original transition request")
    person_resolution: TransitionPersonResolution = Field(..., description="Person match state")
    from_account: AccountResolution = Field(..., description="Source account resolution")
    to_account: AccountResolution = Field(..., description="Destination account resolution")
    quick_indicators: QuickRelationshipIndicators = Field(..., description="Compact relationship summary")
    opportunity_hypotheses: List[OpportunityHypothesis] = Field(
        default_factory=list,
        description="Top opportunity themes to seed the research plan",
    )
    inferred_industry: str = Field("general", description="Industry prompt family selected for research")
    suggested_research_prompt: str = Field("", description="Generated research prompt preview")
    review_diagnostics: List[str] = Field(
        default_factory=list,
        description="Review-surface diagnostics explaining unresolved person or account context",
    )


class TransitionOpportunityCard(BaseModel):
    """Compact opportunity card for the transition brief."""

    title: str = Field(..., description="Opportunity title")
    why_now: str = Field(..., description="Why this is timely")
    role_fit: str = Field(..., description="Why it fits the target executive role")
    confidence: TransitionConfidence = Field("Medium", description="Brief confidence level")


class TransitionProofCard(BaseModel):
    """Compact proof and warm-path card aligned to an opportunity."""

    opportunity_title: str = Field(..., description="Opportunity title this proof supports")
    credential_summary: str = Field("", description="Credential proof summary")
    warm_path_summary: str = Field("", description="Relationship/warm intro summary")
    internal_sponsors: List[str] = Field(default_factory=list, description="Likely internal sponsors or owners")


class RecommendedAction(BaseModel):
    """Small action item for the transition brief."""

    title: str = Field(..., description="Action headline")
    owner_hint: Optional[str] = Field(None, description="Likely internal owner")
    rationale: str = Field("", description="Why this action matters")


class HiddenArtifactRef(BaseModel):
    """Reference to a non-default artifact shown behind a secondary action."""

    artifact_type: ArtifactType = Field(..., description="Type of hidden artifact")
    label: str = Field(..., description="UI label for the action")
    artifact_key: str = Field(..., description="Stable artifact key for retrieval")


class TransitionBrief(BaseModel):
    """Compact default output for the transition workflow."""

    transition_summary: str = Field("", description="Compact transition summary")
    top_opportunities: List[TransitionOpportunityCard] = Field(
        default_factory=list,
        description="Small set of ranked opportunity cards",
    )
    proof_and_warm_paths: List[TransitionProofCard] = Field(
        default_factory=list,
        description="Proof and warm intro support aligned to opportunities",
    )
    recommended_actions: List[RecommendedAction] = Field(
        default_factory=list,
        description="Next actions for account leaders",
    )
    hidden_artifacts: List[HiddenArtifactRef] = Field(
        default_factory=list,
        description="Secondary artifacts such as full research and dossier detail",
    )
