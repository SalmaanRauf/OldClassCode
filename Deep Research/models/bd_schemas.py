"""
Pydantic models for BD MVP orchestration.

These models define the data structures for:
- User triggers (BDTrigger)
- Deep Research output parsing (Opportunity, DeepResearchOutput)
- Credentials Agent responses (CredentialMatch, CredentialsResponse)
- Final report generation (MDReport, MDReportOpportunity)
"""
from datetime import datetime
from typing import Dict, List, Optional, Literal

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    class BaseModel:  # type: ignore
        pass
    def Field(*args, **kwargs):  # type: ignore
        return None


# =============================================================================
# User Trigger
# =============================================================================

class BDTrigger(BaseModel):
    """User input that triggers BD analysis.
    
    Attributes:
        sector: Industry sector to focus on (e.g., "Defense", "Financial Services")
        signals: List of signals to detect (e.g., ["CMMC", "M&A"])
        company_focus: Optional specific company to focus on
        geography: Optional geographic filter (e.g., "CONUS", "EMEA")
        time_window_days: How far back to look for signals (default 30)
        min_value_usd: Optional minimum opportunity value filter
    """
    sector: str = Field(..., description="Industry sector to focus on")
    signals: List[str] = Field(default_factory=list, description="Signals to detect")
    company_focus: Optional[str] = Field(None, description="Specific company focus")
    user_prompt_context: Optional[str] = Field(
        None,
        description="Sanitized snippet of the original user prompt for synthesis context anchoring"
    )
    geography: Optional[str] = Field(None, description="Geographic filter")
    time_window_days: int = Field(30, ge=1, le=365, description="Lookback window in days")
    min_value_usd: Optional[int] = Field(None, ge=0, description="Minimum opportunity value")


# =============================================================================
# Deep Research Output
# =============================================================================

class Opportunity(BaseModel):
    """Single opportunity extracted from Deep Research output.
    
    Based on sample output format from NextSteps_POC.md:
    - Title with agency
    - Scope description
    - Estimated value
    - Timeline
    - Incumbent info
    - CMMC/compliance requirements
    - Confidence level based on citation quality
    """
    title: str = Field(..., description="Opportunity title")
    agency: Optional[str] = Field(None, description="Government agency or organization")
    scope: str = Field(..., description="Scope of work description")
    estimated_value: Optional[str] = Field(None, description="Estimated contract value (e.g., '$2.4B')")
    timeline: Optional[str] = Field(None, description="Expected timeline (e.g., 'FY2025-2027')")
    incumbent: Optional[str] = Field(None, description="Current incumbent if known")
    cmmc_level: Optional[str] = Field(None, description="CMMC compliance requirement if applicable")
    confidence: Literal["High", "Medium", "Low"] = Field("Medium", description="Confidence level")
    citations: List[str] = Field(default_factory=list, description="Source URLs")


OpportunityExtractionStatus = Literal["Parsed", "No Opportunities", "Extraction Failed"]


class OpportunityExtractionDiagnostics(BaseModel):
    """Diagnostics for opportunity extraction quality and method."""

    status: OpportunityExtractionStatus = Field(
        "No Opportunities",
        description="Overall extraction status classification"
    )
    reason: Optional[str] = Field(
        None,
        description="Human-readable explanation for extraction status"
    )
    opportunities_extracted_count: int = Field(
        0,
        description="Number of parsed opportunities"
    )
    extraction_method: str = Field(
        "none",
        description="Method used for extraction"
    )
    extraction_confidence: Literal["High", "Medium", "Low"] = Field(
        "Low",
        description="Confidence in extraction completeness"
    )
    candidate_signal_count: int = Field(
        0,
        description="Count of opportunity-like signals detected in source text"
    )


class DeepResearchOutput(BaseModel):
    """Parsed output from Deep Research.
    
    Structure matches the sample run output from NextSteps_POC.md:
    - Executive Summary
    - Signals Detected (bullet points)
    - Opportunity Details (list of Opportunity objects)
    - Recommended Actions (bullet points)
    - Raw citations for traceability
    """
    executive_summary: str = Field("", description="High-level summary")
    signals_detected: List[str] = Field(default_factory=list, description="Detected signals")
    opportunities: List[Opportunity] = Field(default_factory=list, description="Extracted opportunities")
    recommended_actions: List[str] = Field(default_factory=list, description="Recommended next steps")
    raw_citations: List[str] = Field(default_factory=list, description="All source URLs")
    structured_citations: List[str] = Field(
        default_factory=list,
        description="Structured source URLs supplied by Deep Research response metadata"
    )
    extraction_diagnostics: Optional[OpportunityExtractionDiagnostics] = Field(
        None,
        description="Opportunity extraction diagnostics"
    )


