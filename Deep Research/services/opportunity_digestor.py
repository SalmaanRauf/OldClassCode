"""
ATLAS-powered opportunity digestor for normalizing Deep Research markdown.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Dict, Any, List, Tuple

from models.bd_schemas import BDTrigger, Opportunity

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_Opportunity_Digest_prompt.txt"


class OpportunityDigestor:
    """Uses existing ATLAS kernel setup to normalize opportunities."""

    def __init__(self, kernel=None, exec_settings=None):
        self._kernel = kernel
        self._exec_settings = exec_settings
        self._prompt_template: str | None = None

    async def _ensure_kernel(self):
        if self._kernel is None:
            from config.kernel_setup import get_kernel_async
            self._kernel, self._exec_settings = await get_kernel_async()

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            if PROMPT_PATH.exists():
                self._prompt_template = PROMPT_PATH.read_text()
            else:
                self._prompt_template = self._fallback_prompt()
        return self._prompt_template

    async def digest(
        self,
        trigger: BDTrigger,
        deep_research_markdown: str,
        max_opportunities: int = 10,
    ) -> Tuple[List[Opportunity], Dict[str, Any]]:
        """Return normalized opportunities and run diagnostics."""
        start = perf_counter()
        diagnostics: Dict[str, Any] = {
            "invoked": True,
            "status": "Failed",
            "reason": None,
            "duration_ms": 0.0,
            "raw_response_text": "",
            "parse_outcome": "",
            "opportunities_returned": 0,
        }

        if not deep_research_markdown or not deep_research_markdown.strip():
            diagnostics["status"] = "Skipped"
            diagnostics["reason"] = "Deep Research markdown was empty."
            diagnostics["parse_outcome"] = "empty_markdown"
            return [], diagnostics

        try:
            await self._ensure_kernel()
            prompt = self._render_prompt(trigger, deep_research_markdown, max_opportunities)

            from semantic_kernel.contents.chat_history import ChatHistory

            history = ChatHistory()
            history.add_user_message(prompt)
            chat = self._kernel.get_service("atlas")
            result = await chat.get_chat_message_content(
                chat_history=history,
                settings=self._exec_settings,
                kernel=self._kernel,
            )
            raw_response = str(result)
            diagnostics["raw_response_text"] = raw_response

            payload = json.loads(self._extract_json(raw_response))
            opportunities = self._coerce_opportunities(payload.get("opportunities", []), max_opportunities)
            diagnostics["opportunities_returned"] = len(opportunities)
            if opportunities:
                diagnostics["status"] = "Succeeded"
                diagnostics["parse_outcome"] = "json_parsed_with_opportunities"
            else:
                diagnostics["status"] = "Failed"
                diagnostics["reason"] = "ATLAS digest returned no opportunities."
                diagnostics["parse_outcome"] = "json_parsed_no_opportunities"
            return opportunities, diagnostics

        except json.JSONDecodeError as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "Could not parse ATLAS digest response as JSON."
            diagnostics["parse_outcome"] = "json_parse_error"
            diagnostics["error_type"] = "JSONDecodeError"
            diagnostics["error_message"] = str(exc)
            logger.warning("Opportunity digest JSON parse failed: %s", exc)
            return [], diagnostics
        except Exception as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "ATLAS digest call failed."
            diagnostics["parse_outcome"] = "digest_failed"
            diagnostics["error_type"] = type(exc).__name__
            diagnostics["error_message"] = str(exc)
            logger.exception("Opportunity digest failed: %s", exc)
            return [], diagnostics
        finally:
            diagnostics["duration_ms"] = (perf_counter() - start) * 1000

    def _render_prompt(self, trigger: BDTrigger, markdown: str, max_opportunities: int) -> str:
        template = self._load_prompt()
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.geography:
            trigger_parts.append(f"Geography: {trigger.geography}")
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")

        prompt = template.replace("{{$trigger_summary}}", "; ".join(trigger_parts))
        prompt = prompt.replace("{{$max_opportunities}}", str(max_opportunities))
        return prompt.replace("{{$deep_research_markdown}}", markdown)

    def _coerce_opportunities(self, items: List[Dict[str, Any]], max_opportunities: int) -> List[Opportunity]:
        opportunities: List[Opportunity] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            scope = (item.get("scope") or "").strip()
            if not title or not scope:
                continue
            confidence = item.get("confidence") or "Medium"
            if confidence not in ("High", "Medium", "Low"):
                confidence = "Medium"
            opportunities.append(
                Opportunity(
                    title=title,
                    agency=item.get("agency"),
                    scope=scope,
                    estimated_value=item.get("estimated_value"),
                    timeline=item.get("timeline"),
                    incumbent=item.get("incumbent"),
                    cmmc_level=item.get("cmmc_level"),
                    confidence=confidence,
                    citations=[],
                )
            )
            if len(opportunities) >= max_opportunities:
                break
        return opportunities

    def _extract_json(self, text: str) -> str:
        cleaned = text.strip()
        if "```" in cleaned:
            lines = cleaned.splitlines()
            json_lines: List[str] = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or (not in_block and "{" in line):
                    json_lines.append(line)
            cleaned = "\n".join(json_lines).strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            return cleaned[start:end]
        return cleaned

    def _fallback_prompt(self) -> str:
        return (
            "Return JSON with opportunities from this markdown.\n"
            "Trigger: {{$trigger_summary}}\n"
            "Max opportunities: {{$max_opportunities}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
