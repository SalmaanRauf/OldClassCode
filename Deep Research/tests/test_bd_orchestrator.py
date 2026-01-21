"""
Integration tests for BDOrchestrator.

Uses mocked components to test the full workflow without live API calls.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from pathlib import Path
import json
import tempfile

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bd_orchestrator import BDOrchestrator
from services.opportunity_extractor import OpportunityExtractor
from agents.credentials_agent import CredentialsAgent
from agents.final_analyst_agent import FinalAnalystAgent
from models.bd_schemas import (
    BDTrigger,
    Opportunity,
    DeepResearchOutput,
    CredentialsResponse,
    CredentialMatch,
    MDReport,
    MDReportOpportunity
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
        no_matches_found=False
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
                validation_status="Validated"
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
        mock_credentials_agent.find_credentials.assert_called()
        mock_final_analyst.synthesize.assert_called_once()
        
        # Verify report
        assert report is not None
        assert report.trigger_summary == "Defense CMMC analysis"
        assert len(report.top_opportunities) > 0
    
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
# Parallel Credentials Lookup Tests
# =============================================================================

class TestParallelCredentials:
    """Test parallel credentials lookup."""
    
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
            final_analyst=mock_final_analyst
        )
        
        await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        
        # Should have called credentials agent 3 times
        assert mock_credentials_agent.find_credentials.call_count == 3
    
    @pytest.mark.asyncio
    async def test_handles_credentials_failure_gracefully(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        """Should continue if some credentials lookups fail."""
        # Setup credentials agent to fail on some calls
        failing_agent = MagicMock(spec=CredentialsAgent)
        failing_agent.find_credentials = AsyncMock(
            side_effect=[
                CredentialsResponse(opportunity_title="Opp 1", matches=[], no_matches_found=False),
                Exception("API Error"),
                CredentialsResponse(opportunity_title="Opp 3", matches=[], no_matches_found=True)
            ]
        )
        
        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[
                Opportunity(title=f"Opp {i}", scope="Test", confidence="Medium")
                for i in range(1, 4)
            ]
        )
        
        orchestrator = BDOrchestrator(
            extractor=mock_extractor,
            credentials_agent=failing_agent,
            final_analyst=mock_final_analyst
        )
        
        # Should not raise despite one failure
        report = await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
        assert report is not None


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
                traces_dir=traces_dir
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
    
    @pytest.mark.asyncio
    async def test_trace_includes_errors(
        self, mock_extractor, mock_final_analyst, sample_trigger
    ):
        """Trace should include any errors encountered."""
        # Setup failing credentials agent
        failing_agent = MagicMock(spec=CredentialsAgent)
        failing_agent.find_credentials = AsyncMock(side_effect=Exception("Test error"))
        
        mock_extractor.extract.return_value = DeepResearchOutput(
            opportunities=[Opportunity(title="Test", scope="Test", confidence="Low")]
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            traces_dir = Path(tmpdir) / "traces"
            
            orchestrator = BDOrchestrator(
                extractor=mock_extractor,
                credentials_agent=failing_agent,
                final_analyst=mock_final_analyst,
                traces_dir=traces_dir
            )
            
            await orchestrator.run(sample_trigger, deep_research_output=SAMPLE_DEEP_RESEARCH)
            
            trace_files = list(traces_dir.glob("bd_run_*.json"))
            trace_data = json.loads(trace_files[0].read_text())
            
            assert len(trace_data["errors"]) > 0
            assert "Test error" in trace_data["errors"][0]


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
        mock_credentials_agent.find_credentials.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_limits_opportunities_to_five(
        self, mock_credentials_agent, mock_final_analyst, sample_trigger
    ):
        """Should only query credentials for top 5 opportunities."""
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
        
        # Should only call 5 times (top 5)
        assert mock_credentials_agent.find_credentials.call_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
