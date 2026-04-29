"""
Public-account Deep Research orchestration.
"""
from __future__ import annotations

import inspect
import re
from datetime import date
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.public_account_prompt_builder import (
    PublicAccountPromptBuilder,
    PublicAccountPromptPackage,
)


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None] | None]
DeepResearchRunner = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class PublicAccountResearchRunResult:
    prompt_package: PublicAccountPromptPackage
    deep_research_response: Dict[str, Any]


class PublicAccountResearchOrchestrator:
    """Run public-account Deep Research without any private-system context."""

    def __init__(
        self,
        prompt_builder: Optional[PublicAccountPromptBuilder] = None,
        deep_research_runner: Optional[DeepResearchRunner] = None,
    ) -> None:
        self.prompt_builder = prompt_builder
        self.deep_research_runner = deep_research_runner

    async def run(
        self,
        *,
        company_name: str,
        focus_hint: str | None = None,
        industry: str | None = None,
        progress_cb: Optional[ProgressCallback] = None,
    ) -> PublicAccountResearchRunResult:
        prompt_package = self._get_prompt_builder().build(
            company_name=company_name,
            focus_hint=focus_hint,
            industry=industry,
        )
        response = await self._run_deep_research(prompt_package, progress_cb=progress_cb)
        normalized = self._normalize_response(
            response,
            company_name=company_name,
            focus_hint=focus_hint,
            industry_key=prompt_package.industry_key,
        )
        return PublicAccountResearchRunResult(
            prompt_package=prompt_package,
            deep_research_response=normalized,
        )

    def _get_prompt_builder(self) -> PublicAccountPromptBuilder:
        if self.prompt_builder is None:
            self.prompt_builder = PublicAccountPromptBuilder()
        return self.prompt_builder

    def _get_deep_research_runner(self) -> DeepResearchRunner:
        if self.deep_research_runner is None:
            from tools.orchestrators import run_deep_research

            self.deep_research_runner = run_deep_research
        return self.deep_research_runner

    async def _run_deep_research(
        self,
        prompt_package: PublicAccountPromptPackage,
        *,
        progress_cb: Optional[ProgressCallback],
    ) -> Any:
        runner = self._get_deep_research_runner()
        kwargs = self._build_runner_kwargs(
            runner,
            industry=prompt_package.industry_key,
            progress_callback=self._make_deep_research_progress_wrapper(progress_cb) if progress_cb else None,
            instructions_override=prompt_package.system_prompt,
        )
        return await runner(prompt_package.user_prompt, **kwargs)

    def _make_deep_research_progress_wrapper(
        self,
        progress_cb: Optional[ProgressCallback],
    ) -> Callable[[str, Dict[str, Any]], Awaitable[None]]:
        async def _wrapped(text: str, metadata: Dict[str, Any]) -> None:
            if not progress_cb:
                return
            event = {
                "stage": "running_deep_research",
                "message": text or "Deep Research activity update.",
                "status": str(metadata.get("status") or "in_progress"),
                "citation_count": metadata.get("citation_count", 0),
                "poll_count": metadata.get("poll_count", 0),
                "activity_log": metadata.get("activity_log", []),
            }
            result = progress_cb(event)
            if inspect.isawaitable(result):
                await result

        return _wrapped

    @staticmethod
    def _build_runner_kwargs(runner, **candidate_kwargs: Any) -> Dict[str, Any]:
        signature = inspect.signature(runner)
        params = signature.parameters
        accepts_varkw = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        kwargs: Dict[str, Any] = {}
        for key, value in candidate_kwargs.items():
            if key in params or accepts_varkw:
                kwargs[key] = value
        return kwargs

    @classmethod
    def _normalize_response(
        cls,
        response: Any,
        *,
        company_name: str,
        focus_hint: str | None,
        industry_key: str,
    ) -> Dict[str, Any]:
        payload = response if isinstance(response, dict) else {"summary": str(response or "")}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

        sections: List[Dict[str, Any]] = []
        section_citations: List[Dict[str, str]] = []
        coverage_gaps = cls._normalize_gap_values(
            payload.get("coverage_gaps")
            or payload.get("coverageGaps")
            or payload.get("key_gaps")
            or payload.get("gaps")
        )

        raw_sections = payload.get("sections") or payload.get("findings") or []
        if isinstance(raw_sections, list):
            for index, section in enumerate(raw_sections, 1):
                if not isinstance(section, dict):
                    continue
                title = cls._first_text(
                    section.get("title"),
                    section.get("heading"),
                    section.get("name"),
                    default=f"Section {index}",
                )
                content = cls._first_text(
                    section.get("content"),
                    section.get("body"),
                    section.get("summary"),
                    section.get("text"),
                )
                citations = cls._normalize_citations(
                    section.get("citations")
                    or section.get("sources")
                    or section.get("links")
                )
                sections.append(
                    {
                        "title": title,
                        "content": content,
                        "citations": citations,
                    }
                )
                section_citations.extend(citations)
                if cls._is_coverage_gap_section(title):
                    coverage_gaps = cls._merge_unique_text(
                        coverage_gaps,
                        cls._normalize_gap_values(
                            section.get("items")
                            or section.get("bullets")
                            or section.get("points")
                            or content
                        ),
	                    )

        summary_text = cls._first_text(
            payload.get("summary"),
            payload.get("executive_summary"),
            payload.get("headline"),
            payload.get("account_status_summary"),
        )
        parsed_summary_sections = cls._parse_markdown_sections(summary_text)
        if parsed_summary_sections:
            existing_titles = {cls._normalize_heading(item.get("title")) for item in sections}
            for section in parsed_summary_sections:
                if cls._normalize_heading(section.get("title")) in existing_titles:
                    continue
                sections.append(section)

        coverage_gaps = cls._merge_unique_text(
            coverage_gaps,
            cls._normalize_gap_values(
                metadata.get("coverage_gaps")
                or metadata.get("coverageGaps")
                or metadata.get("key_gaps")
                or metadata.get("gaps")
            ),
        )

        citations = cls._merge_citations(
            cls._normalize_citations(payload.get("citations") or payload.get("sources")),
            section_citations,
            cls._normalize_citations(metadata.get("display_sources")),
            cls._normalize_citations(metadata.get("source_urls")),
            cls._normalize_citations(metadata.get("discovery_sources")),
            cls._normalize_citations(metadata.get("confirmation_sources")),
        )
        freshness = cls._build_freshness_assessment(
            "\n\n".join(
                [summary_text]
                + [str(section.get("content") or "") for section in sections]
            )
        )
        if freshness.get("coverage_gap"):
            coverage_gaps = cls._merge_unique_text(
                coverage_gaps,
                [str(freshness["coverage_gap"])],
            )

        return {
            "type": str(payload.get("type") or "deep_research"),
            "company_name": str(company_name or "").strip(),
            "focus_hint": str(focus_hint or "").strip(),
            "industry_key": str(industry_key or "general").strip() or "general",
            "summary": cls._best_summary(summary_text, sections),
            "sections": sections,
            "public_company_snapshot": cls._compact_text(
                cls._find_section_content(
                    sections,
                    ["company snapshot", "company overview", "business overview"],
                ),
                max_chars=1200,
            ),
            "public_strategy_priorities": cls._extract_section_items(
                sections,
                [
                    "strategy priorities and operating pressure",
                    "strategic priorities",
                    "operating pressure",
                    "strategy and priorities",
                ],
                limit=10,
            ),
            "public_filing_financial_signals": cls._extract_section_items(
                sections,
                [
                    "filings financials and risk signals",
                    "filings and financials",
                    "financial and risk signals",
                    "risk signals",
                ],
                limit=10,
            ),
            "public_competitive_context": cls._extract_section_items(
                sections,
                [
                    "competitive and market context",
                    "competitive context",
                    "market context",
                    "competitors",
                ],
                limit=10,
            ),
            "public_customer_contract_signals": cls._extract_section_items(
                sections,
                [
                    "customer contract and procurement signals",
                    "customer and contract signals",
                    "contract and procurement signals",
                    "procurement signals",
                ],
                limit=10,
            ),
            "public_likely_needs": cls._extract_section_items(
                sections,
                [
                    "likely needs white space hypotheses",
                    "likely needs",
                    "white space hypotheses",
                    "white-space hypotheses",
                    "needs and white space",
                ],
                limit=10,
            ),
            "public_people_targets": cls._extract_section_items(
                sections,
                ["people to pursue", "leadership coverage", "public leadership"],
                limit=12,
            ),
            "public_people_moves": cls._extract_section_items(
                sections,
                ["recent people moves", "executive and buyer moves", "leadership changes"],
                limit=12,
            ),
            "public_buyer_map": cls._extract_section_items(
                sections,
                ["buying committee map", "buyer center map", "org map"],
                limit=12,
            ),
            "public_buying_triggers": cls._extract_section_items(
                sections,
                ["why now current triggers", "why now", "current triggers"],
                limit=10,
            ),
            "public_initiatives": cls._extract_section_items(
                sections,
                ["recent initiatives public signals", "recent initiatives", "public signals"],
                limit=10,
            ),
            "public_relationship_hooks": cls._extract_section_items(
                sections,
                ["public relationship hooks warm path hypotheses", "public relationship hooks", "warm path hypotheses"],
                limit=8,
            ),
            "public_recommended_actions": cls._extract_section_items(
                sections,
                ["recommended md actions this week", "recommended actions", "analyst follow ups"],
                limit=8,
            ),
            "freshness_assessment": freshness,
            "citations": citations,
            "coverage_gaps": coverage_gaps,
            "metadata": metadata,
        }

    @staticmethod
    def _first_text(*values: Any, default: str = "") -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return default

    @classmethod
    def _best_summary(cls, summary_text: str, sections: List[Dict[str, Any]]) -> str:
        thesis = cls._find_section_content(sections, ["executive pursuit thesis"])
        if thesis:
            return cls._compact_text(thesis, max_chars=900)
        return cls._compact_text(summary_text, max_chars=900)

    @staticmethod
    def _compact_text(value: Any, max_chars: int = 900) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."

    @classmethod
    def _parse_markdown_sections(cls, text: str) -> List[Dict[str, Any]]:
        lines = str(text or "").splitlines()
        sections: List[Dict[str, Any]] = []
        current_title: Optional[str] = None
        current_lines: List[str] = []

        def flush() -> None:
            nonlocal current_title, current_lines
            if not current_title:
                current_lines = []
                return
            content = "\n".join(current_lines).strip()
            if content:
                sections.append(
                    {
                        "title": current_title.strip(),
                        "content": content,
                        "citations": cls._normalize_citations(cls._extract_urls_from_text(content)),
                    }
                )
            current_lines = []

        for line in lines:
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
            if match:
                flush()
                current_title = re.sub(r"[*_`]+", "", match.group(1)).strip()
                continue
            if current_title:
                current_lines.append(line)
        flush()
        return sections

    @classmethod
    def _find_section_content(cls, sections: List[Dict[str, Any]], aliases: List[str]) -> str:
        aliases_normalized = {cls._normalize_heading(alias) for alias in aliases}
        for section in list(sections or []):
            title = cls._normalize_heading(section.get("title"))
            if title in aliases_normalized:
                return str(section.get("content") or "").strip()
        return ""

    @classmethod
    def _extract_section_items(
        cls,
        sections: List[Dict[str, Any]],
        aliases: List[str],
        *,
        limit: int = 8,
    ) -> List[str]:
        content = cls._find_section_content(sections, aliases)
        if not content:
            return []
        rows: List[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$", line):
                continue
            line = re.sub(r"^\s*[-*]\s+", "", line).strip()
            line = re.sub(r"^\s*\d+[.)]\s+", "", line).strip()
            if not line:
                continue
            if line.startswith("|") and line.endswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if cells and all(cls._normalize_heading(cell) in {"person", "current role", "buyer lane", "why this person matters now", "evidence date source", "move", "date", "why it matters", "source", "buyer role", "named person or public role", "evidence", "likely concern", "follow up needed", "source date", "signal", "pursuit implication", "need or hypothesis", "likely buyer lane", "confidence", "analyst validation step"} for cell in cells):
                    continue
                line = " | ".join(cell for cell in cells if cell)
            if line and line.lower() not in {"none found", "not found", "n/a"}:
                rows.append(line)
            if len(rows) >= limit:
                break
        return cls._merge_unique_text([], rows)

    @staticmethod
    def _normalize_heading(value: Any) -> str:
        text = re.sub(r"[*_`]+", "", str(value or "").lower())
        text = text.replace("/", " ")
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_urls_from_text(text: str) -> List[str]:
        urls = re.findall(r"https?://[^\s)\]>\"']+", str(text or ""))
        return [url.rstrip(".,;:") for url in urls]

    @classmethod
    def _build_freshness_assessment(cls, text: str) -> Dict[str, Any]:
        current_year = date.today().year
        years = sorted(
            {
                int(match)
                for match in re.findall(r"\b(20[0-9]{2})\b", str(text or ""))
                if 2000 <= int(match) <= current_year
            }
        )
        newest_year = years[-1] if years else None
        stale_only = bool(years) and newest_year <= current_year - 2
        needs_review = stale_only or not years
        coverage_gap = ""
        if stale_only:
            coverage_gap = (
                f"Public research appears stale-only; newest detected evidence year is {newest_year}."
            )
        elif not years:
            coverage_gap = "Public research did not expose explicit evidence dates; verify freshness before MD use."
        return {
            "current_year": current_year,
            "year_mentions": years,
            "newest_year": newest_year,
            "stale_only": stale_only,
            "needs_review": needs_review,
            "coverage_gap": coverage_gap,
        }

    @classmethod
    def _normalize_citations(cls, raw: Any) -> List[Dict[str, str]]:
        if raw is None:
            return []
        if isinstance(raw, dict):
            items = [raw]
        elif isinstance(raw, (list, tuple, set)):
            items = list(raw)
        else:
            items = [raw]

        citations: List[Dict[str, str]] = []
        for item in items:
            url = ""
            title = ""
            if isinstance(item, str):
                url = item.strip()
                title = url
            elif isinstance(item, dict):
                url = cls._first_text(item.get("url"), item.get("link"), item.get("href"))
                title = cls._first_text(item.get("title"), item.get("name"), item.get("label"), default=url)
            if not url.startswith(("http://", "https://")):
                continue
            citations.append({"title": title or url, "url": url})
        return cls._merge_citations(citations)

    @classmethod
    def _merge_citations(cls, *citation_lists: List[Dict[str, str]]) -> List[Dict[str, str]]:
        merged: List[Dict[str, str]] = []
        seen = set()
        for citation_list in citation_lists:
            for citation in citation_list or []:
                if not isinstance(citation, dict):
                    continue
                url = cls._first_text(citation.get("url"))
                if not url.startswith(("http://", "https://")):
                    continue
                key = url.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(
                    {
                        "title": cls._first_text(citation.get("title"), default=url),
                        "url": url,
                    }
                )
        return merged

    @classmethod
    def _normalize_gap_values(cls, raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, dict):
            values = [cls._first_text(raw.get("text"), raw.get("gap"), raw.get("title"), raw.get("content"))]
        elif isinstance(raw, (list, tuple, set)):
            values = []
            for item in raw:
                values.extend(cls._normalize_gap_values(item))
        else:
            text = str(raw or "").strip()
            if not text:
                values = []
            else:
                parts = [line.strip() for line in text.splitlines()]
                values = [cls._strip_list_prefix(part) for part in parts if cls._strip_list_prefix(part)]
        return cls._merge_unique_text([], values)

    @staticmethod
    def _strip_list_prefix(value: str) -> str:
        return re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", str(value or "").strip())

    @staticmethod
    def _is_coverage_gap_section(title: str) -> bool:
        lowered = str(title or "").strip().lower()
        return any(token in lowered for token in ("gap", "caveat", "limitation"))

    @staticmethod
    def _merge_unique_text(existing: List[str], additions: List[str]) -> List[str]:
        merged = list(existing)
        seen = {item.strip().lower() for item in merged if item.strip()}
        for item in additions:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
        return merged
