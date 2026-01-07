"""
Unit tests for task execution system.

This module tests the task execution functionality including
parallel execution, error handling, and result synthesis.
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from tools.task_executor import TaskExecutor, TaskResult, ExecutionResult
from services.intent_resolver import IntentType, TaskType, IntentPlan, Task
from services.conversation_manager import ConversationContext


class TestTaskExecution:
    """Test class for task execution system."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.executor = TaskExecutor()
        self.context = ConversationContext(session_id="test_session")
        self.mock_bing_agent = Mock()
        self.mock_analyst_agent = Mock()
    
    @pytest.mark.asyncio
    async def test_company_briefing_task_execution(self):
        """Test company briefing task execution."""
        # Create intent plan
        intent_plan = IntentPlan(
            intent_type=IntentType.COMPANY_BRIEFING,
            tasks=[
                Task(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target="Tesla",
                    parameters={},
                    priority=1
                )
            ],
            entities={"companies": ["Tesla"]},
            confidence=0.95,
            reasoning="Test"
        )
        
        # Mock the full_company_analysis function
        with patch('tools.orchestrators.full_company_analysis') as mock_analysis:
            mock_briefing = Mock()
            mock_briefing.company.name = "Tesla"
            mock_briefing.summary = "Tesla analysis summary"
            mock_briefing.events = []
            mock_briefing.gwbs = {}
            mock_analysis.return_value = mock_briefing
            
            # Execute the plan
            result = await self.executor.execute_plan(
                intent_plan, self.context, self.mock_bing_agent, self.mock_analyst_agent
            )
            
            # Verify results
            assert isinstance(result, ExecutionResult)
            assert result.intent_type == "company_briefing"
            assert result.success is True
            assert len(result.results) == 1
            assert result.results[0].task_type == TaskType.COMPANY_BRIEFING
            assert result.results[0].target == "Tesla"
            assert result.results[0].success is True
            assert "Tesla analysis summary" in result.combined_summary
    
    @pytest.mark.asyncio
    async def test_general_research_task_execution(self):
        """Test general research task execution."""
        # Create intent plan
        intent_plan = IntentPlan(
            intent_type=IntentType.GENERAL_RESEARCH,
            tasks=[
                Task(
                    task_type=TaskType.GENERAL_RESEARCH,
                    target="What are the top financial companies?",
                    parameters={},
                    priority=1
                )
            ],
            entities={"topics": ["financial companies"]},
            confidence=0.90,
            reasoning="Test"
        )
        
        # Mock the general research orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.execute_general_research = AsyncMock(return_value=(
            "Top financial companies research completed",
            []
        ))
        self.executor.set_general_research_orchestrator(mock_orchestrator)
        
        # Execute the plan
        result = await self.executor.execute_plan(
            intent_plan, self.context, self.mock_bing_agent, self.mock_analyst_agent
        )
        
        # Verify results
        assert isinstance(result, ExecutionResult)
        assert result.intent_type == "general_research"
        assert result.success is True
        assert len(result.results) == 1
        assert result.results[0].task_type == TaskType.GENERAL_RESEARCH
        assert result.results[0].success is True
        assert "financial companies" in result.combined_summary
    
    @pytest.mark.asyncio
    async def test_parallel_task_execution(self):
        """Test parallel execution of multiple tasks."""
        # Create intent plan with multiple tasks
        intent_plan = IntentPlan(
            intent_type=IntentType.MIXED_REQUEST,
            tasks=[
                Task(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target="Apple",
                    parameters={},
                    priority=1
                ),
                Task(
                    task_type=TaskType.COMPETITOR_ANALYSIS,
                    target="Apple",
                    parameters={},
                    priority=2
                )
            ],
            entities={"companies": ["Apple"]},
            confidence=0.95,
            reasoning="Test"
        )
        
        # Mock the analysis functions
        with patch('tools.orchestrators.full_company_analysis') as mock_analysis:
            mock_briefing = Mock()
            mock_briefing.company.name = "Apple"
            mock_briefing.summary = "Apple analysis summary"
            mock_briefing.events = []
            mock_briefing.gwbs = {}
            mock_analysis.return_value = mock_briefing
            
            # Mock competitor analysis
            self.mock_bing_agent.search_competitor_analysis.return_value = {
                'summary': 'Apple competitor analysis',
                'citations_md': '- [Competitor Source](https://test.com)',
                'audit': {'citation_count': 1}
            }
            
            # Execute the plan
            result = await self.executor.execute_plan(
                intent_plan, self.context, self.mock_bing_agent, self.mock_analyst_agent
            )
            
            # Verify results
            assert isinstance(result, ExecutionResult)
            assert result.intent_type == "mixed_request"
            assert result.success is True
            assert len(result.results) == 2
            assert result.results[0].task_type == TaskType.COMPANY_BRIEFING
            assert result.results[1].task_type == TaskType.COMPETITOR_ANALYSIS
            assert all(r.success for r in result.results)
    
    @pytest.mark.asyncio
    async def test_task_execution_failure(self):
        """Test task execution failure handling."""
        # Create intent plan
        intent_plan = IntentPlan(
            intent_type=IntentType.COMPANY_BRIEFING,
            tasks=[
                Task(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target="Tesla",
                    parameters={},
                    priority=1
                )
            ],
            entities={"companies": ["Tesla"]},
            confidence=0.95,
            reasoning="Test"
        )
        
        # Mock the analysis function to fail
        with patch('tools.orchestrators.full_company_analysis') as mock_analysis:
            mock_analysis.side_effect = Exception("Analysis failed")
            
            # Execute the plan
            result = await self.executor.execute_plan(
                intent_plan, self.context, self.mock_bing_agent, self.mock_analyst_agent
            )
            
            # Verify results
            assert isinstance(result, ExecutionResult)
            assert result.intent_type == "company_briefing"
            assert result.success is False
            assert len(result.results) == 1
            assert result.results[0].success is False
            assert "Analysis failed" in result.results[0].error
    
    @pytest.mark.asyncio
    async def test_mixed_success_failure(self):
        """Test mixed success and failure in task execution."""
        # Create intent plan with multiple tasks
        intent_plan = IntentPlan(
            intent_type=IntentType.MIXED_REQUEST,
            tasks=[
                Task(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target="Apple",
                    parameters={},
                    priority=1
                ),
                Task(
                    task_type=TaskType.GENERAL_RESEARCH,
                    target="Test topic",
                    parameters={},
                    priority=2
                )
            ],
            entities={"companies": ["Apple"]},
            confidence=0.95,
            reasoning="Test"
        )
        
        # Mock the analysis function to succeed
        with patch('tools.orchestrators.full_company_analysis') as mock_analysis:
            mock_briefing = Mock()
            mock_briefing.company.name = "Apple"
            mock_briefing.summary = "Apple analysis summary"
            mock_briefing.events = []
            mock_briefing.gwbs = {}
            mock_analysis.return_value = mock_briefing
            
            # Mock general research to fail
            self.mock_bing_agent.search_general_topic.side_effect = Exception("Research failed")
            
            # Execute the plan
            result = await self.executor.execute_plan(
                intent_plan, self.context, self.mock_bing_agent, self.mock_analyst_agent
            )
            
            # Verify results
            assert isinstance(result, ExecutionResult)
            assert result.intent_type == "mixed_request"
            assert result.success is True  # At least one task succeeded
            assert len(result.results) == 2
            assert result.results[0].success is True
            assert result.results[1].success is False
            assert "Research failed" in result.results[1].error
    
    def test_task_result_creation(self):
        """Test TaskResult creation and properties."""
        # Test successful task result
        success_result = TaskResult(
            task_type=TaskType.COMPANY_BRIEFING,
            target="Tesla",
            success=True,
            data={"summary": "Test summary"},
            citations=[],
            execution_time=1.5
        )
        
        assert success_result.task_type == TaskType.COMPANY_BRIEFING
        assert success_result.target == "Tesla"
        assert success_result.success is True
        assert success_result.data["summary"] == "Test summary"
        assert success_result.execution_time == 1.5
        
        # Test failed task result
        failure_result = TaskResult(
            task_type=TaskType.GENERAL_RESEARCH,
            target="Test topic",
            success=False,
            error="Test error",
            execution_time=0.5
        )
        
        assert failure_result.task_type == TaskType.GENERAL_RESEARCH
        assert failure_result.target == "Test topic"
        assert failure_result.success is False
        assert failure_result.error == "Test error"
        assert failure_result.execution_time == 0.5
    
    def test_execution_result_creation(self):
        """Test ExecutionResult creation and properties."""
        # Create test results
        results = [
            TaskResult(
                task_type=TaskType.COMPANY_BRIEFING,
                target="Tesla",
                success=True,
                data={"summary": "Test summary"},
                citations=[],
                execution_time=1.5
            )
        ]
        
        execution_result = ExecutionResult(
            intent_type="company_briefing",
            success=True,
            results=results,
            combined_summary="Test combined summary",
            all_citations=[],
            execution_time=1.5
        )
        
        assert execution_result.intent_type == "company_briefing"
        assert execution_result.success is True
        assert len(execution_result.results) == 1
        assert execution_result.combined_summary == "Test combined summary"
        assert execution_result.execution_time == 1.5


if __name__ == "__main__":
    pytest.main([__file__])
