"""
Unit tests for CredentialsAgent.

All tests use mocked responses (no live API calls).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.credentials_agent import CredentialsAgent
from services.contextfree_client import ContextFreeClient, ContextFreeError
from models.bd_schemas import Opportunity


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

    def test_normalizes_numeric_cmmc_level(self, agent):
        """Numeric CMMC level should render as canonical 'CMMC Level X'."""
        opp = Opportunity(
            title="Numeric CMMC",
            scope="General services",
            cmmc_level="2",
            confidence="Medium",
        )
        assert agent._extract_requirements(opp) == "CMMC Level 2"

    def test_normalizes_level_prefixed_cmmc_level(self, agent):
        """'Level X' should render as canonical 'CMMC Level X'."""
        opp = Opportunity(
            title="Level Prefixed CMMC",
            scope="General services",
            cmmc_level="Level 2",
            confidence="Medium",
        )
        assert agent._extract_requirements(opp) == "CMMC Level 2"

    def test_normalizes_cmmc_level_with_suffix(self, agent):
        """Numeric levels with suffixes should preserve suffix while normalizing prefix."""
        opp = Opportunity(
            title="Suffixed CMMC",
            scope="General services",
            cmmc_level="2 (Self-Assessment)",
            confidence="Medium",
        )
        assert agent._extract_requirements(opp) == "CMMC Level 2 (Self-Assessment)"

    def test_normalizes_prefixed_numeric_cmmc_level(self, agent):
        """'CMMC X' should normalize to 'CMMC Level X'."""
        opp = Opportunity(
            title="Prefixed Numeric CMMC",
            scope="General services",
            cmmc_level="CMMC 2",
            confidence="Medium",
        )
        assert agent._extract_requirements(opp) == "CMMC Level 2"


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
        assert result.lookup_status == "Matched"
        assert result.failure_reason is None
        assert result.diagnostics is not None
        assert result.diagnostics.lookup_status == "Matched"
        assert result.diagnostics.match_count == 2
        assert result.diagnostics.raw_response_text == mock_credentials_json_response
        
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
        assert result.lookup_status == "No Match"
        assert result.failure_reason is None
        assert result.diagnostics is not None
        assert result.diagnostics.lookup_status == "No Match"
        assert result.diagnostics.match_count == 0
    
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
        assert result.lookup_status == "No Match"
        assert result.failure_reason is None
        assert result.diagnostics is not None
        assert result.diagnostics.parse_outcome == "natural_language_no_match"
    
    def test_handles_empty_response(self, agent):
        """Should handle empty response gracefully."""
        result = agent._parse_response("", "Test Opportunity")
        
        assert result.no_matches_found == True
        assert len(result.matches) == 0
        assert result.lookup_status == "No Match"
        assert result.failure_reason is None
        assert result.diagnostics is not None
        assert result.diagnostics.parse_outcome == "empty_response"
    
    def test_handles_malformed_json(self, agent):
        """Should handle malformed JSON gracefully."""
        result = agent._parse_response("{invalid json", "Test Opportunity")
        
        assert result.no_matches_found == True
        assert result.lookup_status == "Lookup Failed"
        assert result.failure_reason is not None
        assert result.diagnostics is not None
        assert result.diagnostics.parse_outcome == "json_parse_error"
        assert result.diagnostics.error_type == "JSONDecodeError"

    def test_single_parse_drops_invalid_url_match(self, agent):
        """Should drop invalid URL matches while preserving valid matches."""
        raw = json.dumps(
            {
                "matches": [
                    {
                        "title": "Invalid URL Credential",
                        "client_challenge": "Challenge",
                        "approach": "Approach",
                        "value_provided": "Value",
                        "industry": "Defense",
                        "technologies_used": [],
                        "url": "not-a-real-url",
                    },
                    {
                        "title": "Valid URL Credential",
                        "client_challenge": "Challenge 2",
                        "approach": "Approach 2",
                        "value_provided": "Value 2",
                        "industry": "Defense",
                        "technologies_used": [],
                        "url": "https://roberthalf.sharepoint.com/sites/iShare-Client-Credentials/SitePages/Credential-Details.aspx?itemid=821",
                    },
                ],
                "no_matches_found": False,
            }
        )

        result = agent._parse_response(raw, "Test Opportunity")
        assert result.lookup_status == "Matched"
        assert len(result.matches) == 1
        assert result.matches[0].title == "Valid URL Credential"
        assert result.diagnostics is not None
        assert result.diagnostics.parse_outcome == "json_parsed_with_matches_filtered_invalid_url"

    def test_single_parse_all_invalid_urls_results_no_match(self, agent):
        """Should return No Match when all parsed matches are filtered for invalid URLs."""
        raw = json.dumps(
            {
                "matches": [
                    {
                        "title": "Invalid Credential A",
                        "client_challenge": "Challenge",
                        "approach": "Approach",
                        "value_provided": "Value",
                        "industry": "Defense",
                        "technologies_used": [],
                        "url": "Hyp/NearSeriesAdjustNIST",
                    }
                ],
                "no_matches_found": False,
            }
        )

        result = agent._parse_response(raw, "Test Opportunity")
        assert result.lookup_status == "No Match"
        assert result.no_matches_found is True
        assert len(result.matches) == 0
        assert result.diagnostics is not None
        assert result.diagnostics.parse_outcome == "json_parsed_all_matches_filtered_invalid_url"
        assert "filtered_invalid_url_count=1" in (result.diagnostics.error_message or "")

    def test_single_parse_coerces_technologies_used_string(self, agent):
        raw = json.dumps(
            {
                "matches": [
                    {
                        "title": "Credential with string technologies",
                        "client_challenge": "Challenge",
                        "approach": "Approach",
                        "value_provided": "Value",
                        "industry": "Financial Services",
                        "technologies_used": "Not Specified",
                        "url": "https://roberthalf.sharepoint.com/sites/iShare-Client-Credentials/SitePages/Credential-Details.aspx?itemid=1732",
                    }
                ],
                "no_matches_found": False,
            }
        )

        result = agent._parse_response(raw, "Test Opportunity")

        assert result.lookup_status == "Matched"
        assert len(result.matches) == 1
        assert result.matches[0].technologies_used == []

    def test_single_parse_recovers_valid_json_with_trailing_malformed_text(self, agent):
        raw = (
            '{"matches":[{"title":"Recovered Credential","client_challenge":"Challenge",'
            '"approach":"Approach","value_provided":"Value","industry":"Financial Services",'
            '"technologies_used":[],"url":"https://ishare.protiviti.com/cred/recovered"}],'
            '"no_matches_found":false}\n'
            'Trailing content {that is not valid json'
        )

        result = agent._parse_response(raw, "Test Opportunity")

        assert result.lookup_status == "Matched"
        assert len(result.matches) == 1
        assert result.matches[0].title == "Recovered Credential"

    def test_single_parse_dedupes_duplicate_urls_and_caps_matches(self, agent):
        raw = json.dumps(
            {
                "matches": [
                    {
                        "title": "Credential 1",
                        "client_challenge": "Challenge 1",
                        "approach": "Approach 1",
                        "value_provided": "Value 1",
                        "industry": "Financial Services",
                        "technologies_used": [],
                        "url": "https://ishare.protiviti.com/cred/1",
                    },
                    {
                        "title": "Credential 1 Duplicate",
                        "client_challenge": "Challenge 1",
                        "approach": "Approach 1",
                        "value_provided": "Value 1",
                        "industry": "Financial Services",
                        "technologies_used": [],
                        "url": "https://ishare.protiviti.com/cred/1",
                    },
                    {
                        "title": "Credential 2",
                        "client_challenge": "Challenge 2",
                        "approach": "Approach 2",
                        "value_provided": "Value 2",
                        "industry": "Financial Services",
                        "technologies_used": [],
                        "url": "https://ishare.protiviti.com/cred/2",
                    },
                    {
                        "title": "Credential 3",
                        "client_challenge": "Challenge 3",
                        "approach": "Approach 3",
                        "value_provided": "Value 3",
                        "industry": "Financial Services",
                        "technologies_used": [],
                        "url": "https://ishare.protiviti.com/cred/3",
                    },
                    {
                        "title": "Credential 4",
                        "client_challenge": "Challenge 4",
                        "approach": "Approach 4",
                        "value_provided": "Value 4",
                        "industry": "Financial Services",
                        "technologies_used": [],
                        "url": "https://ishare.protiviti.com/cred/4",
                    },
                ],
                "no_matches_found": False,
            }
        )

        result = agent._parse_response(raw, "Test Opportunity")

        assert result.lookup_status == "Matched"
        assert len(result.matches) == 3
        urls = [match.url for match in result.matches]
        assert len(set(urls)) == 3
        assert "https://ishare.protiviti.com/cred/1" in urls
        assert "https://ishare.protiviti.com/cred/4" not in urls


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
        assert result.lookup_status == "Matched"
        assert result.failure_reason is None
        assert result.diagnostics is not None
        assert result.diagnostics.query_text
        assert result.diagnostics.raw_response_text == mock_credentials_json_response
        assert result.diagnostics.duration_ms >= 0.0
    
    @pytest.mark.asyncio
    async def test_handles_api_error(self, agent, mock_client, sample_opportunity):
        """Should return graceful failure on API error."""
        mock_client.ask.side_effect = ContextFreeError("API unavailable")
        
        result = await agent.find_credentials(sample_opportunity, sector="Defense")
        
        # Should return empty result, not raise
        assert result.no_matches_found == True
        assert len(result.matches) == 0
        assert result.opportunity_title == "CMMC Assessment Program"
        assert result.lookup_status == "Lookup Failed"
        assert result.failure_reason == "API unavailable"
        assert result.diagnostics is not None
        assert result.diagnostics.error_type == "ContextFreeError"
        assert result.diagnostics.parse_outcome == "lookup_failed"
    
    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self, agent, mock_client, sample_opportunity):
        """Should handle unexpected exceptions gracefully."""
        mock_client.ask.side_effect = Exception("Unexpected error")
        
        result = await agent.find_credentials(sample_opportunity, sector="Defense")
        
        assert result.no_matches_found == True
        assert len(result.matches) == 0
        assert result.lookup_status == "Lookup Failed"
        assert result.failure_reason == "Unexpected error"
        assert result.diagnostics is not None
        assert result.diagnostics.error_type == "Exception"


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


# =============================================================================
# Batch Lookup Tests
# =============================================================================

class TestBatchLookup:
    """Test single-call batched credentials lookup."""

    @pytest.mark.asyncio
    async def test_batch_happy_path(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="CMMC compliance support", confidence="High"),
            Opportunity(title="Opp 2", scope="Risk and cybersecurity program", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Cloud compliance modernization", confidence="Medium"),
        ]
        mock_client.ask.return_value = json.dumps(
            {
                "results": [
                    {
                        "opportunity_id": "opp_1",
                        "matches": [
                            {
                                "title": "Credential A",
                                "client_challenge": "Challenge A",
                                "approach": "Approach A",
                                "value_provided": "Value A",
                                "industry": "Defense",
                                "technologies_used": ["CMMC"],
                                "url": "https://ishare.protiviti.com/cred/a",
                            }
                        ],
                        "no_matches_found": False,
                    },
                    {
                        "opportunity_id": "opp_2",
                        "matches": [],
                        "no_matches_found": True,
                    },
                    {
                        "opportunity_id": "opp_3",
                        "matches": [
                            {
                                "title": "Credential C",
                                "client_challenge": "Challenge C",
                                "approach": "Approach C",
                                "value_provided": "Value C",
                                "industry": "Technology",
                                "technologies_used": ["Cloud"],
                                "url": "https://ishare.protiviti.com/cred/c",
                            }
                        ],
                        "no_matches_found": False,
                    },
                ]
            }
        )

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        mock_client.ask.assert_called_once()
        assert len(responses) == 3
        assert responses["Opp 1"].lookup_status == "Matched"
        assert responses["Opp 2"].lookup_status == "No Match"
        assert responses["Opp 3"].lookup_status == "Matched"
        assert batch_diag.invoked is True
        assert batch_diag.lookup_count_requested == 3
        assert batch_diag.lookup_count_returned == 3
        assert batch_diag.parse_outcome == "batch_json_parsed"

    @pytest.mark.asyncio
    async def test_batch_malformed_json_sets_lookup_failed_for_all(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.return_value = "{invalid"

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert all(resp.lookup_status == "Lookup Failed" for resp in responses.values())
        assert batch_diag.parse_outcome == "batch_json_parse_error"
        assert batch_diag.lookup_count_requested == 3

    @pytest.mark.asyncio
    async def test_batch_transport_error_sets_lookup_failed_for_all(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.side_effect = ContextFreeError("Service unavailable")

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert all(resp.lookup_status == "Lookup Failed" for resp in responses.values())
        assert batch_diag.parse_outcome == "batch_lookup_failed"
        assert batch_diag.error_type == "ContextFreeError"

    @pytest.mark.asyncio
    async def test_batch_timeout_then_retry_success(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.side_effect = [
            ContextFreeError("Request timed out. Service may be unavailable."),
            json.dumps(
                {
                    "results": [
                        {
                            "opportunity_id": "opp_1",
                            "matches": [
                                {
                                    "title": "Credential A",
                                    "client_challenge": "Challenge A",
                                    "approach": "Approach A",
                                    "value_provided": "Value A",
                                    "industry": "Defense",
                                    "technologies_used": ["CMMC"],
                                    "url": "https://ishare.protiviti.com/cred/a",
                                }
                            ],
                            "no_matches_found": False,
                        },
                        {
                            "opportunity_id": "opp_2",
                            "matches": [],
                            "no_matches_found": True,
                        },
                        {
                            "opportunity_id": "opp_3",
                            "matches": [],
                            "no_matches_found": True,
                        },
                    ]
                }
            ),
        ]

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert mock_client.ask.call_count == 2
        assert responses["Opp 1"].lookup_status == "Matched"
        assert responses["Opp 2"].lookup_status == "No Match"
        assert responses["Opp 3"].lookup_status == "No Match"
        assert batch_diag.parse_outcome == "batch_json_parsed"

    @pytest.mark.asyncio
    async def test_batch_timeout_then_serial_fallback(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.side_effect = [
            ContextFreeError("Request timed out. Service may be unavailable."),
            ContextFreeError("Request timed out. Service may be unavailable."),
            json.dumps({"matches": [{"title": "Cred 1", "client_challenge": "A", "approach": "B", "value_provided": "C", "industry": "Defense", "technologies_used": [], "url": "https://ishare.protiviti.com/cred/1"}], "no_matches_found": False}),
            json.dumps({"matches": [], "no_matches_found": True}),
            json.dumps({"matches": [{"title": "Cred 3", "client_challenge": "X", "approach": "Y", "value_provided": "Z", "industry": "Defense", "technologies_used": [], "url": "https://ishare.protiviti.com/cred/3"}], "no_matches_found": False}),
        ]

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert mock_client.ask.call_count == 5
        assert batch_diag.parse_outcome == "batch_timeout_fallback_serial"
        assert batch_diag.lookup_count_returned == 3
        assert "serial fallback" in (batch_diag.error_message or "").lower()
        assert responses["Opp 1"].lookup_status == "Matched"
        assert responses["Opp 2"].lookup_status == "No Match"
        assert responses["Opp 3"].lookup_status == "Matched"
        assert not all(resp.lookup_status == "Lookup Failed" for resp in responses.values())

    @pytest.mark.asyncio
    async def test_non_timeout_batch_error_unchanged(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.side_effect = ContextFreeError("Service unavailable")

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert all(resp.lookup_status == "Lookup Failed" for resp in responses.values())
        assert batch_diag.parse_outcome == "batch_lookup_failed"
        assert batch_diag.error_type == "ContextFreeError"

    @pytest.mark.asyncio
    async def test_batch_network_resolution_error_retries_then_fallback(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.side_effect = [
            ContextFreeError("Request failed: [Errno 11001] getaddrinfo failed"),
            ContextFreeError("Request failed: [Errno 11001] getaddrinfo failed"),
            json.dumps({"matches": [], "no_matches_found": True}),
            json.dumps({"matches": [], "no_matches_found": True}),
            json.dumps({"matches": [], "no_matches_found": True}),
        ]

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert mock_client.ask.call_count == 5
        assert batch_diag.parse_outcome == "batch_timeout_fallback_serial"
        assert all(resp.lookup_status == "No Match" for resp in responses.values())

    def test_batch_query_scope_truncation(self, agent):
        long_scope = " ".join(["scope"] * 200)  # > 350 chars
        opportunities = [
            Opportunity(title="Opp 1", scope=long_scope, confidence="High"),
        ]

        query = agent._build_batch_query(opportunities, "Defense", 3)
        scope_line = next(line for line in query.splitlines() if line.strip().startswith("scope:"))
        rendered_scope = scope_line.split("scope:", 1)[1].strip()
        assert len(rendered_scope) <= 353
        assert rendered_scope.endswith("...")
        assert "scope scope scope" in rendered_scope

    @pytest.mark.asyncio
    async def test_batch_partial_recovery_recovers_completed_objects(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        # Deliberately truncated after a complete opp_1 object and partial opp_2 object
        mock_client.ask.return_value = (
            '{"results":[{"opportunity_id":"opp_1","matches":[{"title":"Cred 1","client_challenge":"a",'
            '"approach":"b","value_provided":"c","industry":"Defense","technologies_used":[],"url":"https://ishare.protiviti.com/cred/x"}],'
            '"no_matches_found":false},{"opportunity_id":"opp_2","matches":[{"title":"Cred 2"'
        )

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")

        assert responses["Opp 1"].lookup_status == "Matched"
        assert responses["Opp 2"].lookup_status == "Lookup Failed"
        assert responses["Opp 3"].lookup_status == "Lookup Failed"
        assert batch_diag.parse_outcome == "batch_partial_recovery"
        assert batch_diag.lookup_count_returned == 1

    @pytest.mark.asyncio
    async def test_batch_parse_drops_invalid_url_match(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.return_value = json.dumps(
            {
                "results": [
                    {
                        "opportunity_id": "opp_1",
                        "matches": [
                            {
                                "title": "Invalid Credential",
                                "client_challenge": "Challenge",
                                "approach": "Approach",
                                "value_provided": "Value",
                                "industry": "Defense",
                                "technologies_used": [],
                                "url": "invalid-url",
                            }
                        ],
                        "no_matches_found": False,
                    },
                    {
                        "opportunity_id": "opp_2",
                        "matches": [],
                        "no_matches_found": True,
                    },
                    {
                        "opportunity_id": "opp_3",
                        "matches": [],
                        "no_matches_found": True,
                    },
                ]
            }
        )

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")
        assert responses["Opp 1"].lookup_status == "No Match"
        assert responses["Opp 1"].matches == []
        assert responses["Opp 1"].diagnostics is not None
        assert responses["Opp 1"].diagnostics.parse_outcome == "batch_json_parsed_all_matches_filtered_invalid_url"
        assert "filtered_invalid_url_count=1" in (responses["Opp 1"].diagnostics.error_message or "")
        assert batch_diag.parse_outcome == "batch_json_parsed"

    @pytest.mark.asyncio
    async def test_batch_parse_mixed_valid_invalid_retains_valid(self, agent, mock_client):
        opportunities = [
            Opportunity(title="Opp 1", scope="Scope 1", confidence="High"),
            Opportunity(title="Opp 2", scope="Scope 2", confidence="Medium"),
            Opportunity(title="Opp 3", scope="Scope 3", confidence="Low"),
        ]
        mock_client.ask.return_value = json.dumps(
            {
                "results": [
                    {
                        "opportunity_id": "opp_1",
                        "matches": [
                            {
                                "title": "Invalid Credential",
                                "client_challenge": "Challenge",
                                "approach": "Approach",
                                "value_provided": "Value",
                                "industry": "Defense",
                                "technologies_used": [],
                                "url": "invalid-url",
                            },
                            {
                                "title": "Valid Credential",
                                "client_challenge": "Challenge 2",
                                "approach": "Approach 2",
                                "value_provided": "Value 2",
                                "industry": "Defense",
                                "technologies_used": [],
                                "url": "https://ishare.protiviti.com/cred/1",
                            },
                        ],
                        "no_matches_found": False,
                    },
                    {
                        "opportunity_id": "opp_2",
                        "matches": [],
                        "no_matches_found": True,
                    },
                    {
                        "opportunity_id": "opp_3",
                        "matches": [],
                        "no_matches_found": True,
                    },
                ]
            }
        )

        responses, batch_diag = await agent.find_credentials_batch(opportunities, "Defense")
        assert responses["Opp 1"].lookup_status == "Matched"
        assert len(responses["Opp 1"].matches) == 1
        assert responses["Opp 1"].matches[0].title == "Valid Credential"
        assert responses["Opp 1"].diagnostics is not None
        assert responses["Opp 1"].diagnostics.parse_outcome == "batch_json_parsed_with_matches_filtered_invalid_url"
        assert batch_diag.parse_outcome == "batch_json_parsed"

    def test_valid_sharepoint_and_ishare_urls_pass(self, agent):
        assert agent._is_valid_credential_url(
            "https://roberthalf.sharepoint.com/sites/iShare-Client-Credentials/SitePages/Credential-Details.aspx?itemid=821"
        )
        assert agent._is_valid_credential_url("https://ishare.protiviti.com/cred/123")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
