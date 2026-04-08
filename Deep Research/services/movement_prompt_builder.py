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
- This research run supports a movement-led account brief for the destination account, not a generic company briefing.
- Primary deliverables are Executive Movement and Buyer Movement within the requested lookback window.
- Secondary deliverable is a concise set of other account signals that explain why the account matters now.
- Preserve source-backed movement evidence that can later feed the leverage table.
- Optimize for recall on executive and buyer movers; the downstream workflow ranks later.
- Maintain a coverage checklist and do not finalize until major executive lanes and buyer centers have been checked or the evidence is exhausted.
- Preserve explicit Executive Movement Inventory and Buyer Movement Inventory sections in the final report.
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
        lines = [f"Build a movement-led account brief for {resolved_to_company}."]
        search_aliases = self._search_aliases(resolved_to_company, request.to_company)
        lines.extend(
            [
                "",
                "## Primary Deliverables",
                (
                    f"1. Executive Movement: identify materially supported executive movers within the last "
                    f"{request.lookback_days} days."
                ),
                (
                    f"2. Buyer Movement: identify materially supported buyer movers within the last "
                    f"{request.lookback_days} days."
                ),
                "Aim to preserve roughly 15-18 total movers across the two inventories when the evidence supports that many.",
                "",
                "## Secondary Deliverable",
                "Identify a concise set of other account signals that explain why the account matters now. These signals are secondary to Executive Movement and Buyer Movement.",
                "",
                "## Search Procedure",
                "Focus the run on the destination account and the requested lookback window.",
                "Optimize for recall on executive and buyer movers; the downstream workflow ranks later.",
                "Preserve appointments, promotions, acting roles, external hires, scope expansions, and materially relevant departures, resignations, or terminations that create a vacancy, successor decision, governance gap, or backfill opportunity.",
                "Return only individual people as movers. Never include companies, partnerships, products, programs, or transactions as movers.",
                "First complete major executive-lane coverage, then complete buyer-center coverage before concluding the movement search.",
                "If buyer movement is materially thinner than executive movement, keep pushing buyer-center discovery instead of ending early with an executive-heavy list.",
                "Use title-family search expansion when buyer recall is thin. Explicitly search for General Counsel, Deputy General Counsel, Corporate Secretary, Chief Audit Executive, Chief Control Officer, Chief Control Office leaders, Head of Enterprise Operations, Chief Compliance Officer, Chief Risk Officer, Chief Operating Officer, COO, co-COO, CIO, CISO, Chief Data/AI leaders, Enterprise Operations leaders, operations leaders, and Single-Family or Multifamily business leaders.",
                "Maintain a coverage checklist across buyer centers and major executive lanes. Do not finalize until each lane has been checked with targeted title-family searches or the evidence is exhausted.",
                "If the movement inventory is still below roughly 15 movers, continue targeted searches across issuer newsroom, leadership pages, governance pages, investor relations, conference bios, and corroborated self-disclosures before concluding that evidence is weak.",
            ]
        )
        if len(search_aliases) >= 2:
            lines.append(
                "Use both the company's legal name and common alias in searches: "
                + ", ".join(f'"{item}"' for item in search_aliases[:3])
                + "."
            )
        lines.extend(
            [
                "",
                "## Required Output",
                "Use explicit Executive Movement Inventory and Buyer Movement Inventory sections in the report with name, new role, move type, why it matters, and source.",
                "After the movement inventories, include a concise set of other account signals that explain why the account matters now.",
            ]
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
