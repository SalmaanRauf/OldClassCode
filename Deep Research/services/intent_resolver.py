"""
Intent Resolution Service - LLM-based intent resolution with rule-based fallback.

This service analyzes user input to determine what tasks need to be executed,
using an LLM for complex pattern recognition while falling back to rule-based
routing for reliability.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from semantic_kernel.functions.kernel_arguments import KernelArguments
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.contents.text_content import TextContent
from services.conversation_manager import ConversationContext, QueryRouter, QueryType

logger = logging.getLogger(__name__)

class IntentType(Enum):
    """Types of user intents that can be resolved."""
    COMPANY_BRIEFING = "company_briefing"
    GENERAL_RESEARCH = "general_research"
    MIXED_REQUEST = "mixed_request"
    FOLLOW_UP = "follow_up"
    COMPARISON = "comparison"
    CLARIFICATION = "clarification"

class TaskType(Enum):
    """Types of tasks that can be executed."""
    COMPANY_BRIEFING = "company_briefing"
    GENERAL_RESEARCH = "general_research"
    COMPETITOR_ANALYSIS = "competitor_analysis"
    COMPARISON = "comparison"
    FOLLOW_UP = "follow_up"

@dataclass
class Task:
    """Represents a single task to be executed."""
    task_type: TaskType
    target: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1  # Lower number = higher priority

@dataclass
class IntentPlan:
    """Represents the resolved intent and execution plan."""
    intent_type: IntentType
    tasks: List[Task] = field(default_factory=list)
    entities: Dict[str, List[str]] = field(default_factory=dict)
    confidence: float = 0.0
    reasoning: str = ""
    
    @classmethod
    def from_json(cls, json_data: Dict[str, Any]) -> "IntentPlan":
        """Create IntentPlan from JSON data."""
        try:
            intent_type_raw = json_data.get("intent_type", "clarification")
            intent_type = cls._coerce_intent_type(intent_type_raw)
            tasks = []
            for task_data in json_data.get("tasks", []):
                task_type_raw = task_data.get("task_type", "general_research")
                task = Task(
                    task_type=cls._coerce_task_type(task_type_raw),
                    target=task_data.get("target", ""),
                    parameters=task_data.get("parameters", {}),
                    priority=task_data.get("priority", 1)
                )
                tasks.append(task)
            
            return cls(
                intent_type=intent_type,
                tasks=tasks,
                entities=json_data.get("entities", {}),
                confidence=json_data.get("confidence", 0.0),
                reasoning=json_data.get("reasoning", "")
            )
        except Exception as e:
            logger.error(f"Failed to parse IntentPlan from JSON: {e}")
            return cls(intent_type=IntentType.CLARIFICATION)

    @staticmethod
    def _coerce_intent_type(value: Any) -> IntentType:
        """Convert arbitrary intent type strings to IntentType enum."""
        if isinstance(value, IntentType):
            return value

        text = str(value or "clarification").strip()
        # Try by value match (case insensitive)
        for member in IntentType:
            if member.value.lower() == text.lower():
                return member
        # Try by enum name (case insensitive)
        try:
            return IntentType[text.upper()]
        except Exception:
            logger.warning(f"Unknown intent_type '{value}', defaulting to CLARIFICATION")
            return IntentType.CLARIFICATION

    @staticmethod
    def _coerce_task_type(value: Any) -> TaskType:
        """Convert arbitrary task type strings to TaskType enum."""
        if isinstance(value, TaskType):
            return value

        text = str(value or "general_research").strip()
        for member in TaskType:
            if member.value.lower() == text.lower():
                return member
        try:
            return TaskType[text.upper()]
        except Exception:
            logger.warning(f"Unknown task_type '{value}', defaulting to GENERAL_RESEARCH")
            return TaskType.GENERAL_RESEARCH

class IntentResolver:
    """Resolves user intent using LLM with rule-based fallback."""
    
    def __init__(self):
        self.rule_router = QueryRouter()
        self._llm_available = True
        logger.info("IntentResolver initialized with LLM + rule fallback")
    
    async def resolve_intent(self, user_input: str, context: ConversationContext) -> IntentPlan:
        """
        Resolve user intent using LLM with rule-based fallback.
        
        Args:
            user_input: The user's input text
            context: Current conversation context
            
        Returns:
            IntentPlan with resolved intent and execution tasks
        """
        user_input = user_input.strip()
        if not user_input:
            return IntentPlan(intent_type=IntentType.CLARIFICATION)
        
        # Try LLM-based resolution first
        if self._llm_available:
            try:
                llm_plan = await self._llm_resolve_intent(user_input, context)
                if llm_plan and llm_plan.confidence > 0.7:
                    logger.info(f"LLM resolved intent: {llm_plan.intent_type.value} (confidence: {llm_plan.confidence})")
                    return llm_plan
                else:
                    logger.warning(f"LLM resolution low confidence: {llm_plan.confidence if llm_plan else 'None'}")
            except Exception as e:
                logger.warning(f"LLM intent resolution failed: {e}")
                self._llm_available = False
        
        # Fallback to rule-based routing
        logger.info("Falling back to rule-based intent resolution")
        return await self._rule_based_resolve_intent(user_input, context)
    
    async def _llm_resolve_intent(self, user_input: str, context: ConversationContext) -> Optional[IntentPlan]:
        """Resolve intent using LLM."""
        try:
            # Import here to avoid circular imports
            from config.kernel_setup import get_kernel_async
            
            kernel, exec_settings = await get_kernel_async()
            
            # Create the prompt
            prompt = self._create_intent_prompt(user_input, context)
            
            # Get LLM response
            result = await kernel.invoke(
                function_name="intent_resolver",
                plugin_name="intent_plugin",
                arguments=KernelArguments(input=prompt)
            )
            
            # Parse the response
            raw_payload = self._extract_response_text(result)
            if raw_payload is None:
                raise ValueError("Intent resolver received empty response from LLM")

            logger.debug("Intent resolver raw payload before parsing: %s", raw_payload)
            json_data = self._parse_llm_response(raw_payload)
            return IntentPlan.from_json(json_data)
            
        except Exception as e:
            logger.error(f"LLM intent resolution error: {e}")
            return None

    def _extract_response_text(self, result) -> Optional[str]:
        """Extract textual content from Semantic Kernel invoke result."""
        value = getattr(result, "value", result)

        text = self._extract_text(value)
        if text:
            return text.strip()
        return None

    def _extract_text(self, value) -> Optional[str]:
        """Recursively extract text from SK content objects."""
        if value is None:
            return None

        if isinstance(value, str):
            return value

        if isinstance(value, TextContent):
            return value.text

        if isinstance(value, ChatMessageContent):
            if getattr(value, "content", None):
                return value.content
            for item in getattr(value, "items", []) or []:
                extracted = self._extract_text(item)
                if extracted:
                    return extracted
            return None

        if isinstance(value, (list, tuple)):
            for entry in value:
                extracted = self._extract_text(entry)
                if extracted:
                    return extracted
            return None

        # Some SK types expose `.text` or `.content` attributes
        for attr in ("text", "content"):
            attr_value = getattr(value, attr, None)
            if isinstance(attr_value, str):
                return attr_value

        return None

    def _parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """Extract JSON object from LLM response with defensive cleanup."""
        cleaned = response_text.strip()

        # Trim fenced code blocks
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        if cleaned.startswith('```'):
            cleaned = cleaned[3:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()

        # Remove wrapping quotes the model occasionally adds
        if (
            (cleaned.startswith("'") and cleaned.endswith("'"))
            or (cleaned.startswith('"') and cleaned.endswith('"'))
        ):
            cleaned = cleaned[1:-1]

        cleaned = cleaned.strip()
        logger.debug(f"Intent resolver raw response after cleanup: {cleaned}")

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Fallback to extracting first JSON object substring
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start:end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError as inner:
                    logger.error(f"Failed to parse candidate JSON: {inner}. Candidate: {candidate}")
                    raise
            logger.error(f"Unable to locate JSON object in LLM response: {cleaned}")
            raise
    
    def _create_intent_prompt(self, user_input: str, context: ConversationContext) -> str:
        """Create the prompt for LLM intent resolution."""
        current_company = context.current_company.get("name") if context.current_company else None
        
        return f"""
