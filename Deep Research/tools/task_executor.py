"""
Task Executor - Coordinates parallel execution of multiple tasks.

This module handles the execution of multiple tasks concurrently and
synthesizes the results into a unified response.
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from services.intent_resolver import Task, TaskType, IntentPlan
from services.conversation_manager import ConversationContext
from models.schemas import CompanyRef, Citation, Briefing, GWBSSection
from tools.orchestrators import full_company_analysis, follow_up_research, competitor_analysis, general_research
from tools.general_research_orchestrator import GeneralResearchOrchestrator

logger = logging.getLogger(__name__)

@dataclass
class TaskResult:
    """Result of a single task execution."""
    task_type: TaskType
    target: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    citations: List[Citation] = field(default_factory=list)
    execution_time: float = 0.0

@dataclass
class ExecutionResult:
    """Result of executing a complete intent plan."""
    intent_type: str
    success: bool
    results: List[TaskResult] = field(default_factory=list)
    combined_summary: str = ""
    all_citations: List[Citation] = field(default_factory=list)
    execution_time: float = 0.0

class TaskExecutor:
    """Executes multiple tasks concurrently and synthesizes results."""
    
    def __init__(self):
        self.general_research_orchestrator = None
        logger.info("TaskExecutor initialized")
    
    def set_general_research_orchestrator(self, orchestrator: GeneralResearchOrchestrator):
        """Set the general research orchestrator."""
        self.general_research_orchestrator = orchestrator
    
    async def execute_plan(self, intent_plan: IntentPlan, context: ConversationContext, 
                          bing_agent, analyst_agent) -> ExecutionResult:
        """
        Execute all tasks in the intent plan concurrently.
        
        Args:
            intent_plan: The resolved intent plan
            context: Conversation context
            bing_agent: Bing data extraction agent
            analyst_agent: Analyst agent for synthesis
            
        Returns:
            ExecutionResult with all task results
        """
        import time
        start_time = time.time()
        
        logger.info(f"Executing intent plan: {intent_plan.intent_type.value} with {len(intent_plan.tasks)} tasks")
        
        # Sort tasks by priority
        sorted_tasks = sorted(intent_plan.tasks, key=lambda t: t.priority)
        
        # Execute tasks concurrently
        task_coroutines = []
        for task in sorted_tasks:
            coro = self._execute_single_task(task, context, bing_agent, analyst_agent)
            task_coroutines.append(coro)
        
        # Wait for all tasks to complete
        task_results = await asyncio.gather(*task_coroutines, return_exceptions=True)
        
        # Process results
        results = []
        for i, result in enumerate(task_results):
            if isinstance(result, Exception):
                logger.error(f"Task {i} failed with exception: {result}")
                results.append(TaskResult(
                    task_type=sorted_tasks[i].task_type,
                    target=sorted_tasks[i].target,
                    success=False,
                    error=str(result)
                ))
            else:
                results.append(result)
        
        # Synthesize results
        execution_time = time.time() - start_time
        combined_summary = self._synthesize_results(results, intent_plan.intent_type.value)
        all_citations = self._collect_all_citations(results)
        
        return ExecutionResult(
            intent_type=intent_plan.intent_type.value,
            success=any(r.success for r in results),
            results=results,
            combined_summary=combined_summary,
            all_citations=all_citations,
            execution_time=execution_time
        )
    
    async def _execute_single_task(self, task: Task, context: ConversationContext, 
                                 bing_agent, analyst_agent) -> TaskResult:
        """Execute a single task."""
        import time
        start_time = time.time()
        
        try:
            logger.info(f"Executing task: {task.task_type.value} for '{task.target}'")
            
            if task.task_type == TaskType.COMPANY_BRIEFING:
                result = await self._execute_company_briefing(task, context, bing_agent, analyst_agent)
            elif task.task_type == TaskType.GENERAL_RESEARCH:
                result = await self._execute_general_research(task, context, bing_agent)
            elif task.task_type == TaskType.COMPETITOR_ANALYSIS:
                result = await self._execute_competitor_analysis(task, context, bing_agent)
            elif task.task_type == TaskType.COMPARISON:
                result = await self._execute_comparison(task, context, bing_agent, analyst_agent)
            elif task.task_type == TaskType.FOLLOW_UP:
                result = await self._execute_follow_up(task, context, bing_agent, analyst_agent)
            else:
                raise ValueError(f"Unknown task type: {task.task_type}")
            
            execution_time = time.time() - start_time
            result.execution_time = execution_time
            
            logger.info(f"Task completed: {task.task_type.value} in {execution_time:.2f}s")
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Task failed: {task.task_type.value} - {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e),
                execution_time=execution_time
            )
    
    async def _execute_company_briefing(self, task: Task, context: ConversationContext, 
                                      bing_agent, analyst_agent) -> TaskResult:
        """Execute company briefing task."""
        try:
            company_ref = CompanyRef(
                name=task.target,
                ticker=task.parameters.get("ticker")
            )
            
            briefing = await full_company_analysis(
                company_ref,
                bing_agent=bing_agent,
                analyst_agent=analyst_agent
            )
            
            # Collect citations from briefing
            citations = []
            if hasattr(briefing, 'gwbs') and briefing.gwbs:
                for section in briefing.gwbs.values():
                    if hasattr(section, 'citations'):
                        citations.extend(section.citations)
            
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=True,
                data=briefing,
                citations=citations
            )
            
        except Exception as e:
            logger.error(f"Company briefing failed: {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e)
            )
    
    async def _execute_general_research(self, task: Task, context: ConversationContext, 
                                      bing_agent) -> TaskResult:
        """Execute general research task."""
        try:
            if not self.general_research_orchestrator:
                # Fallback to direct Bing agent call
                result = bing_agent.search_general_topic(task.target)
                summary = result.get("summary", "")
                citations = self._extract_citations_from_result(result)
            else:
                summary, citations = await self.general_research_orchestrator.execute_general_research(
                    task.target, task.parameters
                )
            
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=True,
                data={"summary": summary, "citations": citations},
                citations=citations
            )
            
        except Exception as e:
            logger.error(f"General research failed: {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e)
            )
    
    async def _execute_competitor_analysis(self, task: Task, context: ConversationContext, 
                                         bing_agent) -> TaskResult:
        """Execute competitor analysis task."""
        try:
            result = bing_agent.search_competitor_analysis(task.target)
            summary = result.get("summary", "")
            citations = self._extract_citations_from_result(result)
            
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=True,
                data={"summary": summary, "citations": citations},
                citations=citations
            )
            
        except Exception as e:
            logger.error(f"Competitor analysis failed: {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e)
            )
    
    async def _execute_comparison(self, task: Task, context: ConversationContext, 
                                bing_agent, analyst_agent) -> TaskResult:
        """Execute company comparison task."""
        try:
            companies = task.parameters.get("companies", [])
            if not companies:
                raise ValueError("No companies specified for comparison")
            
            # Execute briefings for all companies
            briefings = []
            for company in companies:
                company_ref = CompanyRef(name=company)
                briefing = await full_company_analysis(
                    company_ref,
                    bing_agent=bing_agent,
                    analyst_agent=analyst_agent
                )
                briefings.append(briefing)
            
            # Collect all citations
            all_citations = []
            for briefing in briefings:
                if hasattr(briefing, 'gwbs') and briefing.gwbs:
                    for section in briefing.gwbs.values():
                        if hasattr(section, 'citations'):
                            all_citations.extend(section.citations)
            
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=True,
                data={"briefings": briefings, "companies": companies},
                citations=all_citations
            )
            
        except Exception as e:
            logger.error(f"Comparison failed: {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e)
            )
    
    async def _execute_follow_up(self, task: Task, context: ConversationContext, 
                               bing_agent, analyst_agent) -> TaskResult:
        """Execute follow-up task."""
        try:
            # Get current company from context
            current_company = context.current_company
            if not current_company:
                raise ValueError("No current company for follow-up")
            
            company_ref = CompanyRef(
                name=current_company.get("name", ""),
                ticker=current_company.get("ticker")
            )
            
            # Get existing analysis for context
            existing_analysis = context.get_analysis()
            ctx_blob = existing_analysis.to_dict() if existing_analysis else None
            
            answer, citations = await follow_up_research(
                company_ref,
                task.target,
                bing_agent=bing_agent,
                analyst_agent=analyst_agent,
                ctx_blob=ctx_blob
            )
            
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=True,
                data={"answer": answer, "citations": citations},
                citations=citations
            )
            
        except Exception as e:
            logger.error(f"Follow-up failed: {e}")
            return TaskResult(
                task_type=task.task_type,
                target=task.target,
                success=False,
                error=str(e)
            )
    
    def _extract_citations_from_result(self, result: Dict[str, Any]) -> List[Citation]:
        """Extract citations from Bing agent result."""
        citations = []
        citations_md = result.get("citations_md", "")
        
        if citations_md:
            import re
            for line in citations_md.splitlines():
                line = line.strip()
                if not line.startswith('- ['):
                    continue
                
                match = re.match(r'^- \[(?P<title>[^\]]+)\]\((?P<url>https?://[^)]+)\)', line)
                if match:
                    try:
                        citations.append(Citation(
                            title=match.group('title'),
                            url=match.group('url')
                        ))
                    except Exception:
                        continue
        
        return citations
    
    def _synthesize_results(self, results: List[TaskResult], intent_type: str) -> str:
        """Synthesize multiple task results into a combined summary."""
        if not results:
            return "No results to synthesize."
        
        successful_results = [r for r in results if r.success]
        if not successful_results:
            return "All tasks failed to execute successfully."
        
        if len(successful_results) == 1:
            result = successful_results[0]
            if result.task_type == TaskType.COMPANY_BRIEFING and hasattr(result.data, 'summary'):
                return result.data.summary
            elif isinstance(result.data, dict) and 'summary' in result.data:
                return result.data['summary']
            elif isinstance(result.data, dict) and 'answer' in result.data:
                return result.data['answer']
            else:
                return f"Completed {result.task_type.value} for {result.target}"
        
        # Multiple results - create combined summary
        summary_parts = []
        
        for result in successful_results:
            if result.task_type == TaskType.COMPANY_BRIEFING and hasattr(result.data, 'summary'):
                summary_parts.append(f"**{result.target} Analysis:**\n{result.data.summary}")
            elif isinstance(result.data, dict) and 'summary' in result.data:
                summary_parts.append(f"**{result.target} Research:**\n{result.data['summary']}")
            elif isinstance(result.data, dict) and 'answer' in result.data:
                summary_parts.append(f"**{result.target} Follow-up:**\n{result.data['answer']}")
            else:
                summary_parts.append(f"**{result.target}:** Completed {result.task_type.value}")
        
        return "\n\n".join(summary_parts)
    
    def _collect_all_citations(self, results: List[TaskResult]) -> List[Citation]:
        """Collect all citations from all results."""
        all_citations = []
        seen_urls = set()
        
        for result in results:
            if result.citations:
                for citation in result.citations:
                    if citation.url not in seen_urls:
                        all_citations.append(citation)
                        seen_urls.add(citation.url)
        
        return all_citations

# Global task executor instance
task_executor = TaskExecutor()
