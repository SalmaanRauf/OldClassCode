"""
Integration tests for BDOrchestrator.

Uses mocked components to test the full workflow without live API calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime
from pathlib import Path
import json
import tempfile

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bd_orchestrator import BDOrchestrator
from services.opportunity_extractor import OpportunityExtractor
from services.opportunity_digestor import OpportunityDigestor
from services.fs_signal_evidence_digestor import FSSignalEvidenceDigestor
from services.fs_opportunity_deriver import FSOpportunityDeriver
from agents.credentials_agent import CredentialsAgent
from agents.final_analyst_agent import FinalAnalystAgent
from models.bd_schemas import (
    BDTrigger,
    Opportunity,
    DeepResearchOutput,
    CredentialsResponse,
    CredentialsLookupDiagnostics,
    CredentialsBatchDiagnostics,
    OpportunityExtractionDiagnostics,
    CredentialMatch,
    MDReport,
    MDReportOpportunity,
    SignalEvidence,
    PhaseOpportunity,
)


# =============================================================================
# Sample Data
# =============================================================================

SAMPLE_DEEP_RESEARCH = """
# Executive Summary

Defense sector opportunities detected for CMMC compliance.

## Signals Detected

• CMMC requirements expanding
• New leadership at target company

## Opportunity Details

• CMMC Program – DoD
  Scope: Compliance services
  Value: $2B
  Timeline: FY2025
  CMMC Compliance: Level 2

## Recommended Actions

