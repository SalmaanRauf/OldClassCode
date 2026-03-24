"""
ATLAS-powered digestor for financial-services movement extraction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from models.bd_schemas import BDTrigger
from models.movement_schemas import MovementEvidence, MovementRecord
from services.semantic_kernel_compat import create_chat_history


PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_FS_Movement_Digest_prompt.txt"


class FSMovementDigestor:
    """Normalizes executive and buyer movement rows for movement-led briefs."""

    def __init__(self, kernel=None, exec_settings=None):
        self._kernel = kernel
        self._exec_settings = exec_settings
        self._prompt_template: Optional[str] = None

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
        max_rows: int = 25,
        target_company_aliases: Optional[List[str]] = None,
    ) -> Tuple[List[MovementRecord], Dict[str, Any]]:
        start = perf_counter()
        diagnostics: Dict[str, Any] = {
            "invoked": True,
            "status": "Failed",
            "reason": None,
            "duration_ms": 0.0,
            "raw_response_text": "",
            "parse_outcome": "",
            "movements_returned": 0,
        }

        if not deep_research_markdown or not deep_research_markdown.strip():
            diagnostics["status"] = "Skipped"
            diagnostics["reason"] = "Deep Research markdown was empty."
            diagnostics["parse_outcome"] = "empty_markdown"
            return [], diagnostics

        try:
            await self._ensure_kernel()
            prompt = self._render_prompt(trigger, deep_research_markdown, max_rows=max_rows)

            history = create_chat_history()
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
            movements = self._coerce_movements(
                payload.get("movement_records", []),
                trigger=trigger,
                max_rows=max_rows,
                target_company_aliases=target_company_aliases,
            )
            diagnostics["movements_returned"] = len(movements)
            diagnostics["status"] = "Succeeded"
            diagnostics["parse_outcome"] = "json_parsed_with_movement_records"
            return movements, diagnostics

        except json.JSONDecodeError as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "Could not parse movement digest response as JSON."
            diagnostics["parse_outcome"] = "json_parse_error"
            diagnostics["error_type"] = "JSONDecodeError"
            diagnostics["error_message"] = str(exc)
            return [], diagnostics
        except Exception as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "Movement digest call failed."
            diagnostics["parse_outcome"] = "digest_failed"
            diagnostics["error_type"] = type(exc).__name__
            diagnostics["error_message"] = str(exc)
            return [], diagnostics
        finally:
            diagnostics["duration_ms"] = (perf_counter() - start) * 1000

    def _render_prompt(self, trigger: BDTrigger, markdown: str, max_rows: int) -> str:
        template = self._load_prompt()
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.geography:
            trigger_parts.append(f"Geography: {trigger.geography}")
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")
        if trigger.user_prompt_context:
            trigger_parts.append(f"User Prompt: {trigger.user_prompt_context}")

        prompt = template.replace("{{$trigger_summary}}", "; ".join(trigger_parts))
        prompt = prompt.replace("{{$current_date_iso}}", datetime.now().date().isoformat())
        prompt = prompt.replace("{{$max_rows}}", str(max_rows))
        return prompt.replace("{{$deep_research_markdown}}", markdown)

    def _coerce_movements(
        self,
        raw_items: Any,
        *,
        trigger: BDTrigger,
        max_rows: int,
        target_company_aliases: Optional[List[str]] = None,
    ) -> List[MovementRecord]:
        if not isinstance(raw_items, list):
            return []

        company_aliases = self._company_aliases(target_company_aliases or [trigger.company_focus])
        rows: List[MovementRecord] = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue

            target_company = str(entry.get("target_company") or "").strip()
            normalized_target_aliases = self._company_aliases([target_company])
            if company_aliases and company_aliases.isdisjoint(normalized_target_aliases):
                continue

            person_name = str(entry.get("person_name") or "").strip()
            previous_role = str(entry.get("previous_role") or "").strip()
            new_role = str(entry.get("new_role") or "").strip()
            movement_type = str(entry.get("movement_type") or "").strip()
            category = str(entry.get("category") or "").strip()
            company_context = str(entry.get("company_context") or "").strip()
            evidence_quote = str(entry.get("evidence_quote") or "").strip()
            source_url = str(entry.get("source_url") or "").strip()

            if not all([person_name, target_company, previous_role, new_role, movement_type, category, company_context]):
                continue
            if category not in {"EXEC", "BUYER"}:
                continue
            if not evidence_quote or not source_url:
                continue

            rows.append(
                MovementRecord(
                    person_name=person_name,
                    target_company=target_company,
                    previous_role=previous_role,
                    new_role=new_role,
                    movement_type=movement_type,
                    category=category,
                    company_context=company_context,
                    evidence=MovementEvidence(
                        evidence_quote=evidence_quote,
                        source_url=source_url,
                        source_title=entry.get("source_title"),
                        source_marker=entry.get("source_marker"),
                        corroborated=bool(entry.get("corroborated", False)),
                        confidence_label=entry.get("confidence_label"),
                    ),
                )
            )
            if len(rows) >= max_rows:
                break
        return rows

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

    @staticmethod
    def _normalize_company(value: Optional[str]) -> str:
        normalized = re.sub(r"[\s,.-]+", " ", (value or "").strip().lower())
        return normalized.strip()

    @classmethod
    def _company_aliases(cls, values: List[Optional[str]]) -> set[str]:
        aliases: set[str] = set()
        corporate_suffixes = (
            " corporation",
            " corp",
            " incorporated",
            " inc",
            " company",
            " co",
            " ltd",
            " llc",
            " plc",
            " holdings",
            " group",
        )
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            variants = {
                text,
                re.sub(r"\([^)]*\)", "", text).strip(),
            }
            variants.update(re.findall(r"\(([^)]*)\)", text))
            for variant in variants:
                normalized = cls._normalize_company(variant)
                if normalized:
                    aliases.add(normalized)
                    for suffix in corporate_suffixes:
                        if normalized.endswith(suffix):
                            stripped = normalized[: -len(suffix)].strip()
                            if stripped:
                                aliases.add(stripped)
        return aliases

    def _fallback_prompt(self) -> str:
        return (
            "Return JSON with movement_records from this markdown.\n"
            "Trigger: {{$trigger_summary}}\n"
            "Current date: {{$current_date_iso}}\n"
            "Max rows: {{$max_rows}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
