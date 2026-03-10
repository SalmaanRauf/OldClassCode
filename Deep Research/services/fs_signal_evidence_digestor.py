"""
ATLAS-powered digestor for financial-services signal evidence extraction.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

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
        self._company_alias_overrides: Optional[Dict[str, List[str]]] = None

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
        section_source_map: Optional[Dict[str, List[str]]] = None,
        signal_source_candidates: Optional[Dict[str, List[str]]] = None,
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
            "discovery_source_count": 0,
            "confirmation_source_count": 0,
            "filtered_search_wrapper_count": 0,
            "source_coverage_alert": None,
            "reason_codes": [],
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

        merged_raw_sources = list(source_urls or []) + self._extract_urls(deep_research_markdown)
        discovery_sources = self._normalize_source_urls(
            merged_raw_sources,
            include_search_wrappers=True,
        )
        confirmation_sources = self._normalize_source_urls(
            merged_raw_sources,
            include_search_wrappers=False,
        )
        diagnostics["discovery_source_count"] = len(discovery_sources)
        diagnostics["confirmation_source_count"] = len(confirmation_sources)
        diagnostics["allowed_source_count"] = len(confirmation_sources)
        diagnostics["filtered_search_wrapper_count"] = max(
            0,
            len(discovery_sources) - len(confirmation_sources),
        )
        diagnostics["discovery_sources"] = discovery_sources
        diagnostics["confirmation_sources"] = confirmation_sources
        diagnostics["section_source_map_count"] = len(section_source_map or {})
        diagnostics["signal_source_candidates_count"] = len(signal_source_candidates or {})

        # Advisory warning only; do not fail run.
        if requested and len(confirmation_sources) < min(len(requested), 4):
            diagnostics["source_coverage_alert"] = (
                "Low confirmation-source coverage for requested signal breadth "
                f"({len(confirmation_sources)} sources for {len(requested)} signals)."
            )
            diagnostics["reason_codes"].append("low_confirmation_source_coverage")

        try:
            await self._ensure_kernel()
            prompt = self._render_prompt(
                trigger=trigger,
                deep_research_markdown=deep_research_markdown,
                requested_signal_codes=requested,
                allowed_sources=confirmation_sources,
                section_source_map=section_source_map or {},
                signal_source_candidates=signal_source_candidates or {},
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
                available_sources=set(confirmation_sources),
            )
            entity_aliases = self._build_entity_aliases(
                company_focus=trigger.company_focus,
                deep_research_markdown=deep_research_markdown,
            )
            enforced = self._recover_exec_transition_signal(
                enforced,
                deep_research_markdown=deep_research_markdown,
                available_sources=confirmation_sources,
                discovery_sources=discovery_sources,
                entity_aliases=entity_aliases,
            )
            enforced = self._enforce_exec_transition_entity_scope(
                signal_evidence=enforced,
                deep_research_markdown=deep_research_markdown,
                entity_aliases=entity_aliases,
            )
            enforced = self._enrich_exec_transition_signal(
                signal_evidence=enforced,
                deep_research_markdown=deep_research_markdown,
                available_sources=confirmation_sources,
                discovery_sources=discovery_sources,
                entity_aliases=entity_aliases,
            )
            enforced = self._recover_non_exec_signals(
                signal_evidence=enforced,
                deep_research_markdown=deep_research_markdown,
                available_sources=confirmation_sources,
                section_source_map=section_source_map or {},
                signal_source_candidates=signal_source_candidates or {},
                diagnostics=diagnostics,
            )

            diagnostics["signals_returned"] = len(enforced)
            diagnostics["status"] = "Succeeded"
            diagnostics["parse_outcome"] = "json_parsed_with_signal_evidence"
            return enforced, diagnostics, confirmation_sources

        except json.JSONDecodeError as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "Could not parse FS signal digest response as JSON."
            diagnostics["parse_outcome"] = "json_parse_error"
            diagnostics["error_type"] = "JSONDecodeError"
            diagnostics["error_message"] = str(exc)
            return [], diagnostics, confirmation_sources
        except Exception as exc:
            diagnostics["status"] = "Failed"
            diagnostics["reason"] = "FS signal evidence digest call failed."
            diagnostics["parse_outcome"] = "digest_failed"
            diagnostics["error_type"] = type(exc).__name__
            diagnostics["error_message"] = str(exc)
            return [], diagnostics, confirmation_sources
        finally:
            diagnostics["duration_ms"] = (perf_counter() - start) * 1000

    def _render_prompt(
        self,
        trigger: BDTrigger,
        deep_research_markdown: str,
        requested_signal_codes: List[str],
        allowed_sources: List[str],
        section_source_map: Dict[str, List[str]],
        signal_source_candidates: Dict[str, List[str]],
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
        prompt = prompt.replace("{{$section_source_map_json}}", json.dumps(section_source_map, indent=2))
        prompt = prompt.replace("{{$signal_source_candidates_json}}", json.dumps(signal_source_candidates, indent=2))
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

    def _recover_exec_transition_signal(
        self,
        signal_evidence: List[SignalEvidence],
        deep_research_markdown: str,
        available_sources: List[str],
        discovery_sources: Optional[List[str]],
        entity_aliases: Set[str],
    ) -> List[SignalEvidence]:
        """Promote exec-transition when explicit appointment evidence exists in text.

        This protects extraction quality from brittle model/source selection for
        FS.EXEC.TRANSITION while keeping evidence anchored to provided sources.
        """
        target_idx = next(
            (idx for idx, item in enumerate(signal_evidence) if item.signal_code == "FS.EXEC.TRANSITION"),
            None,
        )
        if target_idx is None:
            return signal_evidence

        current = signal_evidence[target_idx]
        text = deep_research_markdown or ""
        movement_mentions, movement_sources = self._run_exec_transition_sweep(
            deep_research_markdown=text,
            discovery_sources=discovery_sources or available_sources,
            entity_aliases=entity_aliases,
        )

        if not movement_mentions and not movement_sources:
            return signal_evidence

        normalized_available = {str(url or "").strip() for url in available_sources if str(url or "").strip()}
        preferred_source = (current.source_url or "").strip()
        if preferred_source and preferred_source not in normalized_available:
            preferred_source = ""
        if not preferred_source:
            preferred_source = self._select_exec_transition_primary_source(movement_sources)

        if current.status == "Confirmed":
            signal_evidence[target_idx] = SignalEvidence(
                signal_code=current.signal_code,
                signal_label=current.signal_label,
                status=current.status,
                evidence_quote=current.evidence_quote or (movement_mentions[0][:220] if movement_mentions else ""),
                source_url=preferred_source or current.source_url,
                source_title=current.source_title,
                analysis=current.analysis,
            )
            return signal_evidence

        # Keep deterministic recovery evidence-locked to confirmation sources.
        if not preferred_source:
            return signal_evidence

        signal_evidence[target_idx] = SignalEvidence(
            signal_code=current.signal_code,
            signal_label=current.signal_label,
            status="Confirmed",
            evidence_quote=current.evidence_quote or (movement_mentions[0][:220] if movement_mentions else ""),
            source_url=preferred_source,
            source_title=current.source_title,
            analysis=(
                f"{current.analysis} Deterministic recovery: explicit executive or board movement language detected."
                if current.analysis
                else "Deterministic recovery: explicit executive or board movement language detected."
            ),
        )
        return signal_evidence

    def _movement_pattern(self) -> re.Pattern:
        return re.compile(
            r"("
            r"\b(joining|joined|rejoined|appointed|named|hired|promoted|succeeded)\b.{0,260}\b("
            r"business chief risk officer|chief risk(?:\s*&\s*regulatory|\s+and\s+regulatory)? officer|"
            r"chief financial officer|chief compliance officer|head of risk|"
            r"\bcro\b|\bcfo\b|\bcco\b|\bcrro\b"
            r")\b"
            r"|"
            r"\b(board of directors|serve on .* board|committee assignment|committee placements?|board refresh|board expansion)\b"
            r")",
            re.IGNORECASE | re.DOTALL,
        )

    def _build_entity_aliases(
        self,
        company_focus: Optional[str],
        deep_research_markdown: str,
    ) -> Set[str]:
        aliases: Set[str] = set()
        focus = (company_focus or "").strip().lower()
        if not focus:
            return aliases

        aliases.add(focus)
        aliases.add(focus.replace(" ", ""))
        aliases.add(focus.replace("&", "and").replace("  ", " ").strip())

        # Legal-name normalization (generic across institutions).
        legal_suffixes = (
            " inc",
            " incorporated",
            " corp",
            " corporation",
            " llc",
            " plc",
            " ltd",
            " limited",
            " holdings",
            " holding company",
            " company",
            " co",
            " group",
            " bank",
            " financial services",
        )
        trimmed_focus = focus
        for suffix in legal_suffixes:
            if trimmed_focus.endswith(suffix):
                trimmed_focus = trimmed_focus[: -len(suffix)].strip()
        if trimmed_focus and trimmed_focus != focus:
            aliases.add(trimmed_focus)
            aliases.add(trimmed_focus.replace(" ", ""))

        # Add tokenized focus variants but avoid very short noisy terms.
        for piece in re.split(r"[/,&\-\(\)\|]", focus):
            normalized_piece = re.sub(r"\s+", " ", piece).strip()
            if len(normalized_piece) >= 3:
                aliases.add(normalized_piece)
                aliases.add(normalized_piece.replace(" ", ""))

        # Ticker-style aliases from user-provided company focus text.
        focus_raw = (company_focus or "").strip()
        for ticker in re.findall(r"\(([A-Za-z]{2,6})\)", focus_raw):
            normalized_ticker = ticker.strip().lower()
            if normalized_ticker:
                aliases.add(normalized_ticker)

        # Optional customer-specific alias pack (external config, not hardcoded).
        overrides = self._load_company_alias_overrides()
        override_keys = {
            focus,
            focus.replace(" ", ""),
        }
        for key in override_keys:
            for alias in overrides.get(key, []):
                normalized_alias = str(alias or "").strip().lower()
                if normalized_alias:
                    aliases.add(normalized_alias)
                    aliases.add(normalized_alias.replace(" ", ""))

        # Keep low-noise aliases only.
        cleaned = set()
        for alias in aliases:
            normalized_alias = re.sub(r"\s+", " ", alias).strip()
            if len(normalized_alias) < 3:
                continue
            cleaned.add(normalized_alias)
        return cleaned

    def _load_company_alias_overrides(self) -> Dict[str, List[str]]:
        if self._company_alias_overrides is not None:
            return self._company_alias_overrides
        config_path = Path(__file__).parent.parent / "config" / "company_alias_overrides.json"
        if not config_path.exists():
            self._company_alias_overrides = {}
            return self._company_alias_overrides
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            normalized: Dict[str, List[str]] = {}
            if isinstance(payload, dict):
                for key, values in payload.items():
                    normalized_key = str(key or "").strip().lower()
                    if not normalized_key:
                        continue
                    aliases = [str(value or "").strip() for value in (values or []) if str(value or "").strip()]
                    if aliases:
                        normalized[normalized_key] = aliases
            self._company_alias_overrides = normalized
        except Exception:
            self._company_alias_overrides = {}
        return self._company_alias_overrides

    def _is_entity_linked(
        self,
        text: str,
        entity_aliases: Set[str],
    ) -> bool:
        if not entity_aliases:
            return True
        normalized = (text or "").lower()
        if not normalized:
            return False
        return any(alias in normalized for alias in entity_aliases)

    def _has_entity_linked_movement(
        self,
        text: str,
        entity_aliases: Set[str],
    ) -> bool:
        if not text:
            return False
        pattern = self._movement_pattern()
        for match in pattern.finditer(text):
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 120)
            window = text[start:end]
            if self._is_entity_linked(window, entity_aliases):
                return True
        return False

    def _extract_entity_linked_movement_mentions(
        self,
        text: str,
        entity_aliases: Set[str],
        max_items: int = 6,
    ) -> List[str]:
        if not text:
            return []

        mentions: List[str] = []
        seen = set()
        pattern = self._movement_pattern()
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end < 0:
                line_end = len(text)
            snippet = text[line_start:line_end].strip()
            if len(snippet) < 32:
                window_start = max(0, match.start() - 140)
                window_end = min(len(text), match.end() + 220)
                snippet = text[window_start:window_end].strip()
            if not snippet:
                continue
            if not self._is_entity_linked(snippet, entity_aliases):
                continue
            cleaned = re.sub(r"\s+", " ", snippet).strip()
            key = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            mentions.append(cleaned[:360].rstrip())
            if len(mentions) >= max_items:
                break

        return mentions

    def _has_entity_linked_movement_near_url(
        self,
        text: str,
        url: str,
        entity_aliases: Set[str],
        window: int = 320,
    ) -> bool:
        """Check whether movement language appears close to a URL mention in markdown."""
        if not text or not url:
            return False
        normalized_text = text.lower()
        normalized_url = str(url or "").strip().lower()
        if not normalized_url:
            return False

        idx = normalized_text.find(normalized_url)
        if idx < 0:
            return False

        start = max(0, idx - window)
        end = min(len(normalized_text), idx + len(normalized_url) + window)
        context = normalized_text[start:end]
        return self._has_entity_linked_movement(context, entity_aliases)

    def _movement_source_url_candidates(
        self,
        available_sources: List[str],
        deep_research_markdown: str,
        entity_aliases: Set[str],
    ) -> List[str]:
        movement_keywords = (
            "people-move",
            "people-moves",
            "appointment",
            "appointed",
            "joining",
            "joined",
            "rejoined",
            "chief-risk",
            "business-cro",
            "cro",
            "crro",
            "cfo",
            "cco",
            "board",
            "committee",
            "governance",
            "global-payments-network",
        )
        alias_url_tokens = set()
        for alias in entity_aliases:
            cleaned = alias.replace(" ", "")
            if cleaned:
                alias_url_tokens.add(cleaned)
            dashed = alias.replace(" ", "-")
            if dashed:
                alias_url_tokens.add(dashed)

        has_entity_linked_movement_text = self._has_entity_linked_movement(
            text=deep_research_markdown or "",
            entity_aliases=entity_aliases,
        )
        movement_mentions = self._extract_entity_linked_movement_mentions(
            text=deep_research_markdown or "",
            entity_aliases=entity_aliases,
            max_items=12,
        )
        movement_mentions_text = " ".join(movement_mentions).lower()

        candidates: List[str] = []
        seen = set()
        for raw_url in available_sources:
            url = str(raw_url or "").strip()
            if not url:
                continue
            normalized = url.lower()
            try:
                host = urlparse(url).netloc.lower().strip().removeprefix("www.")
            except Exception:
                host = ""

            movement_indicated = any(keyword in normalized for keyword in movement_keywords)
            movement_near_url = self._has_entity_linked_movement_near_url(
                text=deep_research_markdown or "",
                url=url,
                entity_aliases=entity_aliases,
            )
            if movement_near_url:
                movement_indicated = True
            if (
                not movement_indicated
                and (
                    "linkedin.com/posts/" in normalized
                    or host.endswith("sec.gov")
                    or self._is_issuer_host(host)
                )
                and has_entity_linked_movement_text
            ):
                movement_indicated = True
            if not movement_indicated:
                continue

            host_linked = host.endswith("sec.gov") or self._is_issuer_host(host)
            entity_linked = (
                self._is_entity_linked(normalized, entity_aliases)
                or any(token and token in normalized for token in alias_url_tokens)
                or self._is_alias_near_url(
                    text=deep_research_markdown or "",
                    url=url,
                    entity_aliases=entity_aliases,
                )
                or movement_near_url
            )
            if not entity_linked and "linkedin.com" in host and has_entity_linked_movement_text:
                entity_linked = True
            if not entity_linked and host_linked and has_entity_linked_movement_text:
                entity_linked = True
            if (
                not entity_linked
                and "fintechmagazine.com" in host
                and "people-move" in normalized
                and self._slug_overlap_with_mentions(url, movement_mentions_text) >= 2
            ):
                entity_linked = True
            if not entity_linked:
                continue

            if url not in seen:
                seen.add(url)
                candidates.append(url)

        return candidates

    def _slug_overlap_with_mentions(self, url: str, mentions_text: str) -> int:
        if not url or not mentions_text:
            return 0
        try:
            path = (urlparse(url).path or "").lower()
        except Exception:
            return 0
        if not path:
            return 0

        slug = path.split("/")[-1]
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", slug)
            if token and len(token) >= 3 and token not in {"people", "move", "moves", "news"}
        ]
        if not tokens:
            return 0
        return sum(1 for token in tokens if token in mentions_text)

    def _is_issuer_host(self, host: str) -> bool:
        normalized = (host or "").strip().lower()
        if not normalized:
            return False
        if normalized.startswith("investor."):
            return True
        if normalized.startswith("ir."):
            return True
        if ".gcs-web.com" in normalized:
            return True
        return False

    def _select_exec_transition_primary_source(self, candidate_urls: List[str]) -> str:
        """Select one canonical URL while preserving all other movement URLs in analysis."""
        if not candidate_urls:
            return ""

        def _priority(url: str) -> int:
            normalized = url.lower()
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if host.endswith("sec.gov"):
                return 0
            if self._is_issuer_host(host):
                return 1
            if any(media_host in host for media_host in ("reuters.com", "bloomberg.com", "wsj.com", "ft.com", "apnews.com")):
                return 2
            if "linkedin.com/posts/" in normalized or host.endswith("linkedin.com"):
                return 4
            if host:
                return 3
            return 5

        return min(candidate_urls, key=lambda url: (_priority(url), candidate_urls.index(url)))

    def _enrich_exec_transition_signal(
        self,
        signal_evidence: List[SignalEvidence],
        deep_research_markdown: str,
        available_sources: List[str],
        discovery_sources: Optional[List[str]],
        entity_aliases: Set[str],
    ) -> List[SignalEvidence]:
        target_idx = next(
            (idx for idx, item in enumerate(signal_evidence) if item.signal_code == "FS.EXEC.TRANSITION"),
            None,
        )
        if target_idx is None:
            return signal_evidence

        item = signal_evidence[target_idx]
        movement_mentions, movement_sources = self._run_exec_transition_sweep(
            deep_research_markdown=deep_research_markdown or "",
            discovery_sources=discovery_sources or available_sources,
            entity_aliases=entity_aliases,
        )
        if not movement_mentions and not movement_sources:
            return signal_evidence

        analysis = (item.analysis or "").strip()
        movement_summary = ""
        if movement_mentions:
            movement_summary = "Material target-company movements observed: " + " | ".join(
                f"{idx + 1}) {snippet}" for idx, snippet in enumerate(movement_mentions)
            )
        source_summary = ""
        if movement_sources:
            source_summary = "Movement sources: " + "; ".join(movement_sources[:12]) + "."

        pieces = [piece for piece in [analysis, movement_summary, source_summary] if piece]
        updated_analysis = " ".join(pieces).strip()

        preferred_source = (item.source_url or "").strip()
        if not preferred_source:
            preferred_source = self._select_exec_transition_primary_source(movement_sources)

        updated_status = item.status
        has_confirmable_source = bool(preferred_source or (item.source_url or "").strip())
        if item.status != "Confirmed" and (movement_mentions or movement_sources) and has_confirmable_source:
            updated_status = "Confirmed"

        updated_quote = item.evidence_quote or (movement_mentions[0][:220] if movement_mentions else "")
        signal_evidence[target_idx] = SignalEvidence(
            signal_code=item.signal_code,
            signal_label=item.signal_label,
            status=updated_status,
            evidence_quote=updated_quote,
            source_url=preferred_source,
            source_title=item.source_title,
            analysis=updated_analysis,
        )
        return signal_evidence

    def _run_exec_transition_sweep(
        self,
        deep_research_markdown: str,
        discovery_sources: List[str],
        entity_aliases: Set[str],
    ) -> Tuple[List[str], List[str]]:
        """
        Deterministic second-pass sweep for all target-company people movements.

        Uses full discovery sources for recall, then constrains surfaced source list to
        displayable URLs for user-facing analysis text.
        """
        mentions = self._extract_entity_linked_movement_mentions(
            text=deep_research_markdown or "",
            entity_aliases=entity_aliases,
            max_items=12,
        )
        movement_candidates = self._movement_source_url_candidates(
            available_sources=discovery_sources or [],
            deep_research_markdown=deep_research_markdown or "",
            entity_aliases=entity_aliases,
        )
        surfaced_sources = [
            url for url in movement_candidates if self._is_displayable_source_url(url)
        ]
        return mentions, surfaced_sources

    def _recover_non_exec_signals(
        self,
        signal_evidence: List[SignalEvidence],
        deep_research_markdown: str,
        available_sources: List[str],
        section_source_map: Dict[str, List[str]],
        signal_source_candidates: Dict[str, List[str]],
        diagnostics: Dict[str, Any],
    ) -> List[SignalEvidence]:
        """Deterministic recovery path for non-exec FS signals.

        Tiered policy:
        - Confirmed when a signal mention span exists and at least one confirmation source is available.
        - Insufficient when mention exists but no source candidate can be mapped.
        - Rejected when no support exists in provided evidence.
        """
        text = deep_research_markdown or ""
        normalized_available = [
            url for url in (available_sources or []) if self._is_displayable_source_url(url)
        ]
        reason_codes: List[str] = diagnostics.setdefault("reason_codes", [])

        updated: List[SignalEvidence] = []
        for item in signal_evidence:
            if item.signal_code == "FS.EXEC.TRANSITION":
                updated.append(item)
                continue
            if item.status == "Confirmed":
                updated.append(item)
                continue

            mentions = self._extract_non_exec_signal_mentions(item.signal_code, text)
            source_candidates = self._signal_source_candidates(
                signal_code=item.signal_code,
                available_sources=normalized_available,
                section_source_map=section_source_map,
                signal_source_candidates=signal_source_candidates,
            )

            if mentions and source_candidates:
                source_url = (item.source_url or "").strip()
                if source_url not in source_candidates:
                    source_url = source_candidates[0]
                evidence_quote = (item.evidence_quote or "").strip() or mentions[0][:220]
                analysis = (item.analysis or "").strip()
                if analysis:
                    analysis = (
                        f"{analysis} Deterministic recovery: signal mention span matched "
                        "and mapped to confirmation source candidates."
                    )
                else:
                    analysis = (
                        "Deterministic recovery: signal mention span matched and mapped to "
                        "confirmation source candidates."
                    )
                updated.append(
                    SignalEvidence(
                        signal_code=item.signal_code,
                        signal_label=item.signal_label,
                        status="Confirmed",
                        evidence_quote=evidence_quote,
                        source_url=source_url,
                        source_title=item.source_title or self._source_title_from_url(source_url),
                        analysis=analysis,
                    )
                )
                if "non_exec_recovered_confirmed" not in reason_codes:
                    reason_codes.append("non_exec_recovered_confirmed")
                continue

            if mentions and not source_candidates:
                analysis = (item.analysis or "").strip()
                if analysis:
                    analysis = (
                        f"{analysis} Mention found but no mapped confirmation source candidate "
                        "was available."
                    )
                else:
                    analysis = "Mention found but no mapped confirmation source candidate was available."
                updated.append(
                    SignalEvidence(
                        signal_code=item.signal_code,
                        signal_label=item.signal_label,
                        status="Insufficient",
                        evidence_quote=(item.evidence_quote or "").strip() or mentions[0][:220],
                        source_url=item.source_url,
                        source_title=item.source_title,
                        analysis=analysis,
                    )
                )
                if "non_exec_missing_source_mapping" not in reason_codes:
                    reason_codes.append("non_exec_missing_source_mapping")
                continue

            if item.status == "Rejected":
                updated.append(item)
                if "non_exec_no_signal_support" not in reason_codes:
                    reason_codes.append("non_exec_no_signal_support")
                continue

            updated.append(item)

        return updated

    def _extract_non_exec_signal_mentions(self, signal_code: str, text: str) -> List[str]:
        if not text:
            return []
        pattern_map = {
            "FS.CONSUMER.LITIGATION_SETTLEMENT": re.compile(
                r"\b(settlement|class[- ]action|consent order|enforcement action|civil money penalty|restitution|lawsuit)\b.{0,240}",
                re.IGNORECASE | re.DOTALL,
            ),
            "FS.MODEL_RISK.FINDINGS": re.compile(
                r"\b(model risk|sr 11[- ]?7|model validation|model governance|occ 2011[- ]?12)\b.{0,220}",
                re.IGNORECASE | re.DOTALL,
            ),
            "FS.STRESS_TEST.ISSUES": re.compile(
                r"\b(stress test|ccar|dfast|stress capital buffer|scb)\b.{0,220}",
                re.IGNORECASE | re.DOTALL,
            ),
            "FS.REGULATORY.DEADLINE": re.compile(
                r"\b(deadline|due by|effective date|implementation date|within 120 days|submission)\b.{0,220}",
                re.IGNORECASE | re.DOTALL,
            ),
            "FS.AML.BSA_FINDINGS": re.compile(
                r"\b(aml|bsa|fincen|kyc|cdd|sanctions|suspicious activity)\b.{0,220}",
                re.IGNORECASE | re.DOTALL,
            ),
            "FS.CECL.IMPLEMENTATION": re.compile(
                r"\b(cecl|asc 326|expected credit loss|allowance)\b.{0,220}",
                re.IGNORECASE | re.DOTALL,
            ),
        }
        pattern = pattern_map.get(signal_code)
        if pattern is None:
            return []

        mentions: List[str] = []
        seen = set()
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if line_end < 0:
                line_end = len(text)
            snippet = text[line_start:line_end].strip()
            if len(snippet) < 24:
                snippet = text[max(0, match.start() - 120): min(len(text), match.end() + 180)].strip()
            cleaned = re.sub(r"\s+", " ", snippet).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            mentions.append(cleaned[:320])
            if len(mentions) >= 8:
                break
        return mentions

    def _signal_source_candidates(
        self,
        signal_code: str,
        available_sources: List[str],
        section_source_map: Dict[str, List[str]],
        signal_source_candidates: Dict[str, List[str]],
    ) -> List[str]:
        candidates: List[str] = []
        seen = set()

        for source in signal_source_candidates.get(signal_code, []) or []:
            normalized = str(source or "").strip()
            if not normalized or normalized not in available_sources:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(normalized)

        if candidates:
            return candidates

        keywords_map = {
            "FS.CONSUMER.LITIGATION_SETTLEMENT": ("settlement", "litigation", "consent", "enforcement", "lawsuit"),
            "FS.MODEL_RISK.FINDINGS": ("model", "validation", "sr 11-7", "risk"),
            "FS.STRESS_TEST.ISSUES": ("stress", "ccar", "dfast", "scb"),
            "FS.REGULATORY.DEADLINE": ("deadline", "effective", "due", "regulatory"),
            "FS.AML.BSA_FINDINGS": ("aml", "bsa", "fincen", "sanctions", "kyc"),
            "FS.CECL.IMPLEMENTATION": ("cecl", "allowance", "credit loss", "asc 326"),
        }
        keywords = keywords_map.get(signal_code, ())
        for section_title, urls in (section_source_map or {}).items():
            lowered = str(section_title or "").lower()
            if keywords and not any(token in lowered for token in keywords):
                continue
            for source in urls or []:
                normalized = str(source or "").strip()
                if not normalized or normalized not in available_sources:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(normalized)

        if candidates:
            return candidates

        # Final fallback: find URLs that semantically match signal keywords.
        for source in available_sources:
            lowered = source.lower()
            if signal_code == "FS.CONSUMER.LITIGATION_SETTLEMENT" and any(
                token in lowered for token in ("settlement", "litigation", "lawsuit", "consent", "enforcement")
            ):
                candidates.append(source)
            elif signal_code == "FS.MODEL_RISK.FINDINGS" and any(
                token in lowered for token in ("model", "validation", "risk")
            ):
                candidates.append(source)
            elif signal_code == "FS.STRESS_TEST.ISSUES" and any(
                token in lowered for token in ("stress", "ccar", "dfast", "scb")
            ):
                candidates.append(source)
            elif signal_code == "FS.REGULATORY.DEADLINE" and any(
                token in lowered for token in ("deadline", "rule", "occ", "fdic", "federalreserve")
            ):
                candidates.append(source)
            elif signal_code == "FS.AML.BSA_FINDINGS" and any(
                token in lowered for token in ("aml", "bsa", "fincen", "sanction")
            ):
                candidates.append(source)
            elif signal_code == "FS.CECL.IMPLEMENTATION" and any(
                token in lowered for token in ("cecl", "allowance", "accounting")
            ):
                candidates.append(source)

        deduped: List[str] = []
        seen_final = set()
        for source in candidates:
            key = source.lower()
            if key in seen_final:
                continue
            seen_final.add(key)
            deduped.append(source)
        return deduped

    def _source_title_from_url(self, url: str) -> Optional[str]:
        try:
            host = urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            return None
        if not host:
            return None
        return host

    def _enforce_exec_transition_entity_scope(
        self,
        signal_evidence: List[SignalEvidence],
        deep_research_markdown: str,
        entity_aliases: Set[str],
    ) -> List[SignalEvidence]:
        if not entity_aliases:
            return signal_evidence

        normalized: List[SignalEvidence] = []
        for item in signal_evidence:
            if item.signal_code != "FS.EXEC.TRANSITION":
                normalized.append(item)
                continue

            combined = " ".join(
                [
                    item.evidence_quote or "",
                    item.source_title or "",
                    item.source_url or "",
                ]
            )
            linked = self._is_entity_linked(combined, entity_aliases)
            if not linked and item.evidence_quote:
                linked = self._is_alias_near_quote(
                    text=deep_research_markdown or "",
                    quote=item.evidence_quote,
                    entity_aliases=entity_aliases,
                )
            if (
                not linked
                and "deterministic recovery" in (item.analysis or "").lower()
                and not item.evidence_quote
            ):
                linked = self._has_entity_linked_movement(
                    text=deep_research_markdown or "",
                    entity_aliases=entity_aliases,
                )

            if item.status == "Confirmed" and not linked:
                analysis = (
                    f"{item.analysis} Demoted: movement evidence was not explicitly linked to target company scope."
                    if item.analysis
                    else "Demoted: movement evidence was not explicitly linked to target company scope."
                )
                normalized.append(
                    SignalEvidence(
                        signal_code=item.signal_code,
                        signal_label=item.signal_label,
                        status="Insufficient",
                        evidence_quote=item.evidence_quote,
                        source_url=item.source_url,
                        source_title=item.source_title,
                        analysis=analysis,
                    )
                )
            else:
                normalized.append(item)

        return normalized

    def _is_alias_near_quote(
        self,
        text: str,
        quote: str,
        entity_aliases: Set[str],
    ) -> bool:
        if not text or not quote:
            return False
        normalized_text = text.lower()
        normalized_quote = quote.strip().lower()
        if not normalized_quote:
            return False
        idx = normalized_text.find(normalized_quote)
        if idx < 0:
            return False
        start = max(0, idx - 140)
        end = min(len(normalized_text), idx + len(normalized_quote) + 140)
        return self._is_entity_linked(normalized_text[start:end], entity_aliases)

    def _is_alias_near_url(
        self,
        text: str,
        url: str,
        entity_aliases: Set[str],
    ) -> bool:
        if not text or not url:
            return False
        normalized_text = text.lower()
        normalized_url = url.lower().strip()
        idx = normalized_text.find(normalized_url)
        if idx < 0:
            return False
        start = max(0, idx - 180)
        end = min(len(normalized_text), idx + len(normalized_url) + 180)
        return self._is_entity_linked(normalized_text[start:end], entity_aliases)

    def _normalize_source_urls(
        self,
        urls: Iterable[str],
        include_search_wrappers: bool,
    ) -> List[str]:
        normalized: List[str] = []
        seen = set()
        for raw in urls:
            cleaned = str(raw or "").strip().rstrip(".,;)")
            if not cleaned.startswith(("http://", "https://")):
                continue
            if not include_search_wrappers and not self._is_displayable_source_url(cleaned):
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(cleaned)
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

    def _is_displayable_source_url(self, url: str) -> bool:
        normalized = (url or "").strip().lower()
        if not normalized.startswith(("http://", "https://")):
            return False
        try:
            parsed = urlparse(normalized)
            host = parsed.netloc.removeprefix("www.")
            path = parsed.path or ""
            query = parsed.query or ""
        except Exception:
            return False

        if host.endswith("bing.com") and path.startswith("/search"):
            return False
        if host.endswith("google.com") and path.startswith("/search"):
            return False
        if host.endswith("yahoo.com") and path.startswith("/search"):
            return False
        if "search?" in normalized and ("q=" in query or "query=" in query):
            return False
        return True

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
            "Section Source Map: {{$section_source_map_json}}\n"
            "Signal Source Candidates: {{$signal_source_candidates_json}}\n"
            "Markdown:\n{{$deep_research_markdown}}\n"
        )
