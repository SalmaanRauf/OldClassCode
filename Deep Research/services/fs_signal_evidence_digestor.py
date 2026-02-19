"""
ATLAS-powered digestor for financial-services signal evidence extraction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Tuple

from models.bd_schemas import BDTrigger, SignalEvidence
from services.signal_registry_service import get_signal_registry_service
from services.source_guardrails import SourceGuardrails

PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_FS_Signal_Evidence_Digest_prompt.txt"


class FSSignalEvidenceDigestor:
    """Normalizes financial-services evidence records for requested signals."""

    def __init__(self, kernel=None, exec_settings=None, source_guardrails: Optional[SourceGuardrails] = None):
        self._kernel = kernel
        self._exec_settings = exec_settings
        self._prompt_template: Optional[str] = None
        self._signal_registry = get_signal_registry_service()
        self._source_guardrails = source_guardrails or SourceGuardrails()

    async def _ensure_kernel(self):
        if self._kernel is None:
            from config.kernel_setup import get_kernel_async
            self._kernel, self._exec_settings = await get_kernel_async()

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            if PROMPT_PATH.exists():
                self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
            else:
                self._prompt_template = self._fallback_prompt()
        return self._prompt_template

    async def digest(
        self,
        trigger: BDTrigger,
        deep_research_markdown: str,
        requested_signal_codes: List[str],
        source_urls: Optional[List[str]] = None,
    ) -> Tuple[List[SignalEvidence], Dict[str, Any], List[str]]:
        start = perf_counter()
        diagnostics: Dict[str, Any] = {
            "invoked": True,
            "status": "Failed",
            "reason": None,
            "duration_ms": 0.0,
            "raw_response_text": "",
            "parse_outcome": "",
            "signals_returned": 0,
            "allowed_source_count": 0,
        }

        if not deep_research_markdown or not deep_research_markdown.strip():
            diagnostics["status"] = "Skipped"
            diagnostics["reason"] = "Deep Research markdown was empty."
            diagnostics["parse_outcome"] = "empty_markdown"
            return [], diagnostics, []

        requested = [code for code in requested_signal_codes if code]
        if not requested:
            diagnostics["status"] = "Skipped"
            diagnostics["reason"] = "No requested signal codes were provided."
            diagnostics["parse_outcome"] = "no_requested_signals"
            return [], diagnostics, []

        # Keep full unique source set for synthesis context/display; domain caps are enforced
        # separately when promoting evidence to Confirmed status.
        raw_sources = source_urls or self._extract_urls(deep_research_markdown)
        available_sources: List[str] = []
        seen_sources = set()
        for item in raw_sources:
            normalized = str(item or "").strip()
            if not normalized or normalized in seen_sources:
                continue
            seen_sources.add(normalized)
            available_sources.append(normalized)
        diagnostics["allowed_source_count"] = len(available_sources)

        try:
            await self._ensure_kernel()
            prompt = self._render_prompt(
                trigger=trigger,
                deep_research_markdown=deep_research_markdown,
                requested_signal_codes=requested,
                allowed_sources=available_sources,
            )

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
            parsed = self._coerce_signal_evidence(
                payload.get("signal_evidence", []),
                requested_signal_codes=requested,
            )

            # Ensure deterministic placeholders for any missing requested signal.
            existing = {item.signal_code for item in parsed}
            for signal_code in requested:
                if signal_code not in existing:
                    parsed.append(
                        SignalEvidence(
                            signal_code=signal_code,
                            signal_label=self._signal_registry.get_signal_label(signal_code),
                            status="Insufficient",
                            evidence_quote="",
                            source_url="",
                            source_title=None,
                            analysis="No explicit evidence extracted for this signal.",
                        )
                    )

            enforced = self._source_guardrails.enforce_on_signal_evidence(
                parsed,
                available_sources=set(available_sources),
            )

            diagnostics["signals_returned"] = len(enforced)
            diagnostics["status"] = "Succeeded"
            diagnostics["parse_outcome"] = "json_parsed_with_signal_evidence"
            return enforced, diagnostics, available_sources

        except json.JSONDecodeError as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "Could not parse FS signal digest response as JSON."
            diagnostics["parse_outcome"] = "json_parse_error"
            diagnostics["error_type"] = "JSONDecodeError"
            diagnostics["error_message"] = str(exc)
            return [], diagnostics, available_sources
        except Exception as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "FS signal evidence digest call failed."
            diagnostics["parse_outcome"] = "digest_failed"
            diagnostics["error_type"] = type(exc).__name__
            diagnostics["error_message"] = str(exc)
            return [], diagnostics, available_sources
        finally:
            diagnostics["duration_ms"] = (perf_counter() - start) * 1000

    def _render_prompt(
        self,
        trigger: BDTrigger,
        deep_research_markdown: str,
        requested_signal_codes: List[str],
        allowed_sources: List[str],
    ) -> str:
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.geography:
            trigger_parts.append(f"Geography: {trigger.geography}")
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")
        if trigger.user_prompt_context:
            trigger_parts.append(f"User Prompt: {trigger.user_prompt_context}")

        prompt = self._load_prompt()
        prompt = prompt.replace("{{$trigger_summary}}", "; ".join(trigger_parts))
        prompt = prompt.replace("{{$requested_signal_codes_json}}", json.dumps(requested_signal_codes, indent=2))
        prompt = prompt.replace("{{$allowed_sources_json}}", json.dumps(allowed_sources, indent=2))
        prompt = prompt.replace("{{$current_date_iso}}", datetime.now().date().isoformat())
        return prompt.replace("{{$deep_research_markdown}}", deep_research_markdown)

    def _coerce_signal_evidence(
        self,
        raw_items: Any,
        requested_signal_codes: List[str],
    ) -> List[SignalEvidence]:
        if not isinstance(raw_items, list):
            return []

        requested_set: Set[str] = set(requested_signal_codes)
        normalized: List[SignalEvidence] = []
        seen = set()

        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            signal_code = str(entry.get("signal_code", "")).strip()
            if signal_code not in requested_set or signal_code in seen:
                continue

            raw_status = str(entry.get("status", "Insufficient")).strip().title()
            if raw_status not in {"Confirmed", "Insufficient", "Rejected"}:
                raw_status = "Insufficient"

            evidence_quote = str(entry.get("evidence_quote", "")).strip()
            if len(evidence_quote) > 220:
                evidence_quote = evidence_quote[:220].rstrip()

            signal_label = str(entry.get("signal_label", "")).strip() or self._signal_registry.get_signal_label(signal_code)
            source_url = str(entry.get("source_url", "")).strip()
            source_title_raw = entry.get("source_title")
            source_title = str(source_title_raw).strip() if source_title_raw is not None else None
            analysis = str(entry.get("analysis", "")).strip()

            normalized.append(
                SignalEvidence(
                    signal_code=signal_code,
                    signal_label=signal_label,
                    status=raw_status,  # type: ignore[arg-type]
                    evidence_quote=evidence_quote,
                    source_url=source_url,
                    source_title=source_title,
                    analysis=analysis,
                )
            )
            seen.add(signal_code)

        return normalized

    def _extract_urls(self, text: str) -> List[str]:
        if not text:
            return []
        raw_urls = re.findall(r"https?://[^\s\]\)>,]+", text)
        normalized: List[str] = []
        seen = set()
        for url in raw_urls:
            cleaned = url.strip().rstrip(".,;)")
            if cleaned and cleaned not in seen:
                normalized.append(cleaned)
                seen.add(cleaned)
        return normalized

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
            "Return JSON signal evidence records.\n"
            "Trigger: {{$trigger_summary}}\n"
            "Requested: {{$requested_signal_codes_json}}\n"
            "Allowed URLs: {{$allowed_sources_json}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
