"""
Unit tests for ContextFreeClient.

All tests use mocked HTTP responses (no live API calls).
Follows TDD Red-Green-Refactor pattern from test-driven-development skill.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
import json

# Import the client
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.contextfree_client import ContextFreeClient, ContextFreeError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def client():
    """Create a ContextFreeClient instance for testing."""
    return ContextFreeClient(
        api_url="https://test.api.example.com/api/ContextFree/chat",
        tenant_id="test-tenant-id",
        client_id="test-client-id",
        client_secret="test-secret",
        scope="api://test/.default"
    )


@pytest.fixture
def mock_token_response():
    """Mock AAD token response."""
    return {
        "access_token": "test-access-token-12345",
        "expires_in": 3600,
        "token_type": "Bearer"
    }


@pytest.fixture
def mock_chat_response_direct():
    """Mock ContextFree response with direct message field."""
    return {"message": "Here are 3 relevant credentials for your opportunity..."}


@pytest.fixture
def mock_chat_response_variables():
    """Mock ContextFree response with variables array (SK format)."""
    return {
        "variables": [
            {"key": "message", "value": "Found credentials matching CMMC requirements..."},
            {"key": "other", "value": "ignored"}
        ]
    }


@pytest.fixture
def mock_chat_response_assistant():
    """Mock ContextFree response with Content field (Assistant format)."""
    return {"Content": "Based on your query, here are matching credentials..."}


# =============================================================================
# Token Acquisition Tests
# =============================================================================

class TestTokenAcquisition:
    """Test AAD token acquisition."""
    
    @pytest.mark.asyncio
    async def test_acquires_token_on_first_request(self, client, mock_token_response, mock_chat_response_direct):
        """Token should be acquired before first API call."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # First call is token request
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            # Second call is actual chat request
            chat_response = MagicMock()
            chat_response.status_code = 200
            chat_response.json.return_value = mock_chat_response_direct
            chat_response.raise_for_status = MagicMock()
            
            mock_instance.post.side_effect = [token_response, chat_response]
            
            result = await client.ask("Find credentials", "https://endpoint.com")
            
            # Verify token endpoint was called
            token_call = mock_instance.post.call_args_list[0]
            assert "login.microsoftonline.com" in token_call.args[0]
            assert "test-tenant-id" in token_call.args[0]
    
    @pytest.mark.asyncio
    async def test_reuses_cached_token(self, client, mock_token_response, mock_chat_response_direct):
        """Cached token should be reused for subsequent requests."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            chat_response = MagicMock()
            chat_response.status_code = 200
            chat_response.json.return_value = mock_chat_response_direct
            chat_response.raise_for_status = MagicMock()
            
            # First request: token + chat
            mock_instance.post.side_effect = [token_response, chat_response, chat_response]
            
            await client.ask("First question", "https://endpoint.com")
            await client.ask("Second question", "https://endpoint.com")
            
            # Token should only be acquired once (2 token calls + 2 chat calls = 4 if not cached)
            # With caching: 1 token call + 2 chat calls = 3
            assert mock_instance.post.call_count == 3
    
    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, client, mock_token_response, mock_chat_response_direct):
        """Expired token should trigger refresh."""
        # Manually set expired token in cache
        client._token_cache = ("old-token", datetime.now() - timedelta(hours=1))
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            chat_response = MagicMock()
            chat_response.status_code = 200
            chat_response.json.return_value = mock_chat_response_direct
            chat_response.raise_for_status = MagicMock()
            
            mock_instance.post.side_effect = [token_response, chat_response]
            
            await client.ask("Question", "https://endpoint.com")
            
            # New token should be in cache
            assert client._token_cache[0] == "test-access-token-12345"


# =============================================================================
# API Response Parsing Tests
# =============================================================================

class TestResponseParsing:
    """Test response extraction from different GPT formats."""
    
    def test_extracts_direct_message(self, client, mock_chat_response_direct):
        """Should extract message from direct format."""
        result = client._extract_message(mock_chat_response_direct)
        assert "3 relevant credentials" in result
    
    def test_extracts_variables_message(self, client, mock_chat_response_variables):
        """Should extract message from SK variables format."""
        result = client._extract_message(mock_chat_response_variables)
        assert "CMMC requirements" in result
    
    def test_extracts_assistant_content(self, client, mock_chat_response_assistant):
        """Should extract Content from Assistant format."""
        result = client._extract_message(mock_chat_response_assistant)
        assert "matching credentials" in result
    
    def test_handles_empty_response(self, client):
        """Should handle empty response gracefully."""
        result = client._extract_message(None)
        assert result == ""
        
        result = client._extract_message({})
        assert result == ""
    
    def test_handles_assistant_array_format(self, client):
        """Should extract content from Assistant GPT array format.
        
        Per ContextFreeAPI_REPORT.md: Assistant GPT returns a JSON array
        where we select the item with the latest Timestamp.
        """
        assistant_array_response = [
            {
                "Timestamp": "2025-01-01T12:00:00Z",
                "Content": "Earlier response",
                "Id": "msg_1"
            },
            {
                "Timestamp": "2025-01-01T12:05:00Z",
                "Content": "Latest response with credentials",
                "Id": "msg_2"
            }
        ]
        result = client._extract_message(assistant_array_response)
        assert "Latest response" in result
    
    def test_handles_lowercase_content_in_array(self, client):
        """Should handle lowercase 'content' field in array."""
        assistant_array_response = [
            {
                "timestamp": "2025-01-01T12:00:00Z",
                "content": "Response with lowercase content"
            }
        ]
        result = client._extract_message(assistant_array_response)
        assert "lowercase content" in result


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling scenarios."""
    
    @pytest.mark.asyncio
    async def test_rejects_empty_question(self, client):
        """Should reject empty questions."""
        with pytest.raises(ContextFreeError, match="empty"):
            await client.ask("", "https://endpoint.com")
        
        with pytest.raises(ContextFreeError, match="empty"):
            await client.ask("   ", "https://endpoint.com")
            
    @pytest.mark.asyncio
    async def test_rejects_short_question(self, client):
        """Should reject questions shorter than 3 characters."""
        with pytest.raises(ContextFreeError, match="at least 3 characters"):
            await client.ask("Hi", "https://endpoint.com")
    
    @pytest.mark.asyncio
    async def test_rejects_empty_endpoint(self, client):
        """Should reject empty GPT endpoint."""
        with pytest.raises(ContextFreeError, match="endpoint"):
            await client.ask("Valid question", "")
    
    @pytest.mark.asyncio
    async def test_handles_timeout(self, client, mock_token_response):
        """Should handle request timeout gracefully."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            # Import the actual exception
            import httpx as real_httpx
            
            mock_instance.post.side_effect = [
                token_response,
                real_httpx.TimeoutException("Connection timed out")
            ]
            
            with pytest.raises(ContextFreeError, match="timed out"):
                await client.ask("Question", "https://endpoint.com")
    
    @pytest.mark.asyncio
    async def test_retries_on_401(self, client, mock_token_response, mock_chat_response_direct):
        """Should retry with fresh token on 401 error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            # First chat request returns 401
            auth_error_response = MagicMock()
            auth_error_response.status_code = 401
            
            # Second chat request succeeds
            success_response = MagicMock()
            success_response.status_code = 200
            success_response.json.return_value = mock_chat_response_direct
            success_response.raise_for_status = MagicMock()
            
            mock_instance.post.side_effect = [
                token_response,      # Initial token
                auth_error_response, # 401 error
                token_response,      # Refresh token
                success_response     # Retry succeeds
            ]
            
            result = await client.ask("Question", "https://endpoint.com")
            assert "credentials" in result


