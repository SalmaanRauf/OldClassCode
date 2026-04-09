"""
ATLAS-powered digestor for financial-services movement extraction.
"""
from __future__ import annotations

import json
import re
import unicodedata
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Tuple

from models.bd_schemas import BDTrigger
from models.movement_schemas import MovementEvidence, MovementRecord
from services.semantic_kernel_compat import create_chat_history


PROMPT_PATH = Path(__file__).parent.parent / "sk_functions" / "BD_FS_Movement_Digest_prompt.txt"


class FSMovementDigestor:
    """Normalizes executive and buyer movement rows for movement-led briefs."""

    _NON_PERSON_NAME_TERMS = {
        "finance",
        "financial",
        "mortgage",
        "capital",
        "coinbase",
        "company",
        "corporation",
        "corp",
        "bank",
        "group",
        "holdings",
        "partnership",
        "partners",
        "product",
        "platform",
        "program",
        "initiative",
        "association",
    }
    _NON_PERSON_MOVE_TERMS = (
        "partnership",
        "joint venture",
        "collaboration",
        "product launch",
        "product partnership",
        "alliance",
        "integration",
        "merger",
        "acquisition",
        "transaction",
        "deal",
    )

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
            "skip_reasons": {},
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
            aggregate_skip_reasons: Dict[str, int] = {}
            aggregate_skip_signatures: Dict[str, Set[str]] = {}

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
                    rows, skip_reasons, skip_signatures = self._coerce_movements(
                        payload.get("movement_records", []),
                        trigger=trigger,
                        max_rows=max_rows,
                        target_company_aliases=target_company_aliases,
                    )
                    combined_rows.extend(rows)
                    for reason, count in skip_reasons.items():
                        aggregate_skip_reasons[reason] = aggregate_skip_reasons.get(reason, 0) + count
                    for reason, signatures in skip_signatures.items():
                        aggregate_skip_signatures.setdefault(reason, set()).update(signatures)
                    pass_results.append({"focus": focus, "count": len(rows), "skip_reasons": skip_reasons})
                except Exception as exc:
                    pass_results.append(
                        {
                            "focus": focus,
                            "count": 0,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                    )

            supplemental_rows, supplemental_skip_reasons, supplemental_skip_signatures = self._extract_inventory_rows_from_markdown(
                deep_research_markdown,
                trigger=trigger,
                max_rows=max_rows,
                target_company_aliases=target_company_aliases,
            )
            combined_rows.extend(supplemental_rows)
            for reason, count in supplemental_skip_reasons.items():
                aggregate_skip_reasons[reason] = aggregate_skip_reasons.get(reason, 0) + count
            for reason, signatures in supplemental_skip_signatures.items():
                aggregate_skip_signatures.setdefault(reason, set()).update(signatures)
            diagnostics["supplemental_inventory_rows"] = len(supplemental_rows)

            diagnostics["raw_response_text"] = "\n\n".join(raw_responses).strip()
            diagnostics["pass_results"] = pass_results
            diagnostics["skip_reasons"] = {
                reason: len(signatures)
                for reason, signatures in aggregate_skip_signatures.items()
            } or aggregate_skip_reasons
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
    ) -> Tuple[List[MovementRecord], Dict[str, int], Dict[str, Set[str]]]:
        if not isinstance(raw_items, list):
            return [], {}, {}

        company_aliases = self._company_aliases(target_company_aliases or [trigger.company_focus])
        deduped_rows: Dict[Tuple[str, str, str, str], Tuple[int, int, MovementRecord]] = {}
        skip_reasons: Dict[str, int] = {}
        skip_signatures: Dict[str, Set[str]] = {}

        def skip(reason: str, signature: str) -> None:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            skip_signatures.setdefault(reason, set()).add(signature)

        for entry in raw_items:
            entry_signature = self._entry_signature(entry)
            if not isinstance(entry, dict):
                skip("non_dict_entry", entry_signature)
                continue

            target_company = str(entry.get("target_company") or "").strip()
            normalized_target_aliases = self._company_aliases([target_company])
            if company_aliases and company_aliases.isdisjoint(normalized_target_aliases):
                skip("target_company_mismatch", entry_signature)
                continue

            person_name = str(entry.get("person_name") or "").strip()
            previous_role = str(entry.get("previous_role") or "").strip()
            new_role = str(entry.get("new_role") or "").strip()
            movement_type = str(entry.get("movement_type") or "").strip()
            category = self._normalize_category(entry.get("category"))
            company_context = str(entry.get("company_context") or "").strip() or "internal"
            effective_date, effective_date_precision = self._normalize_effective_date(entry.get("effective_date"))
            evidence_quote = str(entry.get("evidence_quote") or "").strip()
            source_url = str(entry.get("source_url") or "").strip()

            if not all([person_name, target_company, movement_type, category]):
                skip("missing_required_fields", entry_signature)
                continue
            if not self._looks_like_person_name(person_name):
                skip("invalid_person_name", entry_signature)
                continue
            if not (previous_role or new_role):
                skip("missing_roles", entry_signature)
                continue
            if category not in {"EXEC", "BUYER"}:
                skip("invalid_category", entry_signature)
                continue
            if not self._looks_like_person_movement(movement_type, previous_role, new_role):
                skip("invalid_movement_type", entry_signature)
                continue
            if not evidence_quote or not source_url:
                skip("missing_source", entry_signature)
                continue
            if effective_date and not self._date_within_lookback(
                effective_date,
                trigger.time_window_days,
                precision=effective_date_precision,
            ):
                skip("outside_lookback", entry_signature)
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
        return rows[:max_rows], skip_reasons, skip_signatures

    def _extract_inventory_rows_from_markdown(
        self,
        markdown: str,
        *,
        trigger: BDTrigger,
        max_rows: int,
        target_company_aliases: Optional[List[str]] = None,
    ) -> Tuple[List[MovementRecord], Dict[str, int], Dict[str, Set[str]]]:
        raw_items: List[Dict[str, Any]] = []
        target_company = str(trigger.company_focus or "").strip()
        fallback_sources = self._extract_section_source_entries(markdown)

        for category, body in self._inventory_sections(markdown).items():
            source_entries = self._extract_section_source_entries(body)
            cleaned_body = re.split(r"(?im)^\s*#{2,3}\s+Section Sources\b", body, maxsplit=1)[0].strip()
            blocks = self._inventory_blocks(cleaned_body)
            for block in blocks:
                item = self._parse_inventory_block(
                    block,
                    category=category,
                    target_company=target_company,
                    default_source=(source_entries[0] if source_entries else fallback_sources[0] if fallback_sources else ("", "")),
                )
                if item:
                    raw_items.append(item)

        return self._coerce_movements(
            raw_items,
            trigger=trigger,
            max_rows=max_rows,
            target_company_aliases=target_company_aliases,
        )

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
    def _inventory_sections(markdown: str) -> Dict[str, str]:
        sections: Dict[str, str] = {}
        exec_match = re.search(
            r"(?is)(?:^|\n)(?:#+\s*)?Executive Movement Inventory\b(?:\s*\([^)\n]*\))?[:\s]*\n(?P<body>.*?)(?=(?:\n(?:#+\s*)?Buyer Movement Inventory\b(?:\s*\([^)\n]*\))?|\Z))",
            markdown,
        )
        if exec_match:
            sections["EXEC"] = exec_match.group("body").strip()
        buyer_match = re.search(
            r"(?is)(?:^|\n)(?:#+\s*)?Buyer Movement Inventory\b(?:\s*\([^)\n]*\))?[:\s]*\n(?P<body>.*?)(?=(?:\n(?:#+\s*)?(?:Sources|Why This Account Matters Now|Recommended Actions|Likely Destination Opportunities)\b|\Z))",
            markdown,
        )
        if buyer_match:
            sections["BUYER"] = buyer_match.group("body").strip()
        return sections

    @staticmethod
    def _inventory_blocks(body: str) -> List[str]:
        cleaned = str(body or "").strip()
        if not cleaned:
            return []

        entry_pattern = re.compile(
            r"(?ms)(?P<block>^\s*(?:[•*-]\s*)?(?P<person>[A-Z][^\n]{1,160}?)\s+[–—-]\s+.*?)(?=^\s*(?:[•*-]\s*)?[A-Z][^\n]{1,160}?\s+[–—-]\s+|\Z)"
        )
        blocks = [match.group("block").strip() for match in entry_pattern.finditer(cleaned)]
        if blocks:
            return blocks

        return [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]

    @staticmethod
    def _extract_section_source_entries(body: str) -> List[Tuple[str, str]]:
        entries: List[Tuple[str, str]] = []
        for match in re.finditer(r"(?im)^[•*-]\s*(?P<title>.+?):\s*(?P<url>https?://\S+)\s*$", body):
            title = match.group("title").strip()
            url = match.group("url").strip().rstrip(").,")
            if url.startswith(("http://", "https://")):
                entries.append((title, url))
        for match in re.finditer(r"(?im)^[•*-]\s*(?P<url>https?://\S+)\s*$", body):
            url = match.group("url").strip().rstrip(").,")
            if url.startswith(("http://", "https://")):
                entries.append((url, url))
        return entries

    def _parse_inventory_block(
        self,
        block: str,
        *,
        category: str,
        target_company: str,
        default_source: Tuple[str, str],
    ) -> Optional[Dict[str, Any]]:
        text = re.sub(r"\s+", " ", block).strip()
        if not text or "section sources" in text.lower():
            return None
        match = re.match(r"(?P<person>.+?)\s+[–—-]\s+(?P<body>.+)$", text)
        if not match:
            return None

        person_name = match.group("person").strip()
        body = match.group("body").strip()
        source_title, source_url = default_source
        inline_url_match = re.search(r"https?://\S+", text)
        if inline_url_match:
            source_url = inline_url_match.group(0).rstrip(").,")
        if not source_url:
            return None

        movement_type = self._extract_move_type(body)
        previous_role, new_role = self._extract_roles_from_inventory_body(body)
        effective_date = self._extract_effective_date_from_text(body)
        evidence_quote = self._ensure_sentence(body.split("Why it matters:")[0].strip())
        source_marker_match = re.search(r"【[^】]+†source】", text)

        if not movement_type:
            movement_type = self._infer_movement_type_from_text(body)
        if not (previous_role or new_role or movement_type):
            return None

        return {
            "person_name": person_name,
            "target_company": target_company,
            "previous_role": previous_role,
            "new_role": new_role,
            "movement_type": movement_type,
            "category": category,
            "company_context": "internal",
            "effective_date": effective_date,
            "evidence_quote": evidence_quote,
            "source_url": source_url,
            "source_title": source_title or None,
            "source_marker": source_marker_match.group(0) if source_marker_match else None,
            "corroborated": False,
            "confidence_label": None,
        }

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
    def _looks_like_person_name(cls, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if any(symbol in text for symbol in ("&", "/", "|", "@")):
            return False
        if any(term in lowered for term in cls._NON_PERSON_MOVE_TERMS):
            return False

        normalized = unicodedata.normalize("NFKD", text)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        tokens = re.findall(r"[A-Za-z][A-Za-z'.-]*", normalized)
        if len(tokens) < 2 or len(tokens) > 6:
            return False
        if any(token.lower() in cls._NON_PERSON_NAME_TERMS for token in tokens):
            return False
        return True

    @classmethod
    def _looks_like_person_movement(cls, movement_type: str, previous_role: str, new_role: str) -> bool:
        combined = " ".join(
            part.strip().lower()
            for part in (movement_type, previous_role, new_role)
            if str(part or "").strip()
        )
        return not any(marker in combined for marker in cls._NON_PERSON_MOVE_TERMS)

    @staticmethod
    def _entry_signature(entry: Any) -> str:
        if not isinstance(entry, dict):
            return str(entry)
        parts = [
            str(entry.get("person_name") or "").strip().lower(),
            str(entry.get("target_company") or "").strip().lower(),
            str(entry.get("new_role") or "").strip().lower(),
            str(entry.get("movement_type") or "").strip().lower(),
            str(entry.get("source_url") or "").strip().lower(),
        ]
        return "|".join(parts)

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
    def _normalize_effective_date(value: Any) -> Tuple[Optional[str], str]:
        text = str(value or "").strip()
        if not text:
            return None, "unknown"
        text = text.replace("Sept.", "Sep.")
        text = re.sub(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s", r"\1 ", text)
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%B %d, %Y", "%b %d, %Y", "%Y-%m", "%B %Y", "%b %Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                if fmt in {"%Y-%m", "%B %Y", "%b %Y"}:
                    parsed = parsed.replace(day=1)
                    return parsed.date().isoformat(), "month"
                return parsed.date().isoformat(), "day"
            except ValueError:
                continue
        return None, "unknown"

    @staticmethod
    def _date_within_lookback(
        effective_date: str,
        lookback_days: int,
        *,
        precision: str = "day",
        today: Optional[date] = None,
    ) -> bool:
        try:
            movement_date = date.fromisoformat(effective_date)
        except ValueError:
            return True
        reference_date = today or date.today()
        cutoff = reference_date - timedelta(days=int(lookback_days or 0))
        if precision == "month":
            month_last_day = monthrange(movement_date.year, movement_date.month)[1]
            movement_date = movement_date.replace(day=month_last_day)
        return movement_date >= cutoff

    @classmethod
    def _extract_move_type(cls, text: str) -> str:
        match = re.search(r"Move Type:\s*([^.;]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        header_match = re.match(r"(?P<role>.+?)\s+[–—-]\s+(?P<label>.+?)(?::|$)", text)
        if not header_match:
            return ""
        return cls._normalize_inventory_move_label(header_match.group("label"))

    @classmethod
    def _infer_movement_type_from_text(cls, text: str) -> str:
        lowered = text.lower()
        if "retire" in lowered:
            return "Retirement"
        if any(marker in lowered for marker in ("departed", "stepped down", "resigned", "termination", "removed")):
            return "Departure"
        if any(marker in lowered for marker in ("promoted", "promotion", "scope expansion", "expanded remit")):
            return "Promotion"
        if any(marker in lowered for marker in ("appointed", "hired", "joined", "external appointment")):
            return "Appointment"
        return ""

    @classmethod
    def _extract_roles_from_inventory_body(cls, text: str) -> Tuple[str, str]:
        previous_role = ""
        new_role = ""

        patterns = [
            (r"stepped down as (?P<prev>.+?)(?:\s+on\b|\(|\.|,)", "Departed", "prev"),
            (r"departed as (?P<prev>.+?)(?:\s+on\b|\(|\.|,)", "Departed", "prev"),
            (r"retired from role as (?P<prev>.+?)(?:\s+on\b|\(|\.|,)", "", "prev"),
            (r"removed from role as (?P<prev>.+?)(?:\s+on\b|\(|\.|,)", "", "prev"),
        ]
        for pattern, implied_new_role, group_name in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                previous_role = match.group(group_name).strip()
                if implied_new_role:
                    new_role = implied_new_role
                break

        new_role_patterns = [
            r"promoted to (?P<new>.+?)(?:\(|\.|,)",
            r"appointed (?:to )?(?P<new>.+?)(?:\(| in | effective |\.|,)",
            r"hired as (?P<new>.+?)(?:\(| in | effective |\.|,)",
            r"joined as (?P<new>.+?)(?:\(| in | effective |\.|,)",
        ]
        for pattern in new_role_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                new_role = match.group("new").strip()
                break

        if not previous_role:
            prev_match = re.search(r"(?:formerly|added to (?:his|her|their) role as) (?P<prev>.+?)(?:\)|\.|,)", text, re.IGNORECASE)
            if prev_match:
                previous_role = prev_match.group("prev").strip()

        if not previous_role or not new_role:
            header_match = re.match(r"(?P<role>.+?)\s+[–—-]\s+(?P<label>.+?)(?::|$)", text)
            if header_match:
                role_candidate = cls._clean_inventory_role_fragment(header_match.group("role"))
                label_candidate = header_match.group("label").strip()
                lowered_label = label_candidate.lower()
                to_role_match = re.search(
                    r"\b(?:promotion|appointment|appointed|external appointment|external hire|internal promotion|new role|role expansion|scope change)\s+to\s+(?P<new>.+)$",
                    label_candidate,
                    re.IGNORECASE,
                )
                if to_role_match:
                    previous_role = previous_role or role_candidate
                    new_role = cls._clean_inventory_role_fragment(to_role_match.group("new"))
                elif any(
                    marker in lowered_label
                    for marker in (
                        "departure",
                        "resignation",
                        "retirement",
                        "termination",
                        "stepped down",
                        "removed",
                        "fired",
                    )
                ):
                    previous_role = previous_role or role_candidate
                elif any(
                    marker in lowered_label
                    for marker in (
                        "external hire",
                        "external appointment",
                        "appointment",
                        "new role",
                        "internal promotion",
                        "role expansion",
                        "scope change",
                        "promotion",
                    )
                ):
                    new_role = new_role or role_candidate

        return previous_role, new_role

    @staticmethod
    def _clean_inventory_role_fragment(value: str) -> str:
        text = str(value or "").strip().strip(" .,:;")
        text = re.sub(r"^(?:former|outgoing|current)\s+", "", text, flags=re.IGNORECASE)
        return text

    @classmethod
    def _normalize_inventory_move_label(cls, value: str) -> str:
        label = re.sub(r"\s+", " ", str(value or "")).strip(" .,:;")
        if not label:
            return ""

        inner_match = re.search(r"\(([^)]+)\)", label)
        inner = inner_match.group(1).strip() if inner_match else ""
        base = re.sub(r"\([^)]*\)", "", label).strip()

        combined = " ".join(part for part in (base, inner) if part).lower()
        if any(marker in combined for marker in ("resignation", "retirement", "termination", "departure", "stepped down", "removed", "fired")):
            if "resignation" in combined:
                return "Departure (Resignation)"
            if "retirement" in combined or "retired" in combined:
                return "Retirement"
            if "termination" in combined or "terminated" in combined or "fired" in combined:
                return "Departure (Termination)"
            return "Departure"
        if "rehire" in combined:
            return "Rehire"
        if "scope change" in combined:
            return "Scope Change"
        if "role expansion" in combined:
            return "Role Expansion"
        if "internal promotion" in combined:
            return "Internal Promotion"
        if "external hire" in combined:
            return "External Hire"
        if "external appointment" in combined:
            return "External Appointment"
        if "promotion" in combined:
            return "Promotion"
        if "appointment" in combined or "appointed" in combined:
            return "Appointment"
        if "new role" in combined:
            return "New Role"
        return label

    @classmethod
    def _extract_effective_date_from_text(cls, text: str) -> Optional[str]:
        candidates = [
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4}\b",
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{4}\b",
        ]
        for pattern in candidates:
            match = re.search(pattern, text)
            if not match:
                continue
            raw_value = match.group(0).strip()
            normalized, _precision = cls._normalize_effective_date(raw_value)
            if normalized:
                return raw_value
        return None

    @staticmethod
    def _ensure_sentence(text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        return cleaned if cleaned[-1] in ".!?" else f"{cleaned}."

    def _fallback_prompt(self) -> str:
        return (
            "Return JSON with movement_records from this markdown.\n"
            "Trigger: {{$trigger_summary}}\n"
            "Current date: {{$current_date_iso}}\n"
            "Max rows: {{$max_rows}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