# =============================================================================
# Credentials Agent
# =============================================================================

LookupStatus = Literal["Matched", "No Match", "Lookup Failed"]


class CredentialMatch(BaseModel):
    """Single credential from Protiviti's internal database.
    
    Based on Credentials Agent identity from NextSteps_POC.md:
    - Client challenge (problem solved)
    - Approach taken
    - Value provided
    - iShare URL for detail
    """
    title: str = Field(..., description="Credential title")
    client_challenge: str = Field(..., description="Problem the client faced")
    approach: str = Field("", description="How Protiviti approached it")
    value_provided: str = Field(..., description="Value delivered to client")
    industry: str = Field("", description="Industry sector")
    technologies_used: List[str] = Field(default_factory=list, description="Technologies used")
    emd: Optional[str] = Field(None, description="Engagement Managing Director")
    url: str = Field(..., description="iShare URL for the credential")


class CredentialsResponse(BaseModel):
    """Response from Credentials Agent for a single opportunity.
    
    Contains matching credentials or explicitly flags when none found.
    """
    opportunity_title: str = Field(..., description="The opportunity being validated")
    matches: List[CredentialMatch] = Field(default_factory=list, description="Matching credentials")
    no_matches_found: bool = Field(False, description="True if no relevant credentials exist")
    lookup_status: LookupStatus = Field(
        "No Match",
        description="Explicit lookup result classification"
    )
    failure_reason: Optional[str] = Field(
        None,
        description="Failure reason when lookup_status is 'Lookup Failed'"
    )
    diagnostics: Optional["CredentialsLookupDiagnostics"] = Field(
        None,
        description="Full diagnostics for credentials lookup"
    )

    def __init__(self, **data):
        super().__init__(**data)
        self._sync_legacy_fields()

    def _sync_legacy_fields(self) -> None:
        """Keep legacy flags compatible with explicit lookup status."""
        if self.lookup_status == "No Match" and self.matches:
            # Backward compatibility for older call sites that populated matches
            # without setting explicit lookup_status.
            self.lookup_status = "Matched"

        if self.lookup_status == "Matched":
            if not self.matches:
                self.lookup_status = "No Match"
                self.no_matches_found = True
            else:
                self.no_matches_found = False
                self.failure_reason = None
        elif self.lookup_status == "No Match":
            self.no_matches_found = True
            self.failure_reason = None
        else:
            self.no_matches_found = True
            if not self.failure_reason:
                self.failure_reason = "Credentials lookup failed."

        if self.diagnostics:
            self.diagnostics.lookup_status = self.lookup_status
            self.diagnostics.match_count = len(self.matches)
            if self.lookup_status == "Lookup Failed":
                self.diagnostics.error_message = self.failure_reason or self.diagnostics.error_message


class CredentialsLookupDiagnostics(BaseModel):
    """Per-opportunity diagnostics for Credentials Agent telemetry."""

    opportunity_title: str = Field(..., description="Opportunity title sent to credentials agent")
    sector: str = Field("", description="Sector context passed to credentials agent")
    query_text: str = Field("", description="Full rendered prompt/query sent to credentials agent")
    raw_response_text: str = Field("", description="Raw unparsed response from credentials agent")
    parse_outcome: str = Field("", description="Parser outcome (json_parsed/no_match_text/lookup_failed/etc)")
    lookup_status: LookupStatus = Field("No Match", description="Final lookup classification")
    error_type: Optional[str] = Field(None, description="Error type if lookup failed")
    error_message: Optional[str] = Field(None, description="Error message if lookup failed")
    duration_ms: float = Field(0.0, description="Lookup duration in milliseconds")
    match_count: int = Field(0, description="Number of parsed credential matches")


class CredentialsBatchDiagnostics(BaseModel):
    """Run-level diagnostics for a single batched credentials lookup."""

    invoked: bool = Field(False, description="Whether batch lookup was attempted")
    lookup_count_requested: int = Field(0, description="Number of opportunities requested in the batch")
    lookup_count_returned: int = Field(0, description="Number of opportunity result groups returned by the model")
    duration_ms: float = Field(0.0, description="Batch lookup duration in milliseconds")
    query_text: str = Field("", description="Full batched prompt sent to credentials agent")
    raw_response_text: str = Field("", description="Full raw response returned by credentials agent")
    parse_outcome: str = Field("", description="Batch parse outcome classification")
    error_type: Optional[str] = Field(None, description="Error type when batch lookup fails")
    error_message: Optional[str] = Field(None, description="Error message when batch lookup fails")