• Engage leadership
• Propose assessment
"""


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_trigger():
    """Sample BD trigger."""
    return BDTrigger(
        sector="Defense",
        signals=["CMMC"],
        company_focus="Hanwha",
        time_window_days=30
    )


@pytest.fixture
def mock_extractor():
    """Mock OpportunityExtractor returning fixed output."""
    extractor = MagicMock(spec=OpportunityExtractor)
    extractor.extract.return_value = DeepResearchOutput(
        executive_summary="Defense opportunities detected.",
        signals_detected=["CMMC requirements expanding"],
        opportunities=[
            Opportunity(
                title="CMMC Program",
                agency="DoD",
                scope="Compliance services",
                estimated_value="$2B",
                timeline="FY2025",
                cmmc_level="Level 2",
                confidence="High"
            )
        ],
        recommended_actions=["Engage leadership"]
    )
    return extractor


@pytest.fixture
def mock_credentials_agent():
    """Mock CredentialsAgent returning credentials."""
    agent = MagicMock(spec=CredentialsAgent)
    diagnostics = CredentialsLookupDiagnostics(
        opportunity_title="CMMC Program",
        sector="Defense",
        query_text="full query text",
        raw_response_text='{"matches":[{"title":"A"}]}',
        parse_outcome="json_parsed_with_matches",
        lookup_status="Matched",
        duration_ms=10.0,
        match_count=1
    )
    agent.find_credentials_batch = AsyncMock(return_value=(
        {
            "CMMC Program": CredentialsResponse(
                opportunity_title="CMMC Program",
                matches=[
                    CredentialMatch(
                        title="CMMC Assessment for Defense Contractor",
                        client_challenge="Needed CMMC certification",
                        value_provided="Achieved certification",
                        url="https://ishare.protiviti.com/cred/123"
                    )
                ],
                no_matches_found=False,
                lookup_status="Matched",
                diagnostics=diagnostics
            )
        },
        CredentialsBatchDiagnostics(
            invoked=True,
            lookup_count_requested=1,
            lookup_count_returned=1,
            duration_ms=10.0,
            query_text="batch query text",
            raw_response_text='{"results":[{"opportunity_id":"opp_1"}]}',
            parse_outcome="batch_json_parsed",
        )
    ))
    agent.find_credentials = AsyncMock(return_value=CredentialsResponse(
        opportunity_title="CMMC Program",
        matches=[
            CredentialMatch(
                title="CMMC Assessment for Defense Contractor",
                client_challenge="Needed CMMC certification",
                value_provided="Achieved certification",
                url="https://ishare.protiviti.com/cred/123"
            )
        ],
        no_matches_found=False,
        lookup_status="Matched",
        diagnostics=diagnostics,
    ))
    return agent


@pytest.fixture
def mock_final_analyst():
    """Mock FinalAnalystAgent returning report."""
    agent = MagicMock(spec=FinalAnalystAgent)
    agent.synthesize = AsyncMock(return_value=MDReport(
        trigger_summary="Defense CMMC analysis",
        executive_summary="CMMC opportunities validated.",
        top_opportunities=[
            MDReportOpportunity(
                opportunity=Opportunity(
                    title="CMMC Program",
                    scope="Compliance",
                    confidence="High"
                ),
                credentials=[],
                validation_status="Validated",
                credentials_lookup_status="Matched"
            )
        ],
        signals_detected=["CMMC expanding"],
        recommended_actions=["Engage leadership"],
        generated_at=datetime.now(),
        confidence_note="High confidence"
    ))
    return agent


@pytest.fixture
def orchestrator(mock_extractor, mock_credentials_agent, mock_final_analyst):
    """Create BDOrchestrator with all mocked components."""
    return BDOrchestrator(
        extractor=mock_extractor,
        credentials_agent=mock_credentials_agent,
        final_analyst=mock_final_analyst
    )


# =============================================================================
# Full Flow Tests
# =============================================================================

class TestFullWorkflow:
    """Test complete orchestration workflow."""
    
    @pytest.mark.asyncio
    async def test_successful_run_with_provided_research(
        self, orchestrator, sample_trigger, mock_extractor, mock_credentials_agent, mock_final_analyst
    ):
        """Should complete full workflow with provided Deep Research output."""
        report = await orchestrator.run(
            sample_trigger,
            deep_research_output=SAMPLE_DEEP_RESEARCH
        )
        
        # Verify each step was called
        mock_extractor.extract.assert_called_once_with(SAMPLE_DEEP_RESEARCH)
        mock_credentials_agent.find_credentials.assert_called_once()
        mock_credentials_agent.find_credentials_batch.assert_not_called()
        mock_final_analyst.synthesize.assert_called_once()
        
        # Verify report
        assert report is not None
        assert report.trigger_summary == "Defense CMMC analysis"
        assert len(report.top_opportunities) > 0
        assert report.credentials_evidence
        assert report.credentials_evidence[0].opportunity_title == "CMMC Program"
        assert report.credentials_evidence[0].lookup_status == "Matched"
        assert report.opportunity_extraction_status == "Parsed"
        assert report.opportunities_extracted_count == 1
        assert report.lookups_executed_count == 1
        assert report.credentials_batch_diagnostics is None
        assert report.credentials_lookup_mode == "serial_per_opportunity"
    
    @pytest.mark.asyncio
    async def test_progress_callback_receives_updates(
        self, orchestrator, sample_trigger
    ):
        """Progress callback should receive all status updates."""
        progress_messages = []
        
        async def capture_progress(msg):
            progress_messages.append(msg)
        
        await orchestrator.run(
            sample_trigger,
            deep_research_output=SAMPLE_DEEP_RESEARCH,
            progress_cb=capture_progress
        )
        
        # Should have received progress updates
        assert len(progress_messages) >= 3
        assert any("Deep Research" in msg for msg in progress_messages)
        assert any("opportunities" in msg.lower() for msg in progress_messages)
        assert any("Complete" in msg for msg in progress_messages)
    
    @pytest.mark.asyncio
    async def test_synchronous_progress_callback(
        self, orchestrator, sample_trigger
    ):
        """Should handle synchronous progress callbacks."""
        messages = []
        
        def sync_callback(msg):
            messages.append(msg)
        
        await orchestrator.run(
            sample_trigger,
            deep_research_output=SAMPLE_DEEP_RESEARCH,
            progress_cb=sync_callback
        )
        
        assert len(messages) >= 3


# =============================================================================
# Batched Credentials Lookup Tests
# =============================================================================

class TestBatchedCredentials:
    """Test single-call batched credentials lookup."""
    
    @pytest.mark.asyncio
    async def test_queries_multiple_opportunities(
        self, mock_extractor, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should query credentials for multiple opportunities."""
        # Setup extractor to return multiple opportunities
        mock_extractor.extract.return_value = DeepResearchOutput(
            executive_summary="Multiple opportunities",
            opportunities=[
                Opportunity(title=f"Opportunity {i}", scope="Test", confidence="Medium")
                for i in range(3)
            ]
        )
        
        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
            credentials_lookup_mode="batched_single_call",
        )
        
        await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        
        # Should have called credentials agent once with top 3
        mock_credentials_agent.find_credentials_batch.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handles_credentials_failure_gracefully(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        """Should continue if some credentials lookups fail."""
        # Setup credentials agent to fail on some calls
        failing_agent = MagicMock(spec=CredentialsAgent)
        failing_agent.find_credentials_batch = AsyncMock(return_value=(
            {
                "Opp 1": CredentialsResponse(opportunity_title="Opp 1", matches=[], no_matches_found=True, lookup_status="No Match"),
                "Opp 2": CredentialsResponse(opportunity_title="Opp 2", matches=[], no_matches_found=True, lookup_status="Lookup Failed", failure_reason="API Error"),
                "Opp 3": CredentialsResponse(opportunity_title="Opp 3", matches=[], no_matches_found=True, lookup_status="No Match"),
            },
            CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=3,
                lookup_count_returned=3,
                duration_ms=10.0,
                query_text="batch query text",
                raw_response_text='{"results":[]}',
                parse_outcome="batch_json_parsed",
            )
        ))
        
        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title=f"Opp {i}", scope="Test", confidence="Medium")
                for i in range(1, 4)
            ]
        )
        
        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=failing_agent,
            final_analyst=mock_final_analyst,
            credentials_lookup_mode="batched_single_call",
        )
        
        # Should not raise despite one failure
        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert report is not None

    @pytest.mark.asyncio
    async def test_batch_timeout_fallback_serial_diagnostics_propagate(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        """Should preserve status counts and diagnostics when batch lookup uses serial fallback."""
        fallback_agent = MagicMock(spec=CredentialsAgent)
        fallback_agent.find_credentials_batch = AsyncMock(return_value=(
            {
                "Opp 1": CredentialsResponse(
                    opportunity_title="Opp 1",
                    matches=[
                        CredentialMatch(
                            title="Cred 1",
                            client_challenge="Challenge",
                            value_provided="Value",
                            url="https://ishare.protiviti.com/cred/1",
                        )
                    ],
                    no_matches_found=False,
                    lookup_status="Matched",
                ),
                "Opp 2": CredentialsResponse(
                    opportunity_title="Opp 2",
                    matches=[],
                    no_matches_found=True,
                    lookup_status="No Match",
                ),
                "Opp 3": CredentialsResponse(
                    opportunity_title="Opp 3",
                    matches=[],
                    no_matches_found=True,
                    lookup_status="Lookup Failed",
                    failure_reason="Per-opportunity fallback lookup failed.",
                ),
            },
            CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=3,
                lookup_count_returned=3,
                duration_ms=1200.0,
                query_text="batch query text",
                raw_response_text="",
                parse_outcome="batch_timeout_fallback_serial",
                error_type="ContextFreeError",
                error_message="Batch credentials lookup timed out after retry; serial fallback executed.",
            )
        ))

        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title=f"Opp {i}", scope="Test", confidence="Medium")
                for i in range(1, 4)
            ]
        )

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=fallback_agent,
            final_analyst=mock_final_analyst,
            credentials_lookup_mode="batched_single_call",
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        assert report.credentials_batch_diagnostics is not None
        assert report.credentials_batch_diagnostics.parse_outcome == "batch_timeout_fallback_serial"
        assert report.credentials_status_counts["Matched"] == 1
        assert report.credentials_status_counts["No Match"] == 1
        assert report.credentials_status_counts["Lookup Failed"] == 1

    @pytest.mark.asyncio
    async def test_canonical_credentials_override_sparse_llm_and_clear_non_matches(
        self, mock_extractor, sample_trigger
    ):
        """Matched opportunities should always use canonical credentials; non-matches should be cleared."""
        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title="Opp Matched", scope="Matched scope", confidence="High"),
                Opportunity(title="Opp No Match", scope="No-match scope", confidence="Medium"),
            ]
        )

        credentials_agent = MagicMock(spec=CredentialsAgent)
        credentials_agent.find_credentials_batch = AsyncMock(return_value=(
            {
                "Opp Matched": CredentialsResponse(
                    opportunity_title="Opp Matched",
                    matches=[
                        CredentialMatch(
                            title="Canonical Rich Credential",
                            client_challenge="Needed deep compliance mapping",
                            approach="Delivered control gap remediation roadmap",
                            value_provided="Enabled bid readiness and reduced compliance risk",
                            industry="Defense",
                            technologies_used=["NIST 800-171", "CMMC"],
                            url="https://ishare.protiviti.com/cred/rich",
                        )
                    ],
                    no_matches_found=False,
                    lookup_status="Matched",
                    diagnostics=CredentialsLookupDiagnostics(
                        opportunity_title="Opp Matched",
                        sector="Defense",
                        query_text="batch query",
                        raw_response_text='{"results":[]}',
                        parse_outcome="batch_json_parsed_with_matches",
                        lookup_status="Matched",
                        duration_ms=10.0,
                        match_count=1,
                    ),
                ),
                "Opp No Match": CredentialsResponse(
                    opportunity_title="Opp No Match",
                    matches=[],
                    no_matches_found=True,
                    lookup_status="No Match",
                    diagnostics=CredentialsLookupDiagnostics(
                        opportunity_title="Opp No Match",
                        sector="Defense",
                        query_text="batch query",
                        raw_response_text='{"results":[]}',
                        parse_outcome="batch_json_parsed_no_match",
                        lookup_status="No Match",
                        duration_ms=10.0,
                        match_count=0,
                    ),
                ),
            },
            CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=2,
                lookup_count_returned=2,
                duration_ms=10.0,
                query_text="batch query text",
                raw_response_text='{"results":[]}',
                parse_outcome="batch_json_parsed",
            ),
        ))

        final_analyst = MagicMock(spec=FinalAnalystAgent)
        final_analyst.synthesize = AsyncMock(return_value=MDReport(
            trigger_summary="Defense credentials merge",
            executive_summary="Summary",
            top_opportunities=[
                MDReportOpportunity(
                    opportunity=Opportunity(
                        title="Opp Matched",
                        scope="Matched scope",
                        confidence="High",
                    ),
                    credentials=[
                        CredentialMatch(
                            title="Sparse LLM Stub",
                            client_challenge="",
                            approach="",
                            value_provided="",
                            industry="",
                            technologies_used=[],
                            url="https://stub",
                        )
                    ],
                    validation_status="Validated",
                    credentials_lookup_status="Matched",
                ),
                MDReportOpportunity(
                    opportunity=Opportunity(
                        title="Opp No Match",
                        scope="No-match scope",
                        confidence="Medium",
                    ),
                    credentials=[
                        CredentialMatch(
                            title="Hallucinated LLM Stub",
                            client_challenge="",
                            approach="",
                            value_provided="",
                            industry="",
                            technologies_used=[],
                            url="https://stub-no-match",
                        )
                    ],
                    validation_status="Validated",
                    credentials_lookup_status="Matched",
                ),
            ],
            signals_detected=[],
            recommended_actions=[],
            generated_at=datetime.now(),
            confidence_note="",
        ))

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=credentials_agent,
            final_analyst=final_analyst,
            credentials_lookup_mode="batched_single_call",
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        matched = next(opp for opp in report.top_opportunities if opp.opportunity.title == "Opp Matched")
        assert matched.credentials_lookup_status == "Matched"
        assert len(matched.credentials) == 1
        assert matched.credentials[0].title == "Canonical Rich Credential"
        assert matched.credentials[0].client_challenge == "Needed deep compliance mapping"
        assert matched.credentials[0].approach == "Delivered control gap remediation roadmap"
        assert matched.credentials[0].value_provided == "Enabled bid readiness and reduced compliance risk"

        no_match = next(opp for opp in report.top_opportunities if opp.opportunity.title == "Opp No Match")
        assert no_match.credentials_lookup_status == "No Match"
        assert no_match.credentials == []
        assert no_match.validation_status == "No Internal Data"

    @pytest.mark.asyncio
    async def test_skips_credentials_when_extraction_failed(
        self, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should fail fast and skip credentials when extraction status is Extraction Failed."""
        extractor = MagicMock(spec=OpportunityExtractor)
        extractor.extract.return_value = DeepResearchOutput(
            executive_summary="Narrative had opportunities but parse failed.",
            opportunities=[],
            extraction_diagnostics=OpportunityExtractionDiagnostics(
                status="Extraction Failed",
                reason="Signal-rich narrative could not be parsed into opportunity blocks.",
                opportunities_extracted_count=0,
                extraction_method="narrative_fallback",
                extraction_confidence="Low",
                candidate_signal_count=5
            )
        )
        orchestrator = BDOrchestrator(
            extractor=extractor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
            credentials_lookup_mode="batched_single_call",
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        mock_credentials_agent.find_credentials_batch.assert_not_called()
        assert report.opportunity_extraction_status == "Extraction Failed"
        assert report.lookups_executed_count == 0
        assert report.lookups_skipped_reason is not None

    @pytest.mark.asyncio
    async def test_uses_atlas_digest_when_enabled(
        self, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should prefer ATLAS-digested opportunities when enabled and available."""
        extractor = MagicMock(spec=OpportunityExtractor)
        extractor.extract.return_value = DeepResearchOutput(
            executive_summary="Narrative report",
            opportunities=[],
            extraction_diagnostics=OpportunityExtractionDiagnostics(
                status="Extraction Failed",
                reason="No structured blocks.",
                opportunities_extracted_count=0,
                extraction_method="section_structured",
                extraction_confidence="Low",
                candidate_signal_count=5,
            ),
        )

        digestor = MagicMock(spec=OpportunityDigestor)
        digestor.digest = AsyncMock(return_value=(
            [
                Opportunity(title="Digest Opp 1", scope="Scope 1", confidence="High"),
                Opportunity(title="Digest Opp 2", scope="Scope 2", confidence="Medium"),
            ],
            {"status": "Succeeded", "parse_outcome": "json_parsed_with_opportunities"},
        ))

        orchestrator = BDOrchestrator(
            extractor=extractor,
            opportunity_digestor=digestor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
            use_atlas_digestion=True,
            credentials_lookup_mode="batched_single_call",
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        digestor.digest.assert_called_once()
        mock_credentials_agent.find_credentials_batch.assert_called_once()
        assert report.opportunity_extraction_status == "Parsed"


# =============================================================================
# Serial Credentials Lookup Tests
# =============================================================================

class TestSerialCredentials:
    """Test serial-per-opportunity credentials lookup behavior."""

    @pytest.mark.asyncio
    async def test_serial_mode_calls_find_credentials_per_opportunity(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        serial_agent = MagicMock(spec=CredentialsAgent)
        serial_agent.find_credentials = AsyncMock(return_value=CredentialsResponse(
            opportunity_title="placeholder",
            matches=[],
            no_matches_found=True,
            lookup_status="No Match",
        ))
        serial_agent.find_credentials_batch = AsyncMock()

        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title=f"Opp {i}", scope="Scope", confidence="Medium")
                for i in range(1, 4)
            ]
        )

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=serial_agent,
            final_analyst=mock_final_analyst,
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert serial_agent.find_credentials.await_count == 3
        serial_agent.find_credentials_batch.assert_not_called()
        assert report.credentials_lookup_mode == "serial_per_opportunity"
        assert report.credentials_batch_diagnostics is None

    @pytest.mark.asyncio
    async def test_serial_mode_retries_once_on_timeout_like_failure(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        serial_agent = MagicMock(spec=CredentialsAgent)
        serial_agent.find_credentials_batch = AsyncMock()
        serial_agent.find_credentials = AsyncMock(side_effect=[
            CredentialsResponse(
                opportunity_title="Opp 1",
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Request timed out. Service may be unavailable.",
                diagnostics=CredentialsLookupDiagnostics(
                    opportunity_title="Opp 1",
                    sector="Defense",
                    query_text="q",
                    raw_response_text="",
                    parse_outcome="lookup_failed",
                    lookup_status="Lookup Failed",
                    error_type="ContextFreeError",
                    error_message="Request timed out. Service may be unavailable.",
                    duration_ms=1.0,
                    match_count=0,
                ),
            ),
            CredentialsResponse(
                opportunity_title="Opp 1",
                matches=[
                    CredentialMatch(
                        title="Cred",
                        client_challenge="c",
                        value_provided="v",
                        url="https://ishare.protiviti.com/cred/1",
                    )
                ],
                no_matches_found=False,
                lookup_status="Matched",
            ),
        ])

        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[Opportunity(title="Opp 1", scope="Scope", confidence="High")]
        )

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=serial_agent,
            final_analyst=mock_final_analyst,
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert serial_agent.find_credentials.await_count == 2
        serial_agent.find_credentials_batch.assert_not_called()
        assert report.credentials_status_counts["Matched"] == 1

    @pytest.mark.asyncio
    async def test_serial_mode_retries_once_on_network_resolution_failure(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        serial_agent = MagicMock(spec=CredentialsAgent)
        serial_agent.find_credentials_batch = AsyncMock()
        serial_agent.find_credentials = AsyncMock(side_effect=[
            CredentialsResponse(
                opportunity_title="Opp 1",
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Request failed: [Errno 11001] getaddrinfo failed",
                diagnostics=CredentialsLookupDiagnostics(
                    opportunity_title="Opp 1",
                    sector="Defense",
                    query_text="q",
                    raw_response_text="",
                    parse_outcome="lookup_failed",
                    lookup_status="Lookup Failed",
                    error_type="ContextFreeError",
                    error_message="Request failed: [Errno 11001] getaddrinfo failed",
                    duration_ms=1.0,
                    match_count=0,
                ),
            ),
            CredentialsResponse(
                opportunity_title="Opp 1",
                matches=[
                    CredentialMatch(
                        title="Cred",
                        client_challenge="c",
                        value_provided="v",
                        url="https://ishare.protiviti.com/cred/1",
                    )
                ],
                no_matches_found=False,
                lookup_status="Matched",
            ),
        ])

        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[Opportunity(title="Opp 1", scope="Scope", confidence="High")]
        )

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=serial_agent,
            final_analyst=mock_final_analyst,
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert serial_agent.find_credentials.await_count == 2
        serial_agent.find_credentials_batch.assert_not_called()
        assert report.credentials_status_counts["Matched"] == 1

    @pytest.mark.asyncio
    async def test_serial_mode_partial_failure_does_not_fail_all(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        serial_agent = MagicMock(spec=CredentialsAgent)
        serial_agent.find_credentials_batch = AsyncMock()
        serial_agent.find_credentials = AsyncMock(side_effect=[
            CredentialsResponse(
                opportunity_title="Opp 1",
                matches=[
                    CredentialMatch(
                        title="Cred 1",
                        client_challenge="c1",
                        value_provided="v1",
                        url="https://ishare.protiviti.com/cred/1",
                    )
                ],
                no_matches_found=False,
                lookup_status="Matched",
            ),
            CredentialsResponse(
                opportunity_title="Opp 2",
                matches=[],
                no_matches_found=True,
                lookup_status="Lookup Failed",
                failure_reason="Auth error",
            ),
            CredentialsResponse(
                opportunity_title="Opp 3",
                matches=[],
                no_matches_found=True,
                lookup_status="No Match",
            ),
        ])

        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title="Opp 1", scope="Scope", confidence="High"),
                Opportunity(title="Opp 2", scope="Scope", confidence="Medium"),
                Opportunity(title="Opp 3", scope="Scope", confidence="Low"),
            ]
        )

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=serial_agent,
            final_analyst=mock_final_analyst,
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert serial_agent.find_credentials.await_count == 3
        assert report.credentials_status_counts == {"Matched": 1, "No Match": 1, "Lookup Failed": 1}

    @pytest.mark.asyncio
    async def test_batched_mode_still_works_when_explicitly_selected(
        self, mock_extractor, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
            credentials_lookup_mode="batched_single_call",
        )

        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        mock_credentials_agent.find_credentials_batch.assert_called_once()
        assert report.credentials_lookup_mode == "batched_single_call"
        assert report.credentials_batch_diagnostics is not None


