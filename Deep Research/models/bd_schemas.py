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


# =============================================================================
# Credentials Agent
# =============================================================================

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
    parsed_research: Optional[DeepResearchOutput] = Field(None, description="Parsed research")
    credentials_results: Dict[str, CredentialsResponse] = Field(
        default_factory=dict, 
        description="Credentials per opportunity title"
    )
    final_report: Optional[MDReport] = Field(None, description="Final synthesized report")
    trace: List[str] = Field(default_factory=list, description="Execution trace log")
    errors: List[str] = Field(default_factory=list, description="Errors encountered")
