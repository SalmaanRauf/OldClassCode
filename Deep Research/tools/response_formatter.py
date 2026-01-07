"""
Response Formatter - Formats different types of responses consistently.

This module provides unified formatting for different types of responses
including company briefings, general research, mixed requests, and follow-ups.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from models.schemas import Briefing, Citation
from tools.task_executor import ExecutionResult, TaskResult
from services.intent_resolver import IntentType, TaskType

logger = logging.getLogger(__name__)

class ResponseFormatter:
    """Formats execution results into user-friendly responses."""
    
    def __init__(self):
        logger.info("ResponseFormatter initialized")
    
    def format_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """
        Format execution result into a unified response.
        
        Args:
            execution_result: The result of task execution
            
        Returns:
            Dict with formatted response data
        """
        if not execution_result.success:
            return self._format_error_response(execution_result)
        
        # Format based on intent type
        if execution_result.intent_type == IntentType.COMPANY_BRIEFING.value:
            return self._format_company_briefing_response(execution_result)
        elif execution_result.intent_type == IntentType.GENERAL_RESEARCH.value:
            return self._format_general_research_response(execution_result)
        elif execution_result.intent_type == IntentType.MIXED_REQUEST.value:
            return self._format_mixed_request_response(execution_result)
        elif execution_result.intent_type == IntentType.COMPARISON.value:
            return self._format_comparison_response(execution_result)
        elif execution_result.intent_type == IntentType.FOLLOW_UP.value:
            return self._format_follow_up_response(execution_result)
        else:
            return self._format_generic_response(execution_result)
    
    def _format_company_briefing_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format company briefing response."""
        briefing_result = next((r for r in execution_result.results if r.task_type == TaskType.COMPANY_BRIEFING), None)
        
        if not briefing_result or not briefing_result.success:
            return self._format_error_response(execution_result)
        
        briefing = briefing_result.data
        if not isinstance(briefing, Briefing):
            return self._format_generic_response(execution_result)
        
        # Format the briefing data
        formatted_sections = []
        for scope, section_summary in (briefing.sections or {}).items():
            if not section_summary:
                continue
            formatted_sections.append(
                {
                    "task_type": scope,
                    "target": briefing.company.name,
                    "content": section_summary,
                }
            )

        unique_events = []
        seen_event_keys = set()
        for event in briefing.events:
            meta = getattr(event, "meta", {}) if hasattr(event, "meta") else event.get("meta", {}) if isinstance(event, dict) else {}
            raw_data = meta.get("raw_data", {}) if isinstance(meta, dict) else {}
            scope = raw_data.get("scope") if isinstance(raw_data, dict) else None
            key = (briefing.company.name, scope or getattr(event, "title", None))
            if key in seen_event_keys:
                continue
            seen_event_keys.add(key)
            unique_events.append(event)

        response = {
            "type": "company_briefing",
            "company": briefing.company.name,
            "summary": briefing.summary,
            "events": [self._format_event(event) for event in unique_events],
            "sections": formatted_sections,
            "raw_gwbs": self._serialize_gwbs_sections(briefing),
            "citations": self._format_citations(execution_result.all_citations),
            "execution_time": execution_result.execution_time
        }
        
        return response
    
    def _format_general_research_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format general research response."""
        research_result = next((r for r in execution_result.results if r.task_type == TaskType.GENERAL_RESEARCH), None)
        
        if not research_result or not research_result.success:
            return self._format_error_response(execution_result)
        
        data = research_result.data
        if isinstance(data, dict) and 'summary' in data:
            summary = data['summary']
        else:
            summary = execution_result.combined_summary
        
        response = {
            "type": "general_research",
            "summary": summary,
            "citations": self._format_citations(execution_result.all_citations),
            "execution_time": execution_result.execution_time
        }
        
        return response
    
    def _format_mixed_request_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format mixed request response (e.g., company briefing + competitor analysis)."""
        response = {
            "type": "mixed_request",
            "summary": execution_result.combined_summary,
            "sections": [],
            "citations": self._format_citations(execution_result.all_citations),
            "execution_time": execution_result.execution_time
        }
        
        # Add sections for each successful task
        for result in execution_result.results:
            if not result.success:
                continue
                
            section = {
                "task_type": result.task_type.value,
                "target": result.target,
                "content": ""
            }
            
            if result.task_type == TaskType.COMPANY_BRIEFING and hasattr(result.data, 'summary'):
                section["content"] = result.data.summary
                section["events"] = [self._format_event(event) for event in result.data.events]
                section["raw_gwbs"] = self._serialize_gwbs_sections(result.data)
            elif isinstance(result.data, dict):
                if 'summary' in result.data:
                    section["content"] = result.data['summary']
                elif 'answer' in result.data:
                    section["content"] = result.data['answer']
            
            response["sections"].append(section)
        
        return response
    
    def _format_comparison_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format company comparison response."""
        comparison_result = next((r for r in execution_result.results if r.task_type == TaskType.COMPARISON), None)
        
        if not comparison_result or not comparison_result.success:
            return self._format_error_response(execution_result)
        
        data = comparison_result.data
        if isinstance(data, dict) and 'briefings' in data:
            briefings = data['briefings']
            companies = data.get('companies', [])
            
            response = {
                "type": "comparison",
                "companies": companies,
                "briefings": [],
                "citations": self._format_citations(execution_result.all_citations),
                "execution_time": execution_result.execution_time
            }
            
            for briefing in briefings:
                if isinstance(briefing, Briefing):
                    response["briefings"].append({
                        "company": briefing.company.name,
                        "summary": briefing.summary,
                        "events": [self._format_event(event) for event in briefing.events]
                    })
            
            return response
        
        return self._format_generic_response(execution_result)
    
    def _format_follow_up_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format follow-up response."""
        follow_up_result = next((r for r in execution_result.results if r.task_type == TaskType.FOLLOW_UP), None)
        
        if not follow_up_result or not follow_up_result.success:
            return self._format_error_response(execution_result)
        
        data = follow_up_result.data
        if isinstance(data, dict) and 'answer' in data:
            answer = data['answer']
        else:
            answer = execution_result.combined_summary
        
        response = {
            "type": "follow_up",
            "answer": answer,
            "citations": self._format_citations(execution_result.all_citations),
            "execution_time": execution_result.execution_time
        }
        
        return response
    
    def _format_generic_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format generic response for unknown types."""
        return {
            "type": "generic",
            "summary": execution_result.combined_summary,
            "citations": self._format_citations(execution_result.all_citations),
            "execution_time": execution_result.execution_time
        }
    
    def _format_error_response(self, execution_result: ExecutionResult) -> Dict[str, Any]:
        """Format error response."""
        error_messages = []
        for result in execution_result.results:
            if not result.success and result.error:
                error_messages.append(f"{result.task_type.value}: {result.error}")
        
        return {
            "type": "error",
            "error": "Task execution failed",
            "details": error_messages,
            "execution_time": execution_result.execution_time
        }
    
    def _format_event(self, event) -> Dict[str, Any]:
        """Format an analysis event."""
        if hasattr(event, 'dict'):
            return event.dict()
        elif isinstance(event, dict):
            return event
        else:
            return {"title": str(event), "insights": {}}
    
    def _format_citations(self, citations: List[Citation]) -> List[Dict[str, str]]:
        """Format citations for display."""
        formatted_citations = []
        seen_urls = set()
        
        for citation in citations:
            if citation.url not in seen_urls:
                formatted_citations.append({
                    "title": citation.title or citation.url,
                    "url": citation.url
                })
                seen_urls.add(citation.url)
        
        return formatted_citations

    def _serialize_gwbs_sections(self, briefing: Briefing) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        raw_sections = getattr(briefing, "gwbs", {}) or {}

        for scope, section in raw_sections.items():
            if isinstance(section, dict):
                summary = section.get("summary", "")
                citations = section.get("citations", [])
                audit = section.get("audit", {})
            else:
                summary = getattr(section, "summary", "")
                citations = getattr(section, "citations", [])
                audit = getattr(section, "audit", {}) or {}

            formatted_citations: List[Dict[str, str]] = []
            for citation in citations or []:
                if isinstance(citation, dict):
                    url = citation.get("url")
                    title = citation.get("title")
                else:
                    url = getattr(citation, "url", None)
                    title = getattr(citation, "title", None)
                if url:
                    formatted_citations.append({"title": title or url, "url": url})

            serialized.append(
                {
                    "scope": scope,
                    "title": scope.replace("_", " ").title(),
                    "summary": summary,
                    "citations": formatted_citations,
                    "audit": audit,
                }
            )

        return serialized

# Global response formatter instance
response_formatter = ResponseFormatter()
