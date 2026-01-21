"""
Unit tests for CredentialsAgent.

All tests use mocked responses (no live API calls).
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.credentials_agent import CredentialsAgent, CREDENTIALS_QUERY_TEMPLATE
from services.contextfree_client import ContextFreeClient, ContextFreeError
from models.bd_schemas import Opportunity, CredentialMatch, CredentialsResponse


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_client():
    """Create a mock ContextFreeClient."""
    client = MagicMock(spec=ContextFreeClient)
    client.ask = AsyncMock()
    return client


@pytest.fixture
def agent(mock_client):
    """Create a CredentialsAgent with mock client."""
    return CredentialsAgent(
        contextfree_client=mock_client,
        gpt_endpoint="https://test-endpoint.com/api/asst_test"
    )


@pytest.fixture
def sample_opportunity():
    """Sample opportunity for testing."""
    return Opportunity(
        title="CMMC Assessment Program",
        agency="Department of Defense",
        scope="Provide CMMC Level 2 assessment services for defense contractors",
        estimated_value="$5M",
        timeline="FY2025",
        cmmc_level="Level 2",
        confidence="High",
        citations=["https://source1.com"]
    )


@pytest.fixture
def mock_credentials_json_response():
    """Mock JSON response with credentials."""
    return json.dumps({
        "matches": [
            {
                "title": "CMMC Readiness Assessment for Defense Manufacturer",
                "client_challenge": "Client needed to achieve CMMC Level 2 certification before contract deadline",
                "approach": "Conducted gap analysis and remediation planning",
                "value_provided": "Achieved certification 2 months ahead of schedule",
                "industry": "Defense",
                "technologies_used": ["NIST 800-171", "Security Controls"],
                "url": "https://ishare.protiviti.com/cred/123"
            },
            {
                "title": "Cybersecurity Program for Aerospace Company",
                "client_challenge": "Improve security posture for government contracting",
                "approach": "Implemented comprehensive security framework",
                "value_provided": "Passed security audits with zero findings",
                "industry": "Aerospace",
                "technologies_used": ["CMMC", "FedRAMP"],
                "url": "https://ishare.protiviti.com/cred/456"
            }
        ],
        "no_matches_found": False
    })


@pytest.fixture
def mock_no_matches_response():
    """Mock response when no credentials found."""
    return json.dumps({
        "matches": [],
        "no_matches_found": True
    })


# =============================================================================
# Query Building Tests
# =============================================================================

class TestQueryBuilding:
    """Test prompt query construction."""
    
    def test_builds_query_with_opportunity_details(self, agent, sample_opportunity):
        """Query should include opportunity title, scope, and requirements."""
        query = agent._build_query(sample_opportunity, sector="Defense")
        
        assert "CMMC Assessment Program" in query
        assert "CMMC Level 2 assessment services" in query
        assert "Defense" in query
        assert "CMMC Level 2" in query
    
    def test_extracts_requirements_from_scope(self, agent):
        """Should extract technology keywords from scope."""
        opp = Opportunity(
            title="Cloud Security Assessment",
            scope="Cloud cybersecurity compliance and risk management services",
            confidence="Medium"
        )
        query = agent._build_query(opp, sector="Technology")
        
        assert "Cybersecurity" in query
        assert "Cloud" in query
        assert "Compliance" in query
        assert "Risk Management" in query
    
    def test_handles_minimal_opportunity(self, agent):
        """Should handle opportunity with minimal fields."""
        opp = Opportunity(
            title="Basic Opportunity",
            scope="General consulting services",
            confidence="Low"
        )
        query = agent._build_query(opp, sector="General")
        
        assert "Basic Opportunity" in query
        assert "N/A" in query or "General consulting" in query


# =============================================================================
# Response Parsing Tests
# =============================================================================

class TestResponseParsing:
    """Test GPT response parsing."""
    
    def test_parses_json_response(self, agent, mock_credentials_json_response):
        """Should parse valid JSON response."""
        result = agent._parse_response(mock_credentials_json_response, "Test Opportunity")
        
        assert result.opportunity_title == "Test Opportunity"
        assert len(result.matches) == 2
        assert result.no_matches_found == False
        
        # Check first credential
        first = result.matches[0]
        assert first.title == "CMMC Readiness Assessment for Defense Manufacturer"
        assert "Level 2 certification" in first.client_challenge
        assert "ishare.protiviti.com" in first.url
    
    def test_parses_no_matches_response(self, agent, mock_no_matches_response):
        """Should parse 'no matches' response correctly."""
        result = agent._parse_response(mock_no_matches_response, "Test Opportunity")
        
        assert len(result.matches) == 0
        assert result.no_matches_found == True
    
    def test_handles_markdown_code_block(self, agent, mock_credentials_json_response):
        """Should extract JSON from markdown code blocks."""
        markdown_wrapped = f"```json\n{mock_credentials_json_response}\n```"
        
        result = agent._parse_response(markdown_wrapped, "Test Opportunity")
        
        assert len(result.matches) == 2
    
    def test_handles_natural_language_no_results(self, agent):
        """Should detect 'no matching credentials' in natural language."""
        natural_response = "I could not find any matching credentials for this opportunity."
        
        result = agent._parse_response(natural_response, "Test Opportunity")
        
        assert result.no_matches_found == True
        assert len(result.matches) == 0
    
    def test_handles_empty_response(self, agent):
        """Should handle empty response gracefully."""
        result = agent._parse_response("", "Test Opportunity")
        
        assert result.no_matches_found == True
        assert len(result.matches) == 0
    
    def test_handles_malformed_json(self, agent):
        """Should handle malformed JSON gracefully."""
        result = agent._parse_response("{invalid json", "Test Opportunity")
        
        assert result.no_matches_found == True


# =============================================================================
# Integration Tests (with mocks)
# =============================================================================

class TestCredentialsLookup:
    """Test full credentials lookup flow."""
    
    @pytest.mark.asyncio
    async def test_successful_lookup(self, agent, mock_client, sample_opportunity, mock_credentials_json_response):
        """Should return credentials on successful lookup."""
        mock_client.ask.return_value = mock_credentials_json_response
        
        result = await agent.find_credentials(sample_opportunity, sector="Defense")
        
        # Verify API was called correctly
        mock_client.ask.assert_called_once()
        call_args = mock_client.ask.call_args
        assert "CMMC Assessment Program" in call_args.args[0]
        assert call_args.args[1] == "https://test-endpoint.com/api/asst_test"
        
        # Verify result
        assert len(result.matches) == 2
        assert result.no_matches_found == False
    
    @pytest.mark.asyncio
    async def test_handles_api_error(self, agent, mock_client, sample_opportunity):
        """Should return graceful failure on API error."""
        mock_client.ask.side_effect = ContextFreeError("API unavailable")
        
        result = await agent.find_credentials(sample_opportunity, sector="Defense")
        
        # Should return empty result, not raise
        assert result.no_matches_found == True
        assert len(result.matches) == 0
        assert result.opportunity_title == "CMMC Assessment Program"
    
    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self, agent, mock_client, sample_opportunity):
        """Should handle unexpected exceptions gracefully."""
        mock_client.ask.side_effect = Exception("Unexpected error")
        
        result = await agent.find_credentials(sample_opportunity, sector="Defense")
        
        assert result.no_matches_found == True
        assert len(result.matches) == 0


# =============================================================================
# No Matches Detection Tests
# =============================================================================

class TestNoMatchesDetection:
    """Test detection of 'no credentials found' scenarios."""
    
    @pytest.mark.asyncio
    async def test_explicit_no_matches_flag(self, agent, mock_client, sample_opportunity, mock_no_matches_response):
        """Should respect explicit no_matches_found flag."""
        mock_client.ask.return_value = mock_no_matches_response
        
        result = await agent.find_credentials(sample_opportunity)
        
        assert result.no_matches_found == True
    
    @pytest.mark.asyncio
    async def test_infers_no_matches_from_empty_array(self, agent, mock_client, sample_opportunity):
        """Should infer no matches from empty matches array."""
        mock_client.ask.return_value = json.dumps({"matches": []})
        
        result = await agent.find_credentials(sample_opportunity)
        
        assert result.no_matches_found == True
    
    def test_detects_no_matches_phrases(self, agent):
        """Should detect common 'no matches' phrases in natural language."""
        phrases = [
            "No matching credentials found for this opportunity.",
            "I was unable to find any relevant credentials.",
            "Could not find any credentials matching the requirements."
        ]
        
        for phrase in phrases:
            result = agent._parse_response(phrase, "Test")
            assert result.no_matches_found == True, f"Failed for: {phrase}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