Analyze this user request and determine what tasks need to be executed.

User Input: "{user_input}"
Current Context: {current_company or "None"}

Available Task Types:
- COMPANY_BRIEFING: Full analysis of a specific company (SEC, news, earnings, etc.)
- GENERAL_RESEARCH: Research on topics, industries, markets, rankings
- COMPETITOR_ANALYSIS: Find competitors of a company
- COMPARISON: Compare multiple companies
- FOLLOW_UP: Answer based on existing context

Examples:
- "Tell me about Capital One" → COMPANY_BRIEFING
- "What are the top financial companies?" → GENERAL_RESEARCH
- "Tell me about Capital One and its competitors" → MIXED_REQUEST
- "What about their earnings?" → FOLLOW_UP (if context exists)

Return ONLY a valid JSON object:
{{
    "intent_type": "COMPANY_BRIEFING|GENERAL_RESEARCH|MIXED_REQUEST|FOLLOW_UP|COMPARISON|CLARIFICATION",
    "tasks": [
        {{
            "task_type": "COMPANY_BRIEFING|GENERAL_RESEARCH|COMPETITOR_ANALYSIS|COMPARISON|FOLLOW_UP",
            "target": "company name or research topic",
            "parameters": {{}},
            "priority": 1
        }}
    ],
    "entities": {{
        "companies": ["Company Name"],
        "topics": ["research topics"],
        "locations": ["geographic locations"]
    }},
    "confidence": 0.95,
    "reasoning": "Brief explanation of the resolution"
}}
"""
    
    async def _rule_based_resolve_intent(self, user_input: str, context: ConversationContext) -> IntentPlan:
        """Fallback to rule-based intent resolution."""
        try:
            # Use existing QueryRouter
            query_type, payload = self.rule_router.route(user_input, context)
            
            # Convert QueryType to IntentType
            intent_mapping = {
                QueryType.NEW_ANALYSIS: IntentType.COMPANY_BRIEFING,
                QueryType.FOLLOW_UP: IntentType.FOLLOW_UP,
                QueryType.COMPARE_COMPANIES: IntentType.COMPARISON,
                QueryType.GENERAL_RESEARCH: IntentType.GENERAL_RESEARCH,
                QueryType.CLARIFICATION: IntentType.CLARIFICATION,
                QueryType.UNKNOWN: IntentType.CLARIFICATION
            }
            
            intent_type = intent_mapping.get(query_type, IntentType.CLARIFICATION)
            
            # Create tasks based on query type
            tasks = []
            entities = {"companies": [], "topics": [], "locations": []}
            
            if query_type == QueryType.NEW_ANALYSIS and payload.get("company"):
                company = payload["company"]
                tasks.append(Task(
                    task_type=TaskType.COMPANY_BRIEFING,
                    target=company.get("name", ""),
                    parameters={"ticker": company.get("ticker")}
                ))
                entities["companies"].append(company.get("name", ""))
                
            elif query_type == QueryType.GENERAL_RESEARCH:
                tasks.append(Task(
                    task_type=TaskType.GENERAL_RESEARCH,
                    target=payload.get("prompt", user_input),
                    parameters={}
                ))
                
            elif query_type == QueryType.COMPARE_COMPANIES and payload.get("companies"):
                companies = payload["companies"]
                for company in companies:
                    tasks.append(Task(
                        task_type=TaskType.COMPANY_BRIEFING,
                        target=company,
                        parameters={}
                    ))
                    entities["companies"].append(company)
                tasks.append(Task(
                    task_type=TaskType.COMPARISON,
                    target="comparison",
                    parameters={"companies": companies}
                ))
                
            elif query_type == QueryType.FOLLOW_UP:
                tasks.append(Task(
                    task_type=TaskType.FOLLOW_UP,
                    target=user_input,
                    parameters={}
                ))
            
            return IntentPlan(
                intent_type=intent_type,
                tasks=tasks,
                entities=entities,
                confidence=0.8,  # Rule-based confidence
                reasoning="Rule-based resolution"
            )
            
        except Exception as e:
            logger.error(f"Rule-based intent resolution failed: {e}")
            return IntentPlan(
                intent_type=IntentType.CLARIFICATION,
                reasoning=f"Resolution failed: {e}"
            )

# Global intent resolver instance
intent_resolver = IntentResolver()
