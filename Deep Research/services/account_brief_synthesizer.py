"""
Bounded synthesis for the compact analyst account brief.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from models.bd_schemas import (
    BDTrigger,
    CredentialsResponse,
    DeepResearchOutput,
    PhaseOpportunity,
    SignalEvidence,
)
from services.semantic_kernel_compat import create_chat_history


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_Account_Brief_Synthesis_prompt.txt"
SynthesisRunner = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class SynthesizedSuggestedPlay:
    play: str
    why_now: str


@dataclass(frozen=True)
class AccountBriefSynthesisResult:
    account_summary: str
    signal_summary: List[str]
    opportunity_summary: List[str]
    takeaway: str
    company_overview: str = ""
    strategic_priorities: List[str] = field(default_factory=list)
    financial_filing_signals: List[str] = field(default_factory=list)
    competitive_context: List[str] = field(default_factory=list)
    customer_contract_signals: List[str] = field(default_factory=list)
    likely_needs: List[str] = field(default_factory=list)
    suggested_plays: List[SynthesizedSuggestedPlay] = field(default_factory=list)
    people_to_prioritize: List[str] = field(default_factory=list)
    recent_people_moves: List[str] = field(default_factory=list)
    buying_triggers: List[str] = field(default_factory=list)
    relationship_hooks: List[str] = field(default_factory=list)
    recommended_asks: List[str] = field(default_factory=list)
    analyst_follow_ups: List[str] = field(default_factory=list)


class AccountBriefSynthesizer:
    """Generate a compact analyst-layer brief from structured evidence only."""

    def __init__(
        self,
        *,
        runner: Optional[SynthesisRunner] = None,
        kernel=None,
        exec_settings=None,
    ) -> None:
        self._runner = runner
        self._kernel = kernel
        self._exec_settings = exec_settings
        self._prompt_template: Optional[str] = None

    async def _ensure_kernel(self) -> None:
        if self._kernel is None:
            from config.kernel_setup import get_kernel_async

            self._kernel, self._exec_settings = await get_kernel_async()

    def build_input(
        self,
        *,
        run_id: Optional[str] = None,
        trigger: Optional[BDTrigger] = None,
        research: Optional[DeepResearchOutput] = None,
        credentials: Optional[Dict[str, CredentialsResponse]] = None,
        opportunity_extraction_status: str = "Parsed",
        opportunity_extraction_reason: Optional[str] = None,
        opportunities_extracted_count: int = 0,
        lookups_executed_count: int = 0,
        lookups_skipped_reason: Optional[str] = None,
        credentials_status_counts: Optional[Dict[str, int]] = None,
        confirmed_signal_evidence: Optional[List[SignalEvidence]] = None,
        phase3_candidates: Optional[List[PhaseOpportunity]] = None,
        allowed_sources: Optional[List[str]] = None,
        preflight_context: Optional[Dict[str, Any]] = None,
        request_context: Optional[Dict[str, Any]] = None,
        proconnect_summary: Optional[Dict[str, Any]] = None,
        deep_research_summary: Optional[Dict[str, Any]] = None,
        source_boundary_rules: Optional[Dict[str, Any]] = None,
        coverage_gaps: Optional[List[str]] = None,
        synthesis_rules: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if request_context is not None or proconnect_summary is not None or deep_research_summary is not None:
            return {
                "run_id": run_id or "",
                "request_context": dict(request_context or {}),
                "proconnect_summary": dict(proconnect_summary or {}),
                "deep_research_summary": dict(deep_research_summary or {}),
                "source_boundary_rules": dict(source_boundary_rules or {}),
                "coverage_gaps": [self._normalize_text(item) for item in list(coverage_gaps or []) if self._normalize_text(item)],
                "synthesis_rules": dict(synthesis_rules or {}),
            }

        if trigger is None or research is None:
            raise ValueError("trigger and research are required when using the legacy evidence-pack contract.")

        credentials = dict(credentials or {})
        status_counts = (
            dict(credentials_status_counts)
            if credentials_status_counts is not None
            else self._compute_credentials_status_counts(credentials)
        )

        top_opportunities = []
        for opportunity in list(research.opportunities[:3]):
            response = self._resolve_credentials_response(
                opportunity_id=getattr(opportunity, "opportunity_id", None),
                opportunity_title=getattr(opportunity, "title", ""),
                credentials=credentials,
            )
            top_opportunities.append(
                {
                    "opportunity_id": opportunity.opportunity_id,
                    "title": opportunity.title,
                    "agency": opportunity.agency,
                    "scope": self._compact_text(opportunity.scope, max_chars=220),
                    "estimated_value": opportunity.estimated_value,
                    "timeline": opportunity.timeline,
                    "confidence": opportunity.confidence,
                    "credentials_lookup_status": response.lookup_status if response else "No Match",
                    "failure_reason": response.failure_reason if response else None,
                    "credentials": [
                        {
                            "title": match.title,
                            "value_provided": self._compact_text(match.value_provided, max_chars=140),
                            "why_relevant": self._compact_text(match.why_relevant, max_chars=140),
                            "url": match.url,
                        }
                        for match in list((response.matches if response else []) or [])[:2]
                    ],
                }
            )

        return {
            "run_id": run_id or "",
            "trigger_context": {
                "sector": trigger.sector,
                "signals": list(trigger.signals or []),
                "company_focus": trigger.company_focus,
                "geography": trigger.geography,
                "time_window_days": trigger.time_window_days,
                "user_prompt_context": self._compact_text(trigger.user_prompt_context or "", max_chars=240),
            },
            "account_context": {
                "company_focus": trigger.company_focus or "",
                "research_summary": self._compact_text(research.executive_summary or "", max_chars=280),
                "research_signals": [
                    self._normalize_text(item)
                    for item in list(research.signals_detected or [])[:5]
                    if self._normalize_text(item)
                ],
                "recommended_actions": [
                    self._normalize_text(item)
                    for item in list(research.recommended_actions or [])[:3]
                    if self._normalize_text(item)
                ],
                "opportunity_extraction_status": opportunity_extraction_status,
                "opportunity_extraction_reason": self._normalize_text(opportunity_extraction_reason),
                "opportunities_extracted_count": opportunities_extracted_count,
                "lookups_skipped_reason": self._normalize_text(lookups_skipped_reason),
            },
            "confirmed_signals": [
                {
                    "signal_code": item.signal_code,
                    "signal_label": item.signal_label,
                    "status": item.status,
                    "analysis": self._compact_text(item.analysis, max_chars=220),
                    "evidence_quote": self._compact_text(item.evidence_quote, max_chars=180),
                    "source_title": item.source_title,
                    "source_url": item.source_url,
                }
                for item in list(confirmed_signal_evidence or [])
                if item.status == "Confirmed"
            ][:5],
            "top_opportunities": top_opportunities,
            "phase3_candidates": [
                {
                    "derived_from_signal": item.derived_from_signal,
                    "overview": self._compact_text(item.overview, max_chars=220),
                    "technical_explanation": self._compact_text(item.technical_explanation, max_chars=220),
                    "layman_explanation": self._compact_text(item.layman_explanation, max_chars=220),
                    "relevant_service_lines": list(item.relevant_service_lines or [])[:4],
                    "credentials_summary": self._compact_text(item.credentials_summary, max_chars=180),
                    "recommended_actions": [
                        self._normalize_text(action)
                        for action in list(item.recommended_actions or [])[:3]
                        if self._normalize_text(action)
                    ],
                    "sources": list(item.sources or [])[:3],
                }
                for item in list(phase3_candidates or [])[:3]
            ],
            "preflight_context": dict(preflight_context or {}),
            "allowed_sources": list(allowed_sources or [])[:8],
            "credential_summary": {
                "lookups_executed_count": int(lookups_executed_count or 0),
                "status_counts": status_counts,
            },
            "synthesis_rules": {
                "facts_first": True,
                "no_retrieval": True,
                "no_new_opportunities": True,
                "no_new_credentials": True,
                "no_new_sources": True,
                "allow_light_inference_for_suggested_plays": True,
                "max_signal_summary_bullets": 3,
                "max_opportunity_summary_bullets": 3,
                "max_suggested_plays": 3,
                "no_markdown_headings": True,
                "json_only": True,
            },
        }

    async def synthesize(self, synthesis_input: Dict[str, Any]) -> Optional[AccountBriefSynthesisResult]:
        try:
            if self._runner is not None:
                response = await self._runner(synthesis_input)
            else:
                response = await self._run_with_kernel(synthesis_input)
            return self._coerce_result(response)
        except Exception as exc:
            logger.warning("Account brief synthesis failed: %s", exc)
            return None

    async def _run_with_kernel(self, synthesis_input: Dict[str, Any]) -> str:
        await self._ensure_kernel()
        prompt = self._load_prompt().replace(
            "{{$synthesis_input_json}}",
            json.dumps(synthesis_input, ensure_ascii=True, indent=2),
        )
        history = create_chat_history()
        history.add_user_message(prompt)
        chat = self._kernel.get_service("atlas")
        result = await chat.get_chat_message_content(
            chat_history=history,
            settings=self._exec_settings,
            kernel=self._kernel,
        )
        return str(result)

    def _coerce_result(self, response: Any) -> Optional[AccountBriefSynthesisResult]:
        if response is None:
            return None
        if isinstance(response, AccountBriefSynthesisResult):
            return response
        if (
            hasattr(response, "account_summary")
            and hasattr(response, "signal_summary")
            and hasattr(response, "opportunity_summary")
            and hasattr(response, "takeaway")
        ):
            suggested_plays = [
                self._coerce_suggested_play(item)
                for item in list(getattr(response, "suggested_plays", []) or [])
            ]
            result = AccountBriefSynthesisResult(
                account_summary=self._normalize_text(getattr(response, "account_summary", "")),
                signal_summary=self._coerce_text_list(getattr(response, "signal_summary", [])),
                opportunity_summary=self._coerce_text_list(getattr(response, "opportunity_summary", [])),
                takeaway=self._normalize_text(getattr(response, "takeaway", "")),
                company_overview=self._normalize_text(getattr(response, "company_overview", "")),
                strategic_priorities=self._coerce_text_list(getattr(response, "strategic_priorities", []), max_items=8),
                financial_filing_signals=self._coerce_text_list(getattr(response, "financial_filing_signals", []), max_items=8),
                competitive_context=self._coerce_text_list(getattr(response, "competitive_context", []), max_items=8),
                customer_contract_signals=self._coerce_text_list(getattr(response, "customer_contract_signals", []), max_items=8),
                likely_needs=self._coerce_text_list(getattr(response, "likely_needs", []), max_items=8),
                suggested_plays=[item for item in suggested_plays if item],
                people_to_prioritize=self._coerce_text_list(getattr(response, "people_to_prioritize", []), max_items=8),
                recent_people_moves=self._coerce_text_list(getattr(response, "recent_people_moves", []), max_items=8),
                buying_triggers=self._coerce_text_list(getattr(response, "buying_triggers", []), max_items=8),
                relationship_hooks=self._coerce_text_list(getattr(response, "relationship_hooks", []), max_items=6),
                recommended_asks=self._coerce_text_list(getattr(response, "recommended_asks", []), max_items=6),
                analyst_follow_ups=self._coerce_text_list(getattr(response, "analyst_follow_ups", []), max_items=6),
            )
            if not result.account_summary or not result.signal_summary or not result.opportunity_summary or not result.takeaway:
                return None
            return result
        payload = response
        if isinstance(response, str):
            payload = json.loads(self._extract_json(response))
        if not isinstance(payload, dict):
            return None
        suggested_plays = [
            self._coerce_suggested_play(item)
            for item in list(payload.get("suggested_plays") or [])
        ]
        result = AccountBriefSynthesisResult(
            account_summary=self._normalize_text(payload.get("account_summary")),
            signal_summary=self._coerce_text_list(payload.get("signal_summary") or []),
            opportunity_summary=self._coerce_text_list(payload.get("opportunity_summary") or []),
            takeaway=self._normalize_text(payload.get("takeaway")),
            company_overview=self._normalize_text(payload.get("company_overview")),
            strategic_priorities=self._coerce_text_list(payload.get("strategic_priorities") or [], max_items=8),
            financial_filing_signals=self._coerce_text_list(payload.get("financial_filing_signals") or [], max_items=8),
            competitive_context=self._coerce_text_list(payload.get("competitive_context") or [], max_items=8),
            customer_contract_signals=self._coerce_text_list(payload.get("customer_contract_signals") or [], max_items=8),
            likely_needs=self._coerce_text_list(payload.get("likely_needs") or [], max_items=8),
            suggested_plays=[item for item in suggested_plays if item],
            people_to_prioritize=self._coerce_text_list(payload.get("people_to_prioritize") or [], max_items=8),
            recent_people_moves=self._coerce_text_list(payload.get("recent_people_moves") or [], max_items=8),
            buying_triggers=self._coerce_text_list(payload.get("buying_triggers") or [], max_items=8),
            relationship_hooks=self._coerce_text_list(payload.get("relationship_hooks") or [], max_items=6),
            recommended_asks=self._coerce_text_list(payload.get("recommended_asks") or [], max_items=6),
            analyst_follow_ups=self._coerce_text_list(payload.get("analyst_follow_ups") or [], max_items=6),
        )
        if not result.account_summary or not result.signal_summary or not result.opportunity_summary or not result.takeaway:
            return None
        return result

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            if PROMPT_PATH.exists():
                self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
            else:
                self._prompt_template = self._fallback_prompt()
        return self._prompt_template

    @staticmethod
    def _resolve_credentials_response(
        *,
        opportunity_id: Optional[str],
        opportunity_title: str,
        credentials: Dict[str, CredentialsResponse],
    ) -> Optional[CredentialsResponse]:
        lookup_keys = [str(opportunity_id or "").strip(), str(opportunity_title or "").strip()]
        for key in lookup_keys:
            if key and key in credentials:
                return credentials[key]
        for response in credentials.values():
            if opportunity_id and response.opportunity_id == opportunity_id:
                return response
            if opportunity_title and response.opportunity_title == opportunity_title:
                return response

        normalized_targets = [
            AccountBriefSynthesizer._normalize_lookup_key(item)
            for item in lookup_keys
            if item
        ]
        normalized_targets = [item for item in normalized_targets if item]
        if not normalized_targets:
            return None

        for key, response in credentials.items():
            candidates = [
                AccountBriefSynthesizer._normalize_lookup_key(key),
                AccountBriefSynthesizer._normalize_lookup_key(response.opportunity_title),
                AccountBriefSynthesizer._normalize_lookup_key(response.opportunity_id or ""),
            ]
            if any(
                candidate and (
                    candidate in normalized_target or normalized_target in candidate
                )
                for normalized_target in normalized_targets
                for candidate in candidates
            ):
                return response
        return None

    @staticmethod
    def _compute_credentials_status_counts(
        credentials: Dict[str, CredentialsResponse]
    ) -> Dict[str, int]:
        counts = {"Matched": 0, "No Match": 0, "Lookup Failed": 0}
        for response in credentials.values():
            status = response.lookup_status if response.lookup_status in counts else "Lookup Failed"
            counts[status] += 1
        return counts

    @staticmethod
    def _extract_json(text: str) -> str:
        cleaned = str(text or "").strip()
        if "```" in cleaned:
            lines = cleaned.splitlines()
            block: List[str] = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or (not in_block and "{" in line):
                    block.append(line)
            cleaned = "\n".join(block).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            return cleaned[start:end]
        return cleaned

    @staticmethod
    def _coerce_text_list(items: Any, *, max_items: int = 3) -> List[str]:
        if isinstance(items, str):
            text = AccountBriefSynthesizer._normalize_text(items)
            return [text] if text else []
        output: List[str] = []
        for item in list(items or [])[:max_items]:
            text = AccountBriefSynthesizer._normalize_text(item)
            if text:
                output.append(text)
        return output

    @staticmethod
    def _coerce_suggested_play(item: Any) -> Optional[SynthesizedSuggestedPlay]:
        if isinstance(item, SynthesizedSuggestedPlay):
            return item
        if not isinstance(item, dict):
            return None
        play = AccountBriefSynthesizer._normalize_text(item.get("play"))
        why_now = AccountBriefSynthesizer._normalize_text(item.get("why_now"))
        if not play or not why_now:
            return None
        return SynthesizedSuggestedPlay(play=play, why_now=why_now)

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    @staticmethod
    def _normalize_lookup_key(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
        return re.sub(r"\s+", " ", normalized)

    @staticmethod
    def _compact_text(value: str, max_chars: int = 240) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = text.replace("\\n", "\n")
        text = re.sub(r"(?is)^final report:\s*", "", text)
        text = re.sub(r"(?is)^executive summary:\s*", "", text)
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.split(r"(?i)\bSources?\s*:", text, maxsplit=1)[0].strip()
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"\s+#{1,6}\s+", " ", text)
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."

    @staticmethod
    def _fallback_prompt() -> str:
        return (
            "You are generating a compact analyst account brief.\n"
            "Use only the facts in the provided JSON evidence pack.\n"
            "Suggested plays may infer a next best move from the stated evidence, but must not introduce new facts.\n"
            "Return only valid JSON with keys account_summary, signal_summary, opportunity_summary, company_overview, strategic_priorities, financial_filing_signals, competitive_context, customer_contract_signals, likely_needs, people_to_prioritize, recent_people_moves, buying_triggers, relationship_hooks, suggested_plays, recommended_asks, analyst_follow_ups, takeaway.\n"
            "Keep it concise, facts-first, and avoid citations or markdown.\n\n"
            "Evidence pack:\n{{$synthesis_input_json}}\n"
        )
