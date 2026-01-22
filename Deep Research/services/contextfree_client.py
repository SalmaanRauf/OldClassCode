"""
ContextFree API Client for stateless chat with internal GPTs.

This client implements the stateless chat pattern documented in ContextFreeAPI_REPORT.md:
1. Acquire AAD token (Client Credentials flow)
2. POST to /api/ContextFree/chat with input and gptEndpoint
3. The API internally: creates session → sends message → extracts response → deletes session
4. Returns the extracted message to caller

Authentication uses Azure AD (AAD) with the same credentials as ATLAS.
"""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple, Any, Dict
import logging

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)


class ContextFreeClient:
    """Stateless chat client for internal GPTs via ContextFree API.
    
    The ContextFree API handles session lifecycle internally, so each call
    is completely stateless from the client's perspective.
    
    Example:
        client = ContextFreeClient(
            api_url="https://dev.api.progpt-tst.protiviti.com/api/ContextFree/chat",
            tenant_id="your-tenant",
            client_id="your-app-id",
            client_secret="your-secret",
            scope="api://xxx/.default"
        )
        response = await client.ask("Find credentials for CMMC", gpt_endpoint)
    """
    
    # Token refresh buffer (refresh 5 minutes before expiry)
    TOKEN_REFRESH_BUFFER = timedelta(minutes=5)
    
    # Request timeout
    REQUEST_TIMEOUT = 120  # seconds
    
    def __init__(
        self,
        api_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        scope: str
    ):
        """Initialize ContextFree client.
        
        Args:
            api_url: ContextFree API endpoint
            tenant_id: Azure AD tenant ID
            client_id: Azure AD application/client ID  
            client_secret: Azure AD client secret
            scope: OAuth scope (e.g., "api://xxx/.default")
        """
        self.api_url = api_url
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        
        # Token cache: (token, expiry_datetime)
        self._token_cache: Optional[Tuple[str, datetime]] = None
        
        # Validate httpx is available
        if httpx is None:
            raise ImportError("httpx is required. Install with: pip install httpx")
    
    @classmethod
    def from_env(cls) -> "ContextFreeClient":
        """Create client from environment variables.
        
        Required env vars:
            - CONTEXTFREE_API_URL
            - TENANT_ID
            - CLIENT_ID
            - CLIENT_SECRET
            - SCOPE
        """
        return cls(
            api_url=os.getenv("CONTEXTFREE_API_URL", ""),
            tenant_id=os.getenv("TENANT_ID", ""),
            client_id=os.getenv("CLIENT_ID", ""),
            client_secret=os.getenv("CLIENT_SECRET", ""),
            scope=os.getenv("SCOPE", "")
        )
    
    async def ask(self, question: str, gpt_endpoint: str) -> str:
        """Send a question to a GPT via ContextFree API.
        
        Args:
            question: The user's question/input
            gpt_endpoint: The GPT endpoint URL (e.g., Credentials Agent URL)
            
        Returns:
            The GPT's response message
            
        Raises:
            ContextFreeError: If the API call fails
        """
        if not question or not question.strip():
            raise ContextFreeError("Question cannot be empty")
            
        if len(question.strip()) < 3:
            raise ContextFreeError("Input must be at least 3 characters")
        
        if not gpt_endpoint:
            raise ContextFreeError("GPT endpoint cannot be empty")
        
        token = await self._ensure_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "input": question.strip(),
            "gptEndpoint": gpt_endpoint
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT) as client:
                logger.debug(f"Sending request to ContextFree API: {self.api_url}")
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=payload
                )
                
                # Handle auth errors with token refresh
                if response.status_code in (401, 403):
                    logger.warning("Auth error, refreshing token and retrying...")
                    self._token_cache = None
                    token = await self._ensure_token()
                    headers["Authorization"] = f"Bearer {token}"
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        json=payload
                    )
                
                response.raise_for_status()
                return self._extract_message(response.json())
                
        except httpx.TimeoutException:
            raise ContextFreeError("Request timed out. Service may be unavailable.")
        except httpx.HTTPStatusError as e:
            raise ContextFreeError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except Exception as e:
            raise ContextFreeError(f"Request failed: {str(e)}")
    
    async def _ensure_token(self) -> str:
        """Get valid token, refreshing if needed."""
        now = datetime.now()
        
        # Check cache validity
        if self._token_cache:
            token, expiry = self._token_cache
            if now < (expiry - self.TOKEN_REFRESH_BUFFER):
                return token
        
        # Acquire new token
        return await self._acquire_token()
    
    async def _acquire_token(self) -> str:
        """Acquire new AAD token using Client Credentials flow.
        
        Token endpoint: https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
        """
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(token_url, data=data)
                response.raise_for_status()
                
                token_data = response.json()
                access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                
                # Cache token with expiry
                expiry = datetime.now() + timedelta(seconds=expires_in)
                self._token_cache = (access_token, expiry)
                
                logger.debug(f"Acquired new AAD token, expires in {expires_in}s")
                return access_token
                
        except httpx.HTTPStatusError as e:
            raise ContextFreeError(f"Token acquisition failed: {e.response.text}")
        except Exception as e:
            raise ContextFreeError(f"Token acquisition failed: {str(e)}")
    
    def _extract_message(self, response_data: Any) -> str:
        """Extract message from ContextFree API response.
        
        Handles multiple response formats per ContextFreeAPI_REPORT.md:
        
        1. SK GPT (Type 0): {"message": "...", "input": "...", "tokenUsage": "..."}
           - Direct extraction from "message" key
           
        2. SK GPT (variables format): {"variables": [{"key": "message", "value": "..."}]}
           - Extract from variables array where key == "message"
           
        3. Assistant GPT (Type 1): JSON ARRAY with timestamp-ordered messages
           - Select the item with the LATEST timestamp
           - Extract "content" or "Content" field
        """
        if not response_data:
            return ""
        
        # Handle Assistant GPT format: JSON ARRAY
        # Per docs: "Expects response content to be a JSON array. Returns the record with the latest Timestamp."
        if isinstance(response_data, list):
            return self._extract_from_assistant_array(response_data)
        
        # Handle SK GPT format: JSON OBJECT
        if isinstance(response_data, dict):
            # Direct message field (already extracted by ContextFreeService)
            if "message" in response_data:
                return str(response_data["message"])
            
            # Variables array (SK GPT raw format)
            # Per docs: "variables" contains [{"key": "message", "value": "..."}]
            if "variables" in response_data:
                variables = response_data["variables"]
                if isinstance(variables, list):
                    for var in variables:
                        if isinstance(var, dict) and var.get("key") == "message":
                            return str(var.get("value", ""))
            
            # Content field (Assistant GPT single object format)
            if "Content" in response_data:
                return str(response_data["Content"])
            if "content" in response_data:
                return str(response_data["content"])
        
        # Fallback: stringify response
        logger.warning(f"Unexpected response format: {type(response_data)}")
        return str(response_data)
    
    def _extract_from_assistant_array(self, messages: list) -> str:
        """Extract message from Assistant GPT array format.
        
        Per ContextFreeAPI_REPORT.md lines 166-170 and 921-957:
        - Response is a JSON array of messages
        - Each message has: Timestamp, Content, Id, etc.
        - Returns the record with the LATEST Timestamp
        """
        if not messages:
            return ""
        
        # Sort by timestamp to get latest
        # Timestamp format: "2025-01-01T12:05:00Z"
        try:
            sorted_messages = sorted(
                [m for m in messages if isinstance(m, dict) and m.get("Timestamp") or m.get("timestamp")],
                key=lambda m: m.get("Timestamp") or m.get("timestamp") or "",
                reverse=True
            )
            
            if sorted_messages:
                latest = sorted_messages[0]
                # Extract Content (capital C per docs) or content (lowercase)
                return str(latest.get("Content") or latest.get("content") or "")
        except Exception as e:
            logger.warning(f"Failed to sort assistant messages by timestamp: {e}")
        
        # Fallback: return last item's content
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                return str(last.get("Content") or last.get("content") or "")
        
        return ""


class ContextFreeError(Exception):
    """Error from ContextFree API operations."""
    pass