# =============================================================================
# Trace File Tests
# =============================================================================

class TestTraceFiles:
    """Test trace file saving."""
    
    @pytest.mark.asyncio
    async def test_saves_trace_file(
        self, mock_extractor, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should save trace file to configured directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            traces_dir = Path(tmpdir) / "traces"
            
            orchestrator = BDOrchestrator(
                extractor=mock_extractor,
                credentials_agent=mock_credentials_agent,
                final_analyst=mock_final_analyst,
                traces_dir=traces_dir,
                credentials_lookup_mode="batched_single_call",
            )
            
            await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
            
            # Check trace file exists
            trace_files = list(traces_dir.glob("bd_run_*.json"))
            assert len(trace_files) == 1
            
            # Verify trace content
            trace_data = json.loads(trace_files[0].read_text())
            assert "timestamp" in trace_data
            assert trace_data["trigger"]["sector"] == "Defense"
            assert "duration_seconds" in trace_data
            assert trace_data["opportunity_extraction_status"] == "Parsed"
            assert trace_data["opportunities_extracted_count"] == 1
            assert trace_data["lookups_executed_count"] == 1
            assert trace_data["lookups_skipped_reason"] is None
            assert "credentials_status_counts" in trace_data
            assert "credentials_diagnostics" in trace_data
            assert trace_data["credentials_status_counts"]["Matched"] == 1
            assert trace_data["credentials_status_counts"]["No Match"] == 0
            assert trace_data["credentials_status_counts"]["Lookup Failed"] == 0
            assert len(trace_data["credentials_diagnostics"]) == 1
            assert trace_data["credentials_diagnostics"][0]["query_text"] == "full query text"
            assert trace_data["credentials_batch_diagnostics"]["parse_outcome"] == "batch_json_parsed"
            assert trace_data["credentials_lookup_mode"] == "batched_single_call"
            assert trace_data["synthesis_status"] == "synthesized"
            assert trace_data["synthesis_fallback_reason"] is None
    
    @pytest.mark.asyncio
    async def test_trace_includes_errors(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        """Trace should include any errors encountered."""
        # Setup failing credentials agent
        failing_agent = MagicMock(spec=CredentialsAgent)
        failing_agent.find_credentials_batch = AsyncMock(return_value=(
            {
                "Test": CredentialsResponse(
                    opportunity_title="Test",
                    matches=[],
                    no_matches_found=True,
                    lookup_status="Lookup Failed",
                    failure_reason="Test error",
                    diagnostics=CredentialsLookupDiagnostics(
                        opportunity_title="Test",
                        sector="Defense",
                        query_text="batch query",
                        raw_response_text="",
                        parse_outcome="batch_lookup_failed:Exception",
                        lookup_status="Lookup Failed",
                        error_message="Test error",
                        duration_ms=1.0,
                        match_count=0,
                    ),
                )
            },
            CredentialsBatchDiagnostics(
                invoked=True,
                lookup_count_requested=1,
                lookup_count_returned=0,
                duration_ms=1.0,
                query_text="batch query",
                raw_response_text="",
                parse_outcome="batch_lookup_failed",
                error_type="Exception",
                error_message="Test error",
            )
        ))
        
        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[Opportunity(title="Test", scope="Test", confidence="Low")]
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            traces_dir = Path(tmpdir) / "traces"
            
            orchestrator = BDOrchestrator(
                extractor=mock_extractor,
                credentials_agent=failing_agent,
                final_analyst=mock_final_analyst,
                traces_dir=traces_dir,
                credentials_lookup_mode="batched_single_call",
            )
            
            await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
            
            trace_files = list(traces_dir.glob("bd_run_*.json"))
            trace_data = json.loads(trace_files[0].read_text())
            
            assert trace_data["credentials_batch_diagnostics"]["error_message"] == "Test error"
            assert trace_data["lookups_executed_count"] == 1
            assert trace_data["credentials_status_counts"]["Lookup Failed"] == 1
            assert trace_data["credentials_lookup_failed"] == 1
            assert trace_data["credentials_diagnostics"][0]["lookup_status"] == "Lookup Failed"


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_handles_empty_research_output(
        self, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should handle empty Deep Research output."""
        empty_extractor = MagicMock(spec=OpportunityExtractor)
        empty_extractor.extract.return_value = DeepResearchOutput()
        
        orchestrator = BDOrchestrator(
            extractor=empty_extractor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst
        )
        
        report = await orchestrator.run(sample_trigger, deep_research_output="")
        
        # Should still produce a report
        assert report is not None
        mock_credentials_agent.find_credentials_batch.assert_not_called()
        mock_credentials_agent.find_credentials.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_limits_opportunities_to_top_three(
        self, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should only query credentials for top 3 opportunities in one batch call."""
        many_opps_extractor = MagicMock(spec=OpportunityExtractor)
        many_opps_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title=f"Opp {i}", scope="Test", confidence="Medium")
                for i in range(10)
            ]
        )
        
        orchestrator = BDOrchestrator(
            extractor=many_opps_extractor,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst
        )
        
        await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        
        # Serial default should execute per-opportunity top 3 lookups.
        assert mock_credentials_agent.find_credentials.await_count == 3
        mock_credentials_agent.find_credentials_batch.assert_not_called()