try:  # pragma: no cover - harmless when pydantic is unavailable
    CredentialsResponse.model_rebuild()
except Exception:
    pass


# =============================================================================
# Final Report
# =============================================================================

class MDReportOpportunity(BaseModel):
    """Opportunity enriched with credentials validation.
    
    Combines Deep Research opportunity with Credentials Agent results.
    """
    opportunity: Opportunity = Field(..., description="The opportunity from Deep Research")
    credentials: List[CredentialMatch] = Field(default_factory=list, description="Supporting credentials")
    validation_status: Literal["Validated", "Partial", "No Internal Data"] = Field(
        "No Internal Data", 
        description="Whether opportunity is validated by internal credentials"
    )
    credentials_lookup_status: LookupStatus = Field(
        "No Match",
        description="Explicit status of credentials lookup for this opportunity"
    )


class SignalEvidence(BaseModel):
    """Evidence record for a normalized financial-services signal."""

    signal_code: str = Field(..., description="Canonical signal code (e.g., FS.EXEC.TRANSITION)")
    signal_label: str = Field(..., description="Human readable signal label")
    status: Literal["Confirmed", "Insufficient", "Rejected"] = Field(
        "Insufficient",
        description="Signal confidence status after deterministic guardrails"
    )
    evidence_quote: str = Field("", description="Short quote supporting the signal")
    source_url: str = Field("", description="Primary source URL supporting the evidence")
    source_title: Optional[str] = Field(None, description="Source title for readability")
    analysis: str = Field("", description="Analytical interpretation of why the evidence matters")


class PhaseOpportunity(BaseModel):
    """Derived opportunity detail for phase-based evidence-locked output."""

    derived_from_signal: str = Field(..., description="Canonical signal code that produced this opportunity")
    overview: str = Field("", description="Opportunity overview")
    technical_explanation: str = Field("", description="Detailed technical explanation")
    layman_explanation: str = Field("", description="Plain-English explanation")
    relevant_service_lines: List[str] = Field(default_factory=list, description="Service lines tied to this opportunity")
    credentials_summary: str = Field("", description="Credential relevance summary")
    recommended_actions: List[str] = Field(default_factory=list, description="Opportunity-specific action list")
    sources: List[str] = Field(default_factory=list, description="Opportunity-specific source URLs")


