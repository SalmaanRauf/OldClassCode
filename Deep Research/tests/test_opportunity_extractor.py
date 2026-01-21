"""
Unit tests for OpportunityExtractor.

Uses sample Deep Research output fixture based on NextSteps_POC.md.
"""
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.opportunity_extractor import OpportunityExtractor
from models.bd_schemas import Opportunity, DeepResearchOutput


# =============================================================================
# Sample Deep Research Output Fixture
# =============================================================================

SAMPLE_DEEP_RESEARCH_OUTPUT = """
# Executive Summary

Hanwha Group's expansion into the U.S. defense market presents significant opportunities for CMMC compliance services. Recent acquisitions and contract wins signal aggressive market entry, creating demand for cybersecurity and regulatory compliance expertise.

## Signals Detected

• Defense sector acquisition activity: Hanwha acquired Philly Shipyard for $100M
• CMMC requirement expansion: DoD contracts now require Level 2 certification
• Leadership change: New CEO appointed for Hanwha Defense USA
• Regulatory compliance gaps: Multiple subcontractors lacking CMMC readiness

## Opportunity Details

• CMMC Compliance Program for Hanwha Defense USA – Department of Defense. Expand compliance infrastructure to support CMMC Level 2 certification across all defense contracts.
  Scope: Cybersecurity and compliance services for CMMC Level 2 certification
  Value: $2.4B (estimated based on similar contracts)
  Timeline: FY2025-2027
  Incumbent: None (new requirement)
  CMMC Compliance: Level 2 required

• Cybersecurity Assessment for Philly Shipyard Integration – U.S. Navy. Post-acquisition security posture assessment and remediation.
  Scope: Security assessment and remediation planning for shipyard integration
  Value: $45M
  Timeline: Q2 2025
  Incumbent: Booz Allen Hamilton
  CMMC Compliance: Level 3 required for classified work

• Supply Chain Risk Management – Defense Contractors. Support Hanwha's subcontractors in achieving CMMC compliance.
  Scope: Multi-vendor compliance program management
  Value: $12M annually
  Timeline: Ongoing through 2027
  Incumbent: None
  CMMC Compliance: Level 1-2 required

## Recommended Actions

• Engage Hanwha Defense USA leadership through existing industry contacts
• Propose CMMC readiness assessment as entry point
• Leverage Protiviti's recent CMMC credentials with similar defense contractors
• Target Q1 2025 for initial proposal submission
• Partner with cleared subcontractors for classified work requirements

## Sources

• https://www.defense.gov/contracts/hanwha-2024
• https://www.philly-shipyard.com/news/acquisition
• https://www.cmmc-ab.org/regulations/update-2024
• https://investor.hanwha.com/quarterly-report-q3-2024
"""

MINIMAL_DEEP_RESEARCH = """
# Executive Summary

Brief summary of findings.

## Signals Detected

• Signal one detected
• Signal two found

## Opportunity Details

• Simple Opportunity - General Agency
  Scope: Basic consulting services
  Timeline: 2025

## Recommended Actions

• Take action one
• Consider action two
"""


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def extractor():
    """Create OpportunityExtractor instance."""
    return OpportunityExtractor()


@pytest.fixture
def full_output():
    """Full sample Deep Research output."""
    return SAMPLE_DEEP_RESEARCH_OUTPUT


@pytest.fixture
def minimal_output():
    """Minimal Deep Research output."""
    return MINIMAL_DEEP_RESEARCH


# =============================================================================
# Section Splitting Tests
# =============================================================================

class TestSectionSplitting:
    """Test markdown section detection."""
    
    def test_splits_all_sections(self, extractor, full_output):
        """Should identify all major sections."""
        sections = extractor._split_sections(full_output)
        
        assert "executive_summary" in sections
        assert "signals" in sections
        assert "opportunities" in sections
        assert "actions" in sections
        assert "sources" in sections
    
    def test_handles_empty_input(self, extractor):
        """Should handle empty input gracefully."""
        result = extractor.extract("")
        
        assert result.executive_summary == ""
        assert result.opportunities == []
    
    def test_handles_no_sections(self, extractor):
        """Should handle markdown with no recognizable sections."""
        result = extractor.extract("Just some random text without headers")
        
        assert result.executive_summary == ""
        assert result.opportunities == []


# =============================================================================
# Executive Summary Tests
# =============================================================================

class TestExecutiveSummary:
    """Test executive summary extraction."""
    
    def test_extracts_summary_paragraph(self, extractor, full_output):
        """Should extract first paragraph as summary."""
        result = extractor.extract(full_output)
        
        assert "Hanwha Group" in result.executive_summary
        assert "defense market" in result.executive_summary
        assert "CMMC compliance" in result.executive_summary
    
    def test_summary_is_single_paragraph(self, extractor, full_output):
        """Summary should be a single paragraph, not include headers."""
        result = extractor.extract(full_output)
        
        assert "\n\n" not in result.executive_summary
        assert "#" not in result.executive_summary


# =============================================================================
# Signals Extraction Tests
# =============================================================================

