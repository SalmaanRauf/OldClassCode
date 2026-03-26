"""
ATLAS-powered digestor for financial-services movement extraction.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

from models.bd_schemas import BDTrigger
from models.movement_schemas import MovementEvidence, MovementRecord
from services.semantic_kernel_compat import create_chat_history


PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_FS_Movement_Digest_prompt.txt"


class FSMovementDigestor:
    """Normalizes executive and buyer movement rows for movement-led briefs."""

    PASS_PLAN = (
        (
            "general",
            "Capture all confirmed executive and buyer movements tied to the target company.",
        ),
        (
            "executive",
            "Focus on executive, board, CEO, president, co-president, C-suite, chair, and leadership transitions. Prefer EXEC rows and do not omit confirmed leadership moves.",
        ),
        (
            "buyer",
            "Focus on buyer-center moves in audit, finance, risk, compliance, legal, data, security, technology, controls, and operations. Prefer BUYER rows and do not omit confirmed buyer-side changes.",
        ),
    )

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
            chat = self._kernel.get_service("atlas")
            combined_rows: List[MovementRecord] = []
            raw_responses: List[str] = []
            pass_results: List[Dict[str, Any]] = []

            for focus, focus_instruction in self.PASS_PLAN:
                prompt = self._render_prompt(
                    trigger,
                    deep_research_markdown,
                    max_rows=max_rows,
                    focus_instruction=focus_instruction,
                )
                history = create_chat_history()
                history.add_user_message(prompt)
                try:
                    result = await chat.get_chat_message_content(
                        chat_history=history,
                        settings=self._exec_settings,
                        kernel=self._kernel,
                    )
                    raw_response = str(result)
                    raw_responses.append(raw_response)
                    payload = json.loads(self._extract_json(raw_response))
                    rows = self._coerce_movements(
                        payload.get("movement_records", []),
                        trigger=trigger,
                        max_rows=max_rows,
                        target_company_aliases=target_company_aliases,
                    )
                    combined_rows.extend(rows)
                    pass_results.append({"focus": focus, "count": len(rows)})
                except Exception as exc:
                    pass_results.append(
                        {
                            "focus": focus,
                            "count": 0,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )

            diagnostics["raw_response_text"] = "\n\n".join(raw_responses).strip()
            diagnostics["pass_results"] = pass_results
            movements = self._dedupe_rows(combined_rows, max_rows=max_rows)
            diagnostics["movements_returned"] = len(movements)
            diagnostics["status"] = "Succeeded" if movements else "Failed"
            diagnostics["parse_outcome"] = (
                "json_parsed_multi_pass_movement_records"
                if movements
                else "multi_pass_no_movement_records"
            )
            if not movements:
                diagnostics["reason"] = "Movement digest passes returned no valid movement rows."
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

    def _render_prompt(
        self,
        trigger: BDTrigger,
        markdown: str,
        max_rows: int,
        *,
        focus_instruction: str = "",
    ) -> str:
        template = self._load_prompt()
        trigger_parts = [f"Sector: {trigger.sector}"]
        if trigger.company_focus:
            trigger_parts.append(f"Company: {trigger.company_focus}")
        if trigger.time_window_days:
            trigger_parts.append(f"Lookback: {int(trigger.time_window_days)} days")
        if trigger.geography:
            trigger_parts.append(f"Geography: {trigger.geography}")
        if trigger.signals:
            trigger_parts.append(f"Signals: {', '.join(trigger.signals)}")
        if trigger.user_prompt_context:
            trigger_parts.append(f"User Prompt: {trigger.user_prompt_context}")

        prompt = template.replace("{{$trigger_summary}}", "; ".join(trigger_parts))
        prompt = prompt.replace("{{$current_date_iso}}", datetime.now().date().isoformat())
        prompt = prompt.replace("{{$max_rows}}", str(max_rows))
        prompt = prompt.replace("{{$deep_research_markdown}}", markdown)
        if focus_instruction:
            prompt = f"{prompt}\n\nAdditional extraction focus:\n- {focus_instruction}\n"
        return prompt

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
        deduped_rows: Dict[Tuple[str, str, str, str], Tuple[int, int, MovementRecord]] = {}
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
            category = self._normalize_category(entry.get("category"))
            company_context = str(entry.get("company_context") or "").strip()
            effective_date = self._normalize_effective_date(entry.get("effective_date"))
            evidence_quote = str(entry.get("evidence_quote") or "").strip()
            source_url = str(entry.get("source_url") or "").strip()

            if not all([person_name, target_company, movement_type, category, company_context]):
                continue
            if not (previous_role or new_role):
                continue
            if category not in {"EXEC", "BUYER"}:
                continue
            if not evidence_quote or not source_url:
                continue
            if effective_date and not self._date_within_lookback(effective_date, trigger.time_window_days):
                continue

            row = MovementRecord(
                person_name=person_name,
                target_company=target_company,
                previous_role=previous_role,
                new_role=new_role,
                movement_type=movement_type,
                category=category,
                company_context=company_context,
                effective_date=effective_date,
                evidence=MovementEvidence(
                    evidence_quote=evidence_quote,
                    source_url=source_url,
                    source_title=entry.get("source_title"),
                    source_marker=entry.get("source_marker"),
                    corroborated=bool(entry.get("corroborated", False)),
                    confidence_label=entry.get("confidence_label"),
                ),
            )
            dedupe_key = self._movement_dedupe_key(row)
            candidate_score = self._row_information_score(row)
            existing = deduped_rows.get(dedupe_key)
            if existing is None:
                deduped_rows[dedupe_key] = (len(deduped_rows), candidate_score, row)
                continue
            original_index, existing_score, existing_row = existing
            if candidate_score > existing_score:
                deduped_rows[dedupe_key] = (original_index, candidate_score, row)
            else:
                deduped_rows[dedupe_key] = (original_index, existing_score, existing_row)

        rows = [
            item[2]
            for item in sorted(deduped_rows.values(), key=lambda payload: payload[0])
        ]
        return rows[:max_rows]

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

    def _dedupe_rows(self, rows: List[MovementRecord], *, max_rows: int) -> List[MovementRecord]:
        deduped_rows: Dict[Tuple[str, str, str, str], Tuple[int, int, MovementRecord]] = {}
        for row in rows:
            dedupe_key = self._movement_dedupe_key(row)
            candidate_score = self._row_information_score(row)
            existing = deduped_rows.get(dedupe_key)
            if existing is None:
                deduped_rows[dedupe_key] = (len(deduped_rows), candidate_score, row)
                continue
            original_index, existing_score, existing_row = existing
            if candidate_score > existing_score:
                deduped_rows[dedupe_key] = (original_index, candidate_score, row)
            else:
                deduped_rows[dedupe_key] = (original_index, existing_score, existing_row)

        return [
            item[2]
            for item in sorted(deduped_rows.values(), key=lambda payload: payload[0])
        ][:max_rows]

    @staticmethod
    def _normalize_company(value: Optional[str]) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        aliases = re.findall(r"\(([^)]*)\)", text)
        for alias in aliases:
            alias_text = alias.strip()
            if alias_text:
                text = alias_text
                break
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        normalized = re.sub(r"[\s,.-]+", " ", text.lower())
        return normalized.strip()

    @staticmethod
    def _normalize_category(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"exec", "executive", "executive movement"}:
            return "EXEC"
        if normalized in {"buyer", "buying", "buying_center", "buying center"}:
            return "BUYER"
        return str(value or "").strip().upper()

    @classmethod
    def _movement_dedupe_key(cls, row: MovementRecord) -> Tuple[str, str, str, str]:
        return (
            cls._normalize_person_identity(row.person_name),
            cls._normalize_company(row.category),
            cls._normalize_company(row.target_company),
            cls._movement_anchor(row),
        )

    @staticmethod
    def _row_information_score(row: MovementRecord) -> int:
        score = 0
        score += 2 if row.previous_role else 0
        score += 2 if row.new_role else 0
        score += 1 if row.evidence.source_title else 0
        score += 1 if row.evidence.source_marker else 0
        score += 1 if row.evidence.corroborated else 0
        score += 1 if row.effective_date else 0
        return score

    @classmethod
    def _movement_anchor(cls, row: MovementRecord) -> str:
        if row.effective_date:
            return f"date:{row.effective_date}"

        movement_type = cls._normalize_role_identity(row.movement_type)
        previous_role = cls._normalize_role_identity(row.previous_role)
        new_role = cls._normalize_role_identity(row.new_role)
        evidence_quote = cls._normalize_role_identity(row.evidence.evidence_quote)
        departure_markers = (
            "departure",
            "departed",
            "stepped down",
            "stepped",
            "fired",
            "ousted",
            "termination",
            "terminated",
            "replaced",
            "role elimination",
            "eliminated",
        )
        if any(marker in movement_type for marker in departure_markers) or any(
            marker in new_role for marker in departure_markers
        ):
            return f"departure:{previous_role or movement_type or evidence_quote[:96]}"
        return f"move:{new_role or previous_role or movement_type or evidence_quote[:96]}"

    @staticmethod
    def _normalize_role_identity(value: Optional[str]) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = text.lower()
        replacements = {
            "chief executive officer": "ceo",
            "chief operating officer": "coo",
            "chief financial officer": "cfo",
            "chief information officer": "cio",
            "chief audit executive": "cae",
            "general counsel": "general counsel",
            "chief legal officer": "general counsel",
            "president and chief executive officer": "ceo president",
            "chief executive officer and president": "ceo president",
            "co president": "copresident",
            "co-president": "copresident",
            "chairman of the board": "chairman board",
            "vice chairman of the board": "vice chairman board",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"[^\w\s]", " ", text)
        tokens = [
            token
            for token in re.split(r"\s+", text)
            if token
            and token not in {"and", "of", "the", "a", "an", "also", "retaining", "duties", "role", "n", "na"}
        ]
        return " ".join(sorted(dict.fromkeys(tokens)))

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

    @staticmethod
    def _normalize_person_identity(value: Optional[str]) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        inner_aliases = re.findall(r"\(([^)]*)\)", text)
        if inner_aliases:
            for alias in inner_aliases:
                alias_text = alias.strip()
                if alias_text and len(alias_text.split()) >= 2:
                    text = alias_text
                    break
        text = re.sub(r"\([^)]*\)", "", text).strip() if "(" in text and ")" in text else text
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^\w\s]", " ", text.lower())
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_effective_date(value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%Y-%m", "%B %Y", "%b %Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                if fmt in {"%Y-%m", "%B %Y", "%b %Y"}:
                    parsed = parsed.replace(day=1)
                return parsed.date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _date_within_lookback(effective_date: str, lookback_days: int) -> bool:
        try:
            movement_date = date.fromisoformat(effective_date)
        except ValueError:
            return True
        return (date.today() - movement_date).days <= int(lookback_days or 0)

    def _fallback_prompt(self) -> str:
        return (
            "Return JSON with movement_records from this markdown.\n"
            "Trigger: {{$trigger_summary}}\n"
            "Current date: {{$current_date_iso}}\n"
            "Max rows: {{$max_rows}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
