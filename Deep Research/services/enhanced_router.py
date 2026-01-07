"""
Enhanced Query Router - Uses intent resolver with fallback to rule-based routing.

This module provides an enhanced routing system that uses LLM-based intent
resolution for complex requests while maintaining rule-based fallback for
reliability and performance.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Tuple
from services.conversation_manager import ConversationContext, QueryType
from services.intent_resolver import IntentResolver, IntentType, IntentPlan

logger = logging.getLogger(__name__)

class EnhancedQueryRouter:
    """Enhanced router that uses intent resolver with rule-based fallback."""
    
    def __init__(self):
        self.intent_resolver = IntentResolver()
        self._use_intent_resolver = True
        logger.info("EnhancedQueryRouter initialized")
    
    async def route_enhanced(self, user_text: str, ctx: ConversationContext) -> Tuple[IntentType, IntentPlan]:
        """
        Route user input using enhanced intent resolution.
        
        Args:
            user_text: User input text
            ctx: Conversation context
            
        Returns:
            Tuple of (IntentType, IntentPlan)
        """
        user_text = user_text.strip()
        if not user_text:
            return IntentType.CLARIFICATION, IntentPlan(intent_type=IntentType.CLARIFICATION)
        
        # Try intent resolver first
        if self._use_intent_resolver:
            try:
                intent_plan = await self.intent_resolver.resolve_intent(user_text, ctx)
                logger.info(f"Intent resolved: {intent_plan.intent_type.value} (confidence: {intent_plan.confidence})")
                return intent_plan.intent_type, intent_plan
            except Exception as e:
                logger.warning(f"Intent resolver failed, falling back to rules: {e}")
                self._use_intent_resolver = False
        
        # Fallback to rule-based routing
        return await self._rule_based_route(user_text, ctx)
    
    async def _rule_based_route(self, user_text: str, ctx: ConversationContext) -> Tuple[IntentType, IntentPlan]:
        """Fallback to rule-based routing using existing QueryRouter."""
        try:
            from services.conversation_manager import QueryRouter
            rule_router = QueryRouter()
            query_type, payload = rule_router.route(user_text, ctx)
            
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
            
            # Create basic intent plan from rule-based result
            from services.intent_resolver import Task, TaskType
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
                    target=payload.get("prompt", user_text),
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
                    target=user_text,
                    parameters={}
                ))
            
            intent_plan = IntentPlan(
                intent_type=intent_type,
                tasks=tasks,
                entities=entities,
                confidence=0.8,  # Rule-based confidence
                reasoning="Rule-based resolution"
            )
            
            return intent_type, intent_plan
            
        except Exception as e:
            logger.error(f"Rule-based routing failed: {e}")
            return IntentType.CLARIFICATION, IntentPlan(
                intent_type=IntentType.CLARIFICATION,
                reasoning=f"Routing failed: {e}"
            )

# Global enhanced router instance
enhanced_router = EnhancedQueryRouter()