class TestFSSignalEvidenceMode:
    """Validate FS-first evidence lock path without regressing non-FS behavior."""

    @pytest.mark.asyncio
    async def test_financial_services_uses_fs_signal_digest_and_deriver(
        self, mock_extractor, mock_credentials_agent, mock_final_analyst
    ):
        fs_trigger = BDTrigger(
            sector="Financial Services",
            signals=["FS.EXEC.TRANSITION"],
            company_focus="Capital One",
            geography="US",
        )

        mock_extractor.extract.return_value = DeepResearchOutput(
            executive_summary="FS summary",
            opportunities=[],
            raw_citations=[
                "https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"
            ],
        )

        mock_digestor = MagicMock(spec=FSSignalEvidenceDigestor)
        mock_digestor.digest = AsyncMock(return_value=(
            [
                SignalEvidence(
                    signal_code="FS.EXEC.TRANSITION",
                    signal_label="Executive Transition",
                    status="Confirmed",
                    evidence_quote="Capital One appointed ... Business Chief Risk Officer ...",
                    source_url="https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro",
                    source_title="FinTech Magazine",
                    analysis="Governance alignment signal.",
                )
            ],
            {"status": "Succeeded", "parse_outcome": "json_parsed_with_signal_evidence"},
            ["https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"],
        ))

        mock_deriver = MagicMock(spec=FSOpportunityDeriver)
        mock_deriver.derive.return_value = [
            PhaseOpportunity(
                derived_from_signal="FS.EXEC.TRANSITION",
                overview="Governance-alignment opportunity.",
                technical_explanation="Define operating model and controls.",
                layman_explanation="Set guardrails early.",
                relevant_service_lines=["Risk governance advisory"],
                credentials_summary="No materially aligned credentials identified.",
                recommended_actions=["Run governance workshop within the next 30-90 days."],
                sources=["https://fintechmagazine.com/banking/capital-one-announces-appointment-of-global-payments-network-business-cro"],
            )
        ]

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            fs_signal_evidence_digestor=mock_digestor,
            fs_opportunity_deriver=mock_deriver,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
        )

        report = await orchestrator.run(fs_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        mock_digestor.digest.assert_called_once()
        mock_deriver.derive.assert_called_once()
        assert report.opportunities_source == "fs_signal_derivation"
        assert report.opportunities_extracted_count == 1

    @pytest.mark.asyncio
    async def test_non_financial_services_skips_fs_signal_digest(
        self, mock_extractor, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        mock_extractor.extract.return_value = DeepResearchOutput(
            executive_summary="Defense summary",
            opportunities=[Opportunity(title="Opp 1", scope="Scope", confidence="High")],
        )

        mock_digestor = MagicMock(spec=FSSignalEvidenceDigestor)
        mock_digestor.digest = AsyncMock(return_value=([], {}, []))
        mock_deriver = MagicMock(spec=FSOpportunityDeriver)
        mock_deriver.derive.return_value = []

        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            fs_signal_evidence_digestor=mock_digestor,
            fs_opportunity_deriver=mock_deriver,
            credentials_agent=mock_credentials_agent,
            final_analyst=mock_final_analyst,
        )

        await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)

        mock_digestor.digest.assert_not_called()
        mock_deriver.derive.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
