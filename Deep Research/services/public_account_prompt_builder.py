"""
Prompt composition for public-account Deep Research runs.
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass

from services.prompt_loader import PromptLoader


PUBLIC_ACCOUNT_OVERLAY = """
## Public Account Overlay
- This research run supports a public-account brief rather than a generic company briefing.
- Ground the work in publicly accessible reporting, filings, company materials, regulatory disclosures, and reputable news coverage.
- Prioritize current business pressure, leadership context, likely buyer priorities, and credible opportunity areas supported by public evidence.
- This is for an upcoming pursuit. Prioritize the last 180 days, with special attention to the last 30-90 days when evidence exists.
- Do not rely on stale 2024-only material unless it directly explains a still-active current initiative, and label that limitation clearly.
- Do not infer private commercial relationships, contracts, delivery history, or active sales activity that is not supported by public sources.
- Call out coverage gaps when public evidence is thin, conflicting, or absent.
- Keep observed facts separate from clearly labeled inference.
""".strip()


@dataclass(frozen=True)
class PublicAccountPromptPackage:
    industry_key: str
    system_prompt: str
    user_prompt: str


class PublicAccountPromptBuilder:
    """Compose Deep Research prompts for public-account research."""

    def __init__(self, prompt_loader: PromptLoader | None = None) -> None:
        self.prompt_loader = prompt_loader or PromptLoader()

    def build(
        self,
        *,
        company_name: str,
        focus_hint: str | None = None,
        industry: str | None = None,
        as_of_date: str | None = None,
    ) -> PublicAccountPromptPackage:
        resolved_company = str(company_name or "").strip()
        if not resolved_company:
            raise ValueError("company_name is required")

        industry_key = self._select_industry(industry)
        base_prompt = self.prompt_loader.load_prompt(industry_key)
        return PublicAccountPromptPackage(
            industry_key=industry_key,
            system_prompt=f"{base_prompt}\n\n{PUBLIC_ACCOUNT_OVERLAY}",
            user_prompt=self._build_user_prompt(
                company_name=resolved_company,
                focus_hint=focus_hint,
                industry_key=industry_key,
                include_industry_context=bool(str(industry or "").strip()),
                as_of_date=as_of_date or date.today().isoformat(),
            ),
        )

    def _select_industry(self, industry: str | None) -> str:
        if str(industry or "").strip():
            resolved = self.prompt_loader.resolve_industry_key(industry)
            if resolved:
                return resolved
        return "general"

    def _build_user_prompt(
        self,
        *,
        company_name: str,
        focus_hint: str | None,
        industry_key: str,
        include_industry_context: bool,
        as_of_date: str,
    ) -> str:
        lines = [
            f"Build a public-account research brief for an upcoming pursuit at {company_name}.",
            "",
            "## Scope",
            f"Company: {company_name}",
            f"Current as of: {as_of_date}",
        ]
        if include_industry_context:
            lines.append(f"Industry: {self._format_industry_label(industry_key)}")
        normalized_focus_hint = str(focus_hint or "").strip()
        if normalized_focus_hint:
            lines.append(f"Focus hint: {normalized_focus_hint}")
        lines.extend(
            [
                "",
                "## Required Output",
                "1. A concise headline that explains the company's current public pressure profile.",
                "2. A grounded why-now summary based on recent public evidence, prioritizing the last 180 days and last 30-90 days.",
                "3. A leadership and buyer-center map covering C-suite, finance, IT, legal, risk, operations, and relevant business-unit leaders where public evidence exists.",
                "4. Current public initiatives, investments, leadership changes, risk/compliance issues, technology modernization, procurement, partnerships, or market events that could support an MD-level pursuit.",
                "5. Suggested pursuit angles and analyst follow-ups clearly tied to cited evidence.",
                "6. Clear coverage gaps where recent public reporting is thin or missing.",
                "",
                "## Research Standard",
                "Use explicit section headings and preserve source-backed evidence throughout the report.",
                "Do not rely on stale 2024-only material unless it directly explains a still-active current initiative.",
            ]
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _format_industry_label(industry_key: str) -> str:
        return (industry_key or "general").replace("_", " ").title()
