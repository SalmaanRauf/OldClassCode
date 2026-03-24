"""
Prompt composition for the named-move People Movement Brief workflow.
"""
from __future__ import annotations

from dataclasses import dataclass

from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight
from services.prompt_loader import PromptLoader


NAMED_MOVE_OVERLAY = """
## People Movement Account Overlay
- This research run supports a movement-led account brief, not a generic company briefing.
- Keep the research broad across requested Financial Services signals, but prioritize executive movement and buyer movement.
- Focus research on the destination account and the requested lookback window.
- Bias findings toward signals that explain why the account matters now, while preserving broader account-signal coverage.
- Preserve source-backed movement evidence that can later feed the leverage table.
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
        lines.append(
            f"Prioritize Executive Movement and Buyer Movement within the last {request.lookback_days} days."
        )
        lines.append(
            "Bias non-movement findings toward explaining why the account matters now."
        )
        lines.append(
            "Preserve source-backed movement evidence suitable for a movement-led account brief."
        )
        if request.geography:
            lines.append(f"Geography: {request.geography}")
        if request.additional_context:
            lines.append(f"Additional context: {request.additional_context}")
        return "\n".join(lines).strip()
