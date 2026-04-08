"""
Prompt composition for the named-move People Movement Brief workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List

from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight
from services.prompt_loader import PromptLoader


NAMED_MOVE_OVERLAY = """
## People Movement Account Overlay
- This research run supports a movement-led account brief, not a generic company briefing.
- Keep the research broad across requested Financial Services signals, but treat executive movement and buyer movement as primary success criteria for this workflow.
- Focus research on the destination account and the requested lookback window.
- Bias findings toward signals that explain why the account matters now, while preserving broader account-signal coverage.
- Preserve source-backed movement evidence that can later feed the leverage table.
- Preserve a broad inventory of materially supported executive and buyer movers across the destination account instead of only a short shortlist of obvious names.
- Try to preserve roughly 15-18 total movers across the two inventories when the evidence supports that many.
- The downstream workflow ranks and prioritizes later. Optimize for recall here, not aggressive commercial pruning inside the research report.
- Use both the destination account's legal name and common alias in searches whenever both exist.
- Prefer recall over conservative pruning. When top-tier evidence is sparse, keep medium-confidence movers with explicit role-and-employer support from leadership pages, governance pages, conference bios, investor materials, or explicit self-disclosures rather than ending the inventory early.
- Preserve appointments, promotions, acting roles, external hires, scope expansions, and materially relevant departures, resignations, or terminations when they create a vacancy, successor decision, governance gap, or backfill opportunity.
- Do not stop after finding only a few obvious names. Continue until the destination account has been checked across audit, finance, risk, compliance, legal, technology, security, data/AI, and operations/transformation buyer centers.
- If buyer movement is materially thinner than executive movement, keep spending search effort on buyer-center discovery instead of ending early with an executive-heavy list.
- Use title-family search expansion when buyer recall is thin. Explicitly search for and preserve moves involving General Counsel, Deputy General Counsel, Corporate Secretary, Chief Audit Executive, Chief Control Officer, Chief Control Office leaders, Chief Compliance Officer, Chief Risk Officer, Chief Operating Officer, COO, co-COO, Chief Information Officer, Chief Information Security Officer, Chief Data/AI leaders, Enterprise Operations leaders, operations leaders, and Single-Family/Multifamily business leaders when they are tied to the destination account.
- Maintain a coverage checklist across the buyer centers and major executive lanes. Do not finalize the report until each lane has been checked with targeted title-family searches or the evidence is exhausted.
- If the movement inventory is still below roughly 15 movers, continue targeted searches across issuer newsroom, leadership pages, governance pages, investor relations, conference bios, and corroborated self-disclosures before concluding that evidence is weak.
- Do not compress multiple movers into prose when they can be listed explicitly in inventories.
- Preserve explicit Executive Movement Inventory and Buyer Movement Inventory sections in the final report with one line per mover covering name, new role, move type, why it matters, and source.
""".strip()


@dataclass
class MovementPromptPackage:
    industry_key: str
    system_prompt: str
    user_prompt: str


class MovementPromptBuilder:
    """Compose Deep Research prompts for the named-move People Movement Brief."""

    def __init__(self, prompt_loader: PromptLoader | None = None) -> None:
        self.prompt_loader = prompt_loader or PromptLoader()

    def build(
        self,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
    ) -> MovementPromptPackage:
        industry_key = self._select_industry(request, preflight)
        base_prompt = self.prompt_loader.load_prompt(industry_key)
        return MovementPromptPackage(
            industry_key=industry_key,
            system_prompt=f"{base_prompt}\n\n{NAMED_MOVE_OVERLAY}",
            user_prompt=self._build_user_prompt(request, preflight),
        )

    def _select_industry(self, request: MovementBriefRequest, preflight: TransitionPreflight) -> str:
        for candidate in (request.industry_override, preflight.inferred_industry, "general"):
            if not str(candidate or "").strip():
                continue
            resolved = self.prompt_loader.resolve_industry_key(candidate)
            if resolved:
                return resolved
        return "general"

    def _build_user_prompt(
        self,
        request: MovementBriefRequest,
        preflight: TransitionPreflight,
    ) -> str:
        resolved_to_company = str(preflight.to_account.company_name or "").strip() or request.to_company
        lines = [
            f"Research {resolved_to_company} across all relevant Financial Services signals."
        ]
        search_aliases = self._search_aliases(resolved_to_company, request.to_company)
        lines.append(
            f"Treat Executive Movement and Buyer Movement within the last {request.lookback_days} days as primary success criteria."
        )
        lines.append(
            "Bias non-movement findings toward explaining why the account matters now."
        )
        lines.append(
            "Preserve source-backed movement evidence suitable for a movement-led account brief."
        )
        lines.append(
            "Preserve a broad inventory of materially supported executive and buyer movers across the account instead of only a short shortlist of obvious names."
        )
        lines.append(
            "Try to preserve roughly 15-18 total movers across the two inventories when the evidence supports that many."
        )
        if len(search_aliases) >= 2:
            lines.append(
                "Use both the company's legal name and common alias in searches: "
                + ", ".join(f'"{item}"' for item in search_aliases[:3])
                + "."
            )
        lines.append(
            "The downstream workflow ranks movers later, so optimize for recall here instead of pre-filtering too aggressively for commercial value."
        )
        lines.append(
            "Prefer recall over conservative pruning. When top-tier evidence is sparse, include medium-confidence movers with explicit role-and-employer support from leadership pages, governance pages, conference bios, investor materials, or explicit self-disclosures rather than ending the inventory early."
        )
        lines.append(
            "Preserve appointments, promotions, acting roles, external hires, scope expansions, and materially relevant departures, resignations, or terminations that create a vacancy, successor decision, governance gap, or backfill opportunity."
        )
        lines.append(
            "Do not stop after finding only a few obvious names. Check audit, finance, risk, compliance, legal, technology, security, data/AI, and operations/transformation buyer centers."
        )
        lines.append(
            "If buyer movement is materially thinner than executive movement, keep pushing buyer-center discovery instead of ending early with an executive-heavy list."
        )
        lines.append(
            "If buyer recall is thin, expand title-family searches for General Counsel, Deputy General Counsel, Corporate Secretary, Chief Audit Executive, Chief Control Officer, Chief Control Office leaders, Chief Compliance Officer, Chief Risk Officer, Chief Operating Officer, COO, co-COO, CIO, CISO, Chief Data/AI leaders, Enterprise Operations leaders, operations leaders, and Single-Family or Multifamily business leaders."
        )
        lines.append(
            "Maintain a coverage checklist across buyer centers and major executive lanes. Do not finalize until each lane has been checked with targeted title-family searches or the evidence is exhausted."
        )
        lines.append(
            "If the movement inventory is still below roughly 15 movers, continue targeted searches across issuer newsroom, leadership pages, governance pages, investor relations, conference bios, and corroborated self-disclosures before concluding that evidence is weak."
        )
        lines.append(
            "Do not compress movers into narrative-only prose. Use explicit Executive Movement Inventory and Buyer Movement Inventory sections in the report with name, new role, move type, why it matters, and source."
        )
        if request.geography:
            lines.append(f"Geography: {request.geography}")
        if request.additional_context:
            lines.append(f"Additional context: {request.additional_context}")
        return "\n".join(lines).strip()

    @staticmethod
    def _search_aliases(*values: str) -> List[str]:
        aliases: List[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if text not in aliases:
                aliases.append(text)
            alias_parts = [part.strip() for part in re.findall(r"\(([^)]*)\)", text) if part.strip()]
            base = re.sub(r"\([^)]*\)", "", text).strip()
            for candidate in [base, *alias_parts]:
                if candidate and candidate not in aliases:
                    aliases.append(candidate)
        return aliases