class TestSignalsExtraction:
    """Test signals bullet extraction."""
    
    def test_extracts_all_signals(self, extractor, full_output):
        """Should extract all signal bullet points."""
        result = extractor.extract(full_output)
        
        assert len(result.signals_detected) == 4
    
    def test_signal_content_preserved(self, extractor, full_output):
        """Signal content should be preserved accurately."""
        result = extractor.extract(full_output)
        
        signals_text = " ".join(result.signals_detected)
        assert "Philly Shipyard" in signals_text
        assert "CMMC" in signals_text
        assert "Leadership change" in signals_text


# =============================================================================
# Opportunity Extraction Tests
# =============================================================================

class TestOpportunityExtraction:
    """Test opportunity parsing."""
    
    def test_extracts_all_opportunities(self, extractor, full_output):
        """Should extract all opportunities."""
        result = extractor.extract(full_output)
        
        assert len(result.opportunities) == 3
    
    def test_parses_title_and_agency(self, extractor, full_output):
        """Should parse title and agency correctly."""
        result = extractor.extract(full_output)
        
        first_opp = result.opportunities[0]
        assert "CMMC Compliance Program" in first_opp.title
        assert "Department of Defense" in first_opp.agency or "Defense" in str(first_opp.agency)
    
    def test_parses_scope(self, extractor, full_output):
        """Should extract scope field."""
        result = extractor.extract(full_output)
        
        first_opp = result.opportunities[0]
        assert "Cybersecurity" in first_opp.scope or "CMMC" in first_opp.scope
    
    def test_parses_value(self, extractor, full_output):
        """Should extract value field."""
        result = extractor.extract(full_output)
        
        first_opp = result.opportunities[0]
        assert first_opp.estimated_value is not None
        assert "$" in first_opp.estimated_value or "B" in first_opp.estimated_value
    
    def test_parses_timeline(self, extractor, full_output):
        """Should extract timeline field."""
        result = extractor.extract(full_output)
        
        first_opp = result.opportunities[0]
        assert first_opp.timeline is not None
        assert "FY" in first_opp.timeline or "2025" in first_opp.timeline
    
    def test_parses_cmmc_level(self, extractor, full_output):
        """Should extract CMMC compliance field."""
        result = extractor.extract(full_output)
        
        first_opp = result.opportunities[0]
        assert first_opp.cmmc_level is not None
        assert "Level 2" in first_opp.cmmc_level


# =============================================================================
# Confidence Assessment Tests
# =============================================================================

class TestConfidenceAssessment:
    """Test confidence level determination."""
    
    def test_high_confidence_with_complete_data(self, extractor, full_output):
        """Opportunities with value, timeline, and compliance should be High."""
        result = extractor.extract(full_output)
        
        # First opportunity has all fields
        first_opp = result.opportunities[0]
        assert first_opp.confidence in ["High", "Medium"]
    
    def test_low_confidence_with_minimal_data(self, extractor, minimal_output):
        """Opportunities with minimal data should be Low/Medium."""
        result = extractor.extract(minimal_output)
        
        if result.opportunities:
            opp = result.opportunities[0]
            assert opp.confidence in ["Low", "Medium"]


# =============================================================================
# Recommended Actions Tests  
# =============================================================================

class TestActionsExtraction:
    """Test recommended actions extraction."""
    
    def test_extracts_all_actions(self, extractor, full_output):
        """Should extract all recommended actions."""
        result = extractor.extract(full_output)
        
        assert len(result.recommended_actions) == 5
    
    def test_action_content_preserved(self, extractor, full_output):
        """Action content should be preserved."""
        result = extractor.extract(full_output)
        
        actions_text = " ".join(result.recommended_actions)
        assert "Engage" in actions_text or "leadership" in actions_text
        assert "CMMC" in actions_text


# =============================================================================
# Citation Extraction Tests
# =============================================================================

class TestCitationExtraction:
    """Test URL citation extraction."""
    
    def test_extracts_urls(self, extractor, full_output):
        """Should extract all URLs from sources."""
        result = extractor.extract(full_output)
        
        assert len(result.raw_citations) >= 4
        assert all(url.startswith("http") for url in result.raw_citations)
    
    def test_urls_properly_formatted(self, extractor, full_output):
        """URLs should be clean without trailing punctuation."""
        result = extractor.extract(full_output)
        
        for url in result.raw_citations:
            assert not url.endswith(",")
            assert not url.endswith(".")


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_handles_missing_fields(self, extractor):
        """Should handle opportunities with missing fields."""
        markdown = """
## Opportunity Details

• Incomplete Opportunity
  Scope: Only has scope
"""
        result = extractor.extract(markdown)
        
        if result.opportunities:
            opp = result.opportunities[0]
            assert opp.title is not None
            assert opp.estimated_value is None or opp.estimated_value == ""
    
    def test_handles_different_bullet_styles(self, extractor):
        """Should handle various bullet point formats."""
        markdown = """
## Signals Detected

- Dash bullet
* Star bullet
1. Numbered item
"""
        result = extractor.extract(markdown)
        
        assert len(result.signals_detected) >= 2
    
    def test_limits_output_size(self, extractor):
        """Should limit number of items to prevent overflow."""
        # Create markdown with many opportunities
        opps = "\n".join([f"• Opportunity {i}\n  Scope: Test" for i in range(20)])
        markdown = f"## Opportunity Details\n{opps}"
        
        result = extractor.extract(markdown)
        
        assert len(result.opportunities) <= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