# =============================================================================
# Integration-style Tests (with mocks)
# =============================================================================

class TestFullFlow:
    """Test complete request/response flow with mocks."""
    
    @pytest.mark.asyncio
    async def test_credentials_query_flow(self, client, mock_token_response):
        """Simulate a credentials query flow."""
        credentials_response = {
            "message": json.dumps({
                "matches": [
                    {
                        "title": "CMMC Assessment for Defense Contractor",
                        "client_challenge": "Needed CMMC Level 2 certification",
                        "value_provided": "Achieved certification in 6 months",
                        "url": "https://ishare.protiviti.com/cred/123"
                    }
                ],
                "no_matches_found": False
            })
        }
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            token_response = MagicMock()
            token_response.status_code = 200
            token_response.json.return_value = mock_token_response
            token_response.raise_for_status = MagicMock()
            
            chat_response = MagicMock()
            chat_response.status_code = 200
            chat_response.json.return_value = credentials_response
            chat_response.raise_for_status = MagicMock()
            
            mock_instance.post.side_effect = [token_response, chat_response]
            
            result = await client.ask(
                "Find credentials for CMMC assessment",
                "https://as-assistant-api.azurewebsites.net/assistantapi/api/OmniInterface/asst_xxx"
            )
            
            # Should get JSON response with credentials
            assert "CMMC Assessment" in result
            assert "Defense Contractor" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
