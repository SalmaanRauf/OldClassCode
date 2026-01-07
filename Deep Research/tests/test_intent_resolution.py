"""
Unit tests for intent resolution system.

This module tests the intent resolution functionality including
LLM-based resolution and rule-based fallback.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from services.intent_resolver import IntentResolver, IntentType, TaskType
from services.conversation_manager import ConversationContext


class TestIntentResolution:
    """Test class for intent resolution system."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.resolver = IntentResolver()
        self.context = ConversationContext(session_id="test_session")
    
    @pytest.mark.asyncio
    async def test_company_briefing_intent(self):
        """Test company briefing intent resolution."""
        with patch.object(self.resolver, '_llm_resolve_intent') as mock_llm:
            # Mock LLM resolution
            mock_llm.return_value = Mock(
                intent_type=IntentType.COMPANY_BRIEFING,
                tasks=[Mock(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target="Tesla",
                    parameters={},
                    priority=1
                )],
                entities={"companies": ["Tesla"], "topics": [], "locations": []},
                confidence=0.95,
                reasoning="Clear company briefing request"
            )
            
            # Test intent resolution
            intent_plan = await self.resolver.resolve_intent("Tell me about Tesla", self.context)
            
            # Verify results
            assert intent_plan.intent_type == IntentType.COMPANY_BRIEFING
            assert len(intent_plan.tasks) == 1
            assert intent_plan.tasks[0].task_type == TaskType.COMPANY_BRIEFING
            assert intent_plan.tasks[0].target == "Tesla"
            assert intent_plan.confidence == 0.95
            assert "Tesla" in intent_plan.entities["companies"]
    
    @pytest.mark.asyncio
    async def test_general_research_intent(self):
        """Test general research intent resolution."""
        with patch.object(self.resolver, '_llm_resolve_intent') as mock_llm:
            # Mock LLM resolution
            mock_llm.return_value = Mock(
                intent_type=IntentType.GENERAL_RESEARCH,
                tasks=[Mock(
                    task_type=TaskType.GENERAL_RESEARCH,
                    target="What are the top financial companies?",
                    parameters={"scope": "market_overview", "industry": "financial_services"},
                    priority=1
                )],
                entities={"companies": [], "topics": ["financial companies"], "locations": []},
                confidence=0.90,
                reasoning="General research request"
            )
            
            # Test intent resolution
            intent_plan = await self.resolver.resolve_intent("What are the top financial companies?", self.context)
            
            # Verify results
            assert intent_plan.intent_type == IntentType.GENERAL_RESEARCH
            assert len(intent_plan.tasks) == 1
            assert intent_plan.tasks[0].task_type == TaskType.GENERAL_RESEARCH
            assert "financial companies" in intent_plan.tasks[0].target
            assert intent_plan.confidence == 0.90
            assert "financial companies" in intent_plan.entities["topics"]
    
    @pytest.mark.asyncio
    async def test_mixed_request_intent(self):
        """Test mixed request intent resolution."""
        with patch.object(self.resolver, '_llm_resolve_intent') as mock_llm:
            # Mock LLM resolution
            mock_llm.return_value = Mock(
                intent_type=IntentType.MIXED_REQUEST,
                tasks=[
                    Mock(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target="Apple",
                        parameters={},
                        priority=1
                    ),
                    Mock(
                        task_type=TaskType.COMPETITOR_ANALYSIS,
                        target="Apple",
                        parameters={},
                        priority=2
                    )
                ],
                entities={"companies": ["Apple"], "topics": ["competitors"], "locations": []},
                confidence=0.95,
                reasoning="Mixed request for company briefing and competitor analysis"
            )
            
            # Test intent resolution
            intent_plan = await self.resolver.resolve_intent("Tell me about Apple and its competitors", self.context)
            
            # Verify results
            assert intent_plan.intent_type == IntentType.MIXED_REQUEST
            assert len(intent_plan.tasks) == 2
            assert intent_plan.tasks[0].task_type == TaskType.COMPANY_BRIEFING
            assert intent_plan.tasks[1].task_type == TaskType.COMPETITOR_ANALYSIS
            assert intent_plan.tasks[0].target == "Apple"
            assert intent_plan.tasks[1].target == "Apple"
            assert intent_plan.confidence == 0.95
    
    @pytest.mark.asyncio
    async def test_llm_fallback_to_rules(self):
        """Test fallback from LLM to rule-based resolution."""
        with patch.object(self.resolver, '_llm_resolve_intent') as mock_llm:
            # Mock LLM failure
            mock_llm.side_effect = Exception("LLM failed")
            
            with patch.object(self.resolver, '_rule_based_resolve_intent') as mock_rules:
                # Mock rule-based resolution
                mock_rules.return_value = Mock(
                    intent_type=IntentType.COMPANY_BRIEFING,
                    tasks=[Mock(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target="Tesla",
                        parameters={},
                        priority=1
                    )],
                    entities={"companies": ["Tesla"], "topics": [], "locations": []},
                    confidence=0.8,
                    reasoning="Rule-based resolution"
                )
                
                # Test intent resolution
                intent_plan = await self.resolver.resolve_intent("Tell me about Tesla", self.context)
                
                # Verify fallback was used
                assert intent_plan.intent_type == IntentType.COMPANY_BRIEFING
                assert intent_plan.confidence == 0.8
                assert intent_plan.reasoning == "Rule-based resolution"
                mock_rules.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_low_confidence_fallback(self):
        """Test fallback when LLM confidence is too low."""
        with patch.object(self.resolver, '_llm_resolve_intent') as mock_llm:
            # Mock low confidence LLM resolution
            mock_llm.return_value = Mock(
                intent_type=IntentType.COMPANY_BRIEFING,
                tasks=[],
                entities={},
                confidence=0.5,  # Low confidence
                reasoning="Uncertain resolution"
            )
            
            with patch.object(self.resolver, '_rule_based_resolve_intent') as mock_rules:
                # Mock rule-based resolution
                mock_rules.return_value = Mock(
                    intent_type=IntentType.COMPANY_BRIEFING,
                    tasks=[Mock(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target="Tesla",
                        parameters={},
                        priority=1
                    )],
                    entities={"companies": ["Tesla"], "topics": [], "locations": []},
                    confidence=0.8,
                    reasoning="Rule-based resolution"
                )
                
                # Test intent resolution
                intent_plan = await self.resolver.resolve_intent("Tell me about Tesla", self.context)
                
                # Verify fallback was used due to low confidence
                assert intent_plan.intent_type == IntentType.COMPANY_BRIEFING
                assert intent_plan.confidence == 0.8
                assert intent_plan.reasoning == "Rule-based resolution"
                mock_rules.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Test handling of empty input."""
        intent_plan = await self.resolver.resolve_intent("", self.context)
        
        # Verify clarification intent
        assert intent_plan.intent_type == IntentType.CLARIFICATION
        assert len(intent_plan.tasks) == 0
        assert intent_plan.confidence == 0.0
    
    @pytest.mark.asyncio
    async def test_whitespace_input(self):
        """Test handling of whitespace-only input."""
        intent_plan = await self.resolver.resolve_intent("   \n\t   ", self.context)
        
        # Verify clarification intent
        assert intent_plan.intent_type == IntentType.CLARIFICATION
        assert len(intent_plan.tasks) == 0
        assert intent_plan.confidence == 0.0
    
    def test_intent_type_enum(self):
        """Test intent type enum values."""
        assert IntentType.COMPANY_BRIEFING.value == "company_briefing"
        assert IntentType.GENERAL_RESEARCH.value == "general_research"
        assert IntentType.MIXED_REQUEST.value == "mixed_request"
        assert IntentType.FOLLOW_UP.value == "follow_up"
        assert IntentType.COMPARISON.value == "comparison"
        assert IntentType.CLARIFICATION.value == "clarification"
    
    def test_task_type_enum(self):
        """Test task type enum values."""
        assert TaskType.COMPANY_BRIEFING.value == "company_briefing"
        assert TaskType.GENERAL_RESEARCH.value == "general_research"
        assert TaskType.COMPETITOR_ANALYSIS.value == "competitor_analysis"
        assert TaskType.COMPARISON.value == "comparison"
        assert TaskType.FOLLOW_UP.value == "follow_up"


if __name__ == "__main__":
    pytest.main([__file__])
