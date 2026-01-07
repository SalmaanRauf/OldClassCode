"""
Integration tests for the enhanced system.

This module tests the complete enhanced system integration including
intent resolution, task execution, and response formatting.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from services.conversation_manager import ConversationContext
from tools.orchestrators import enhanced_user_request_handler
from services.intent_resolver import IntentType, TaskType


class TestEnhancedSystem:
    """Test class for enhanced system integration."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.context = ConversationContext(session_id="test_session")
        
        # Mock bing agent
        self.mock_bing_agent = Mock()
        self.mock_bing_agent.search_market_overview = Mock(return_value={
            'summary': 'Test market overview',
            'citations_md': '- [Test Source](https://test.com)',
            'audit': {'citation_count': 1}
        })
        self.mock_bing_agent.search_general_topic = Mock(return_value={
            'summary': 'Test general topic',
            'citations_md': '- [General Source](https://test.com)',
            'audit': {'citation_count': 1}
        })
        
        # Mock analyst agent
        self.mock_analyst_agent = Mock()
        self.mock_analyst_agent.analyze_all_data = AsyncMock(return_value=[])
    
    @pytest.mark.asyncio
    async def test_company_briefing_intent(self):
        """Test company briefing intent resolution and execution."""
        with patch('services.enhanced_router.enhanced_router') as mock_router:
            # Mock intent resolution
            mock_router.route_enhanced.return_value = (
                IntentType.COMPANY_BRIEFING,
                Mock(
                    intent_type=IntentType.COMPANY_BRIEFING,
                    tasks=[Mock(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target="Tesla",
                        parameters={}
                    )],
                    confidence=0.95,
                    reasoning="Clear company briefing request"
                )
            )
            
            with patch('tools.task_executor.task_executor') as mock_executor:
                # Mock task execution
                mock_executor.execute_plan.return_value = Mock(
                    intent_type="company_briefing",
                    success=True,
                    results=[],
                    combined_summary="Tesla analysis completed",
                    all_citations=[],
                    execution_time=2.5
                )
                
                with patch('tools.response_formatter.response_formatter') as mock_formatter:
                    # Mock response formatting
                    mock_formatter.format_response.return_value = {
                        "type": "company_briefing",
                        "summary": "Tesla analysis completed",
                        "citations": [],
                        "execution_time": 2.5
                    }
                    
                    # Test the enhanced handler
                    response = await enhanced_user_request_handler(
                        "Tell me about Tesla",
                        self.context,
                        self.mock_bing_agent,
                        self.mock_analyst_agent
                    )
                    
                    # Verify response
                    assert response["type"] == "company_briefing"
                    assert "Tesla" in response["summary"]
                    assert response["execution_time"] == 2.5
    
    @pytest.mark.asyncio
    async def test_general_research_intent(self):
        """Test general research intent resolution and execution."""
        with patch('services.enhanced_router.enhanced_router') as mock_router:
            # Mock intent resolution
            mock_router.route_enhanced.return_value = (
                IntentType.GENERAL_RESEARCH,
                Mock(
                    intent_type=IntentType.GENERAL_RESEARCH,
                    tasks=[Mock(
                        task_type=TaskType.GENERAL_RESEARCH,
                        target="What are the top financial companies?",
                        parameters={}
                    )],
                    confidence=0.90,
                    reasoning="General research request"
                )
            )
            
            with patch('tools.task_executor.task_executor') as mock_executor:
                # Mock task execution
                mock_executor.execute_plan.return_value = Mock(
                    intent_type="general_research",
                    success=True,
                    results=[],
                    combined_summary="Top financial companies research completed",
                    all_citations=[],
                    execution_time=1.8
                )
                
                with patch('tools.response_formatter.response_formatter') as mock_formatter:
                    # Mock response formatting
                    mock_formatter.format_response.return_value = {
                        "type": "general_research",
                        "summary": "Top financial companies research completed",
                        "citations": [],
                        "execution_time": 1.8
                    }
                    
                    # Test the enhanced handler
                    response = await enhanced_user_request_handler(
                        "What are the top financial companies?",
                        self.context,
                        self.mock_bing_agent,
                        self.mock_analyst_agent
                    )
                    
                    # Verify response
                    assert response["type"] == "general_research"
                    assert "financial companies" in response["summary"]
                    assert response["execution_time"] == 1.8
    
    @pytest.mark.asyncio
    async def test_mixed_request_intent(self):
        """Test mixed request intent resolution and execution."""
        with patch('services.enhanced_router.enhanced_router') as mock_router:
            # Mock intent resolution
            mock_router.route_enhanced.return_value = (
                IntentType.MIXED_REQUEST,
                Mock(
                    intent_type=IntentType.MIXED_REQUEST,
                    tasks=[
                        Mock(
                            task_type=TaskType.COMPANY_BRIEFING,
                            target="Apple",
                            parameters={}
                        ),
                        Mock(
                            task_type=TaskType.COMPETITOR_ANALYSIS,
                            target="Apple",
                            parameters={}
                        )
                    ],
                    confidence=0.95,
                    reasoning="Mixed request for company briefing and competitor analysis"
                )
            )
            
            with patch('tools.task_executor.task_executor') as mock_executor:
                # Mock task execution
                mock_executor.execute_plan.return_value = Mock(
                    intent_type="mixed_request",
                    success=True,
                    results=[],
                    combined_summary="Apple analysis and competitor research completed",
                    all_citations=[],
                    execution_time=3.2
                )
                
                with patch('tools.response_formatter.response_formatter') as mock_formatter:
                    # Mock response formatting
                    mock_formatter.format_response.return_value = {
                        "type": "mixed_request",
                        "summary": "Apple analysis and competitor research completed",
                        "sections": [
                            {
                                "task_type": "company_briefing",
                                "target": "Apple",
                                "content": "Apple company analysis"
                            },
                            {
                                "task_type": "competitor_analysis",
                                "target": "Apple",
                                "content": "Apple competitor analysis"
                            }
                        ],
                        "citations": [],
                        "execution_time": 3.2
                    }
                    
                    # Test the enhanced handler
                    response = await enhanced_user_request_handler(
                        "Tell me about Apple and its competitors",
                        self.context,
                        self.mock_bing_agent,
                        self.mock_analyst_agent
                    )
                    
                    # Verify response
                    assert response["type"] == "mixed_request"
                    assert "Apple" in response["summary"]
                    assert len(response["sections"]) == 2
                    assert response["execution_time"] == 3.2
    
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling in enhanced system."""
        with patch('services.enhanced_router.enhanced_router') as mock_router:
            # Mock router failure
            mock_router.route_enhanced.side_effect = Exception("Router failed")
            
            # Test the enhanced handler
            response = await enhanced_user_request_handler(
                "Test request",
                self.context,
                self.mock_bing_agent,
                self.mock_analyst_agent
            )
            
            # Verify error response
            assert response["type"] == "error"
            assert "Request processing failed" in response["error"]
            assert response["execution_time"] == 0.0
    
    @pytest.mark.asyncio
    async def test_progress_callback(self):
        """Test progress callback functionality."""
        progress_messages = []
        
        async def mock_progress(message):
            progress_messages.append(message)
        
        with patch('services.enhanced_router.enhanced_router') as mock_router:
            # Mock intent resolution
            mock_router.route_enhanced.return_value = (
                IntentType.COMPANY_BRIEFING,
                Mock(
                    intent_type=IntentType.COMPANY_BRIEFING,
                    tasks=[Mock(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target="Tesla",
                        parameters={}
                    )],
                    confidence=0.95,
                    reasoning="Test"
                )
            )
            
            with patch('tools.task_executor.task_executor') as mock_executor:
                # Mock task execution
                mock_executor.execute_plan.return_value = Mock(
                    intent_type="company_briefing",
                    success=True,
                    results=[],
                    combined_summary="Test completed",
                    all_citations=[],
                    execution_time=1.0
                )
                
                with patch('tools.response_formatter.response_formatter') as mock_formatter:
                    # Mock response formatting
                    mock_formatter.format_response.return_value = {
                        "type": "company_briefing",
                        "summary": "Test completed",
                        "citations": [],
                        "execution_time": 1.0
                    }
                    
                    # Test with progress callback
                    response = await enhanced_user_request_handler(
                        "Tell me about Tesla",
                        self.context,
                        self.mock_bing_agent,
                        self.mock_analyst_agent,
                        progress=mock_progress
                    )
                    
                    # Verify progress messages were called
                    assert len(progress_messages) > 0
                    assert any("Analyzing" in msg for msg in progress_messages)
                    assert any("Executing" in msg for msg in progress_messages)
                    assert any("Formatting" in msg for msg in progress_messages)


if __name__ == "__main__":
    pytest.main([__file__])