class MDReport(BaseModel):
    """Final report for Managing Directors.
    
    Concise, actionable report synthesizing:
    - Deep Research findings
    - Credentials validation
    - Recommended actions
    
    Per NextSteps_POC.md: 3-5 bullets per section, generative summarizations.
    """
    trigger_summary: str = Field(..., description="Summary of what was requested")
    executive_summary: str = Field(..., description="3-5 sentence executive summary")
    top_opportunities: List[MDReportOpportunity] = Field(
        default_factory=list, 
        max_length=3,
        description="Top 3 opportunities with validation"
    )
    signals_detected: List[str] = Field(default_factory=list, description="Key signals found")
    recommended_actions: List[str] = Field(default_factory=list, description="3-5 actionable next steps")
    generated_at: datetime = Field(default_factory=datetime.now, description="Report generation timestamp")
    confidence_note: str = Field("", description="Overall confidence assessment")
    synthesis_status: Literal["synthesized", "fallback"] = Field(
        "synthesized",
        description="Whether final analyst synthesis succeeded or returned fallback output"
    )
    synthesis_fallback_reason: Optional[str] = Field(
        None,
        description="Fallback reason when synthesis_status is fallback"
    )
    synthesis_error_message: Optional[str] = Field(
        None,
        description="Underlying synthesis/parse error when available"
    )
    credentials_evidence: List[CredentialsLookupDiagnostics] = Field(
        default_factory=list,
        description="Full credentials diagnostics to render in UI/report"
    )
    credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = Field(
        None,
        description="Full batched credentials lookup diagnostics"
    )
    credentials_lookup_mode: str = Field(
        "serial_per_opportunity",
        description="Lookup execution mode used for credentials validation"
    )
    opportunities_source: str = Field(
        "none",
        description="Source used for parsed opportunities (atlas_digest/deterministic_extractor/none)"
    )
    opportunity_extraction_status: OpportunityExtractionStatus = Field(
        "No Opportunities",
        description="Extraction status for the pipeline run"
    )
    opportunity_extraction_reason: Optional[str] = Field(
        None,
        description="Reason for extraction status when available"
    )
    opportunities_extracted_count: int = Field(
        0,
        description="Number of extracted opportunities"
    )
    lookups_executed_count: int = Field(
        0,
        description="Number of credential lookups executed"
    )
    lookups_skipped_reason: Optional[str] = Field(
        None,
        description="Reason lookups were skipped"
    )
    credentials_status_counts: Dict[str, int] = Field(
        default_factory=lambda: {"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        description="Count of credentials outcomes by status"
    )
    phase2_headline: Optional[str] = Field(
        None,
        description="Evidence-locked Phase 2 governing headline"
    )
    phase2_signal_evidence: Optional[List[SignalEvidence]] = Field(
        None,
        description="Phase 2 confirmed signal evidence list"
    )
    phase2_footnotes: Optional[List[str]] = Field(
        None,
        description="Phase 2 footnotes with quote and linkage context"
    )
    phase3_opportunities: Optional[List[PhaseOpportunity]] = Field(
        None,
        description="Phase 3 deterministic opportunities derived from confirmed signals"
    )
    phase_sources: Optional[List[str]] = Field(
        None,
        description="Final phase output source URLs"
    )
    layout_version: Optional[str] = Field(
        None,
        description="Renderer layout hint for phase-based output"
    )


# =============================================================================
# Orchestrator Context
# =============================================================================

class BDContext(BaseModel):
    """Runtime context for BD orchestration.
    
    Accumulates state as the orchestrator progresses through steps.
    Used for debugging and trace generation.
    """
    trigger: BDTrigger
    deep_research_raw: Optional[str] = Field(None, description="Raw Deep Research markdown")
    structured_source_urls: List[str] = Field(
        default_factory=list,
        description="Structured source URLs passed from Deep Research response"
    )
    parsed_research: Optional[DeepResearchOutput] = Field(None, description="Parsed research")
    credentials_results: Dict[str, CredentialsResponse] = Field(
        default_factory=dict, 
        description="Credentials per opportunity title"
    )
    credentials_diagnostics: Dict[str, CredentialsLookupDiagnostics] = Field(
        default_factory=dict,
        description="Credentials diagnostics per opportunity title"
    )
    credentials_batch_diagnostics: Optional[CredentialsBatchDiagnostics] = Field(
        None,
        description="Run-level diagnostics for batched credentials lookup"
    )
    credentials_lookup_mode: str = Field(
        "serial_per_opportunity",
        description="Lookup execution mode used for this run"
    )
    opportunities_source: str = Field(
        "none",
        description="Source used for parsed opportunities"
    )
    opportunity_digest_diagnostics: Optional[Dict[str, object]] = Field(
        None,
        description="ATLAS opportunity digestion diagnostics"
    )
    opportunity_extraction_status: OpportunityExtractionStatus = Field(
        "No Opportunities",
        description="Extraction status for current run"
    )
    opportunity_extraction_reason: Optional[str] = Field(
        None,
        description="Reason for extraction classification"
    )
    opportunities_extracted_count: int = Field(
        0,
        description="Count of extracted opportunities"
    )
    lookups_executed_count: int = Field(
        0,
        description="Count of credential lookups executed"
    )
    lookups_skipped_reason: Optional[str] = Field(
        None,
        description="Reason lookups were skipped"
    )
    credentials_status_counts: Dict[str, int] = Field(
        default_factory=lambda: {"Matched": 0, "No Match": 0, "Lookup Failed": 0},
        description="Credentials status counts for run diagnostics"
    )
    fs_signal_evidence: List[SignalEvidence] = Field(
        default_factory=list,
        description="Financial services signal evidence records"
    )
    fs_phase3_candidates: List[PhaseOpportunity] = Field(
        default_factory=list,
        description="Financial services derived phase opportunities"
    )
    fs_allowed_sources: List[str] = Field(
        default_factory=list,
        description="Allowed sources after deterministic source guardrails"
    )
    fs_discovery_sources: List[str] = Field(
        default_factory=list,
        description="Internal discovery source set before display filtering"
    )
    fs_confirmation_sources: List[str] = Field(
        default_factory=list,
        description="Displayable confirmation sources used for signal source_url selection"
    )
    synthesis_status: Optional[str] = Field(
        None,
        description="Synthesis outcome status from FinalAnalystAgent"
    )
    synthesis_fallback_reason: Optional[str] = Field(
        None,
        description="Fallback reason if synthesis returned fallback report"
    )
    synthesis_error_message: Optional[str] = Field(
        None,
        description="Synthesis error details when available"
    )
    final_report: Optional[MDReport] = Field(None, description="Final synthesized report")
    trace: List[str] = Field(default_factory=list, description="Execution trace log")
    errors: List[str] = Field(default_factory=list, description="Errors encountered")
