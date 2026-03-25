"""
Bounded synthesis for the compact People Movement Brief cover.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from models.bd_schemas import SignalEvidence
from models.movement_schemas import MovementBrief, MovementBriefRequest
from models.transition_schemas import TransitionPreflight
from services.semantic_kernel_compat import create_chat_history


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_Movement_Brief_Synthesis_prompt.txt"
SynthesisRunner = Callable[[Dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class SynthesizedActionNarrative:
    person_name: str
    likely_play: str
    why_now: str


@dataclass(frozen=True)
class MovementBriefSynthesisResult:
    move_summary: str
    signal_summary: List[str]
    takeaway: str
    action_narratives: List[SynthesizedActionNarrative] = field(default_factory=list)


class MovementBriefSynthesizer:
    """Generate concise cover narrative without owning deterministic facts."""

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
        run_id: Optional[str],
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
        brief: MovementBrief,
        signal_evidence: List[SignalEvidence],
        deep_research_summary: str,
    ) -> Dict[str, Any]:
        confirmed_signals = [
            {
                "signal_code": item.signal_code,
                "signal_label": item.signal_label,
                "status": item.status,
                "analysis": item.analysis,
                "evidence_quote": item.evidence_quote,
                "source_title": item.source_title,
            }
            for item in signal_evidence
            if item.status == "Confirmed"
        ][:6]

        top_rows = []
        for row in list(brief.movement_rows[:10]):
            leverage = row.leverage
            proof = row.credentials_proof
            top_rows.append(
                {
                    "person_name": row.person_name,
                    "category": row.category,
                    "previous_role": row.previous_role,
                    "new_role": row.new_role,
                    "movement_type": row.movement_type,
                    "evidence_quote": row.evidence.evidence_quote,
                    "known": bool(leverage.known) if leverage else False,
                    "worked_with": bool(leverage.worked_with) if leverage else False,
                    "project_count": int(leverage.project_count) if leverage else 0,
                    "win_count": int(leverage.win_count) if leverage else 0,
                    "relationship_owner": leverage.relationship_owner if leverage else None,
                    "credential_proof_summary": proof.summary if proof else "",
                }
            )

        selected_actions = [
            {
                "person_name": action.person_name,
                "action_posture": action.action_posture,
                "likely_play_raw": action.likely_play,
                "why_now_raw": action.why_now,
                "relationship_owner": action.relationship_owner,
            }
            for action in list(brief.where_to_act[:3])
        ]

        return {
            "run_id": run_id or "",
            "move_context": {
                "person_name": request.person_name,
                "from_company": request.from_company,
                "to_company": request.to_company,
                "new_role": request.new_role,
                "lookback_days": request.lookback_days,
                "synthetic_scenario": bool(request.synthetic_scenario),
            },
            "account_context": {
                "destination_company": preflight.to_account.company_name or request.to_company,
                "industry": preflight.inferred_industry,
                "warm_intro_path_available": preflight.quick_indicators.warm_intro_path_available,
                "source_worked_before": preflight.quick_indicators.source_worked_before,
                "destination_worked_before": preflight.quick_indicators.destination_worked_before,
                "person_match_status": preflight.person_resolution.match_status,
                "account_pressure_summary": self._compact_text(deep_research_summary),
            },
            "confirmed_signals": confirmed_signals,
            "top_movement_rows": top_rows,
            "selected_actions": selected_actions,
            "destination_opportunity_context": [
                {
                    "title": item.title,
                    "confidence": item.confidence,
                    "rationale": item.rationale,
                }
                for item in list(preflight.opportunity_hypotheses[:3])
            ],
            "credential_summary": {
                "matched_count": sum(
                    1
                    for row in brief.movement_rows
                    if row.credentials_proof and row.credentials_proof.lookup_status == "Matched"
                ),
                "visible_row_count": len(brief.movement_rows),
                "selected_action_count": len(brief.where_to_act),
            },
            "synthesis_rules": {
                "facts_first": True,
                "no_new_movers": True,
                "no_new_actions": True,
                "no_markdown_headings": True,
                "no_citation_dump": True,
                "max_signal_summary_bullets": 3,
            },
        }

    async def synthesize(self, synthesis_input: Dict[str, Any]) -> Optional[MovementBriefSynthesisResult]:
        try:
            if self._runner is not None:
                response = await self._runner(synthesis_input)
            else:
                response = await self._run_with_kernel(synthesis_input)
            return self._coerce_result(response)
        except Exception as exc:
            logger.warning("Movement brief synthesis failed: %s", exc)
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

    def _coerce_result(self, response: Any) -> Optional[MovementBriefSynthesisResult]:
        if response is None:
            return None
        if isinstance(response, MovementBriefSynthesisResult):
            return response
        if hasattr(response, "move_summary") and hasattr(response, "signal_summary") and hasattr(response, "takeaway"):
            action_narratives = [
                self._coerce_action_narrative(item)
                for item in list(getattr(response, "action_narratives", []) or [])
            ]
            return MovementBriefSynthesisResult(
                move_summary=self._normalize_text(getattr(response, "move_summary", "")),
                signal_summary=self._coerce_signal_summary(getattr(response, "signal_summary", [])),
                takeaway=self._normalize_text(getattr(response, "takeaway", "")),
                action_narratives=[item for item in action_narratives if item],
            )
        payload = response
        if isinstance(response, str):
            payload = json.loads(self._extract_json(response))
        if not isinstance(payload, dict):
            return None
        action_narratives = [
            self._coerce_action_narrative(item)
            for item in list(payload.get("action_narratives") or [])
        ]
        result = MovementBriefSynthesisResult(
            move_summary=self._normalize_text(payload.get("move_summary")),
            signal_summary=self._coerce_signal_summary(payload.get("signal_summary") or []),
            takeaway=self._normalize_text(payload.get("takeaway")),
            action_narratives=[item for item in action_narratives if item],
        )
        if not result.move_summary or not result.signal_summary or not result.takeaway:
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
    def _coerce_signal_summary(items: List[Any]) -> List[str]:
        if isinstance(items, str):
            text = MovementBriefSynthesizer._normalize_text(items)
            return [text] if text else []
        output: List[str] = []
        for item in list(items or [])[:3]:
            text = MovementBriefSynthesizer._normalize_text(item)
            if text:
                output.append(text)
        return output

    @staticmethod
    def _coerce_action_narrative(item: Any) -> Optional[SynthesizedActionNarrative]:
        if isinstance(item, SynthesizedActionNarrative):
            return item
        if not isinstance(item, dict):
            return None
        person_name = MovementBriefSynthesizer._normalize_text(item.get("person_name"))
        likely_play = MovementBriefSynthesizer._normalize_text(item.get("likely_play"))
        why_now = MovementBriefSynthesizer._normalize_text(item.get("why_now"))
        if not person_name or not likely_play or not why_now:
            return None
        return SynthesizedActionNarrative(
            person_name=person_name,
            likely_play=likely_play,
            why_now=why_now,
        )

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

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
            "You are generating a compact people-movement brief cover.\n"
            "Use only the facts in the provided JSON evidence pack.\n"
            "Return only valid JSON with keys move_summary, signal_summary, takeaway, action_narratives.\n"
            "Keep it concise, facts-first, and avoid citations or markdown.\n\n"
            "Evidence pack:\n{{$synthesis_input_json}}\n"
        )
