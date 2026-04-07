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
- Aim to surface roughly the top 8-10 commercially relevant executive movers and the top 8-10 commercially relevant buyer movers when the evidence supports them. Do not pad the list if evidence is weak.
- Try to preserve roughly 15-18 total movers across the two inventories when the evidence supports that many, with a balanced mix of executive and buyer movement instead of a heavily one-sided list.
- Use both the destination account's legal name and common alias in searches whenever both exist.
- Prioritize active appointments, external hires, promotions, and scope-expansion moves over departures when deciding which movers deserve space in the final report.
- Keep materially relevant departures, resignations, and terminations when they create a vacancy, successor decision, governance gap, or backfill opportunity at the destination account, but sort them after active appointments/promotions when commercial value is comparable.
- Do not stop after finding only a few examples. Continue until the destination account has been checked across audit, finance, risk, compliance, legal, technology, security, data/AI, and operations/transformation buyer centers.
- Prefer a balanced movement inventory over an executive-heavy list. If buyer movement is materially thinner than executive movement, keep spending search effort on buyer-center discovery instead of padding the report with lower-value executive departures.
- Use title-family search expansion when buyer recall is thin. Explicitly search for and preserve moves involving General Counsel, Deputy General Counsel, Corporate Secretary, Chief Audit Executive, Chief Control Officer, Chief Compliance Officer, Chief Risk Officer, Chief Information Officer, Chief Information Security Officer, Chief Data/AI leaders, Enterprise Operations leaders, and Single-Family/Multifamily business leaders when they are tied to the destination account.
- Maintain a coverage checklist across the buyer centers and major executive lanes. Do not finalize the report until each lane has been checked with targeted title-family searches or the evidence is exhausted.
- If the movement inventory is still below roughly 15 movers, continue targeted searches across issuer newsroom, leadership pages, governance pages, investor relations, conference bios, and corroborated self-disclosures before concluding that evidence is weak.
- Preserve compact Executive Movement Inventory and Buyer Movement Inventory sections in the final report with one line per mover covering name, new role, move type, why it matters, and source.
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
            "Aim to identify roughly the top 8-10 high-value executive movers and the top 8-10 high-value buyer movers, but do not pad the list when evidence is weak."
        )
        lines.append(
            "Try to preserve roughly 15-18 total movers across the two inventories when the evidence supports that many, with a balanced mix of executive and buyer movement."
        )
        if len(search_aliases) >= 2:
            lines.append(
                "Use both the company's legal name and common alias in searches: "
                + ", ".join(f'"{item}"' for item in search_aliases[:3])
                + "."
            )
        lines.append(
            "Prioritize active appointments, external hires, promotions, and scope expansions over departures when deciding which movers deserve inclusion."
        )
        lines.append(
            "Keep materially relevant departures, resignations, and terminations when they create a vacancy, successor decision, governance gap, or backfill opportunity, but sort them after active appointments and promotions when commercial value is comparable."
        )
        lines.append(
            "Do not stop after finding only a few names. Check audit, finance, risk, compliance, legal, technology, security, data/AI, and operations/transformation buyer centers."
        )
        lines.append(
            "Prefer a balanced movement inventory over an executive-heavy list. If buyer movement is materially thinner than executive movement, keep pushing buyer-center discovery instead of padding with lower-value executive departures."
        )
        lines.append(
            "If buyer recall is thin, expand title-family searches for General Counsel, Deputy General Counsel, Corporate Secretary, Chief Audit Executive, Chief Control Officer, Chief Compliance Officer, Chief Risk Officer, CIO, CISO, Chief Data/AI leaders, Enterprise Operations leaders, and Single-Family or Multifamily business leaders."
        )
        lines.append(
            "Maintain a coverage checklist across buyer centers and major executive lanes. Do not finalize until each lane has been checked with targeted title-family searches or the evidence is exhausted."
        )
        lines.append(
            "If the movement inventory is still below roughly 15 movers, continue targeted searches across issuer newsroom, leadership pages, governance pages, investor relations, conference bios, and corroborated self-disclosures before concluding that evidence is weak."
        )
        lines.append(
            "Include compact Executive Movement Inventory and Buyer Movement Inventory sections in the report with name, new role, move type, why it matters, and source."
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
