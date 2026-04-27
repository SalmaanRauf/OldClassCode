"""
Prompt composition for public-account Deep Research runs.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.prompt_loader import PromptLoader


PUBLIC_ACCOUNT_OVERLAY = """
## Public Account Overlay
- This research run supports a public-account brief rather than a generic company briefing.
- Ground the work in publicly accessible reporting, filings, company materials, regulatory disclosures, and reputable news coverage.
- Prioritize current business pressure, leadership context, likely buyer priorities, and credible opportunity areas supported by public evidence.
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
    ) -> str:
        lines = [
            f"Build a public-account research brief for {company_name}.",
            "",
            "## Scope",
            f"Company: {company_name}",
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
                "2. A grounded why-now summary based on current public evidence.",
                "3. A buyer and leadership posture summary tied to the available public record.",
                "4. Credible opportunity areas supported by explicit source-backed evidence.",
                "5. Clear coverage gaps where public reporting is thin or missing.",
                "",
                "## Research Standard",
                "Use explicit section headings and preserve source-backed evidence throughout the report.",
            ]
        )
        return "\n".join(lines).strip()

    @staticmethod
    def _format_industry_label(industry_key: str) -> str:
        return (industry_key or "general").replace("_", " ").title()
