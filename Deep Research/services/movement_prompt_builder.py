"""
Prompt composition for the named-move People Movement Brief workflow.
"""
from __future__ import annotations

from dataclasses import dataclass

from models.movement_schemas import MovementBriefRequest
from models.transition_schemas import TransitionPreflight
from services.prompt_loader import PromptLoader


NAMED_MOVE_OVERLAY = """
## Named-Move People Movement Overlay
- This research run supports a named-move people movement workflow, not a generic company briefing.
- Keep the research broad across requested Financial Services signals, but prioritize executive movement and buyer movement.
- Use the named move as the anchor for why-now analysis and search the requested lookback window for related movement.
- Bias findings toward signals that explain why the move matters now, while preserving broader account-signal coverage.
- Treat synthetic scenarios as hypothetical planning scenarios, not as verified public facts.
- The final cover artifact is movement-led, so preserve source-backed movement evidence that can later feed the leverage table.
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
        summary = (
            f"{request.person_name} has moved from {request.from_company} to {request.to_company}, "
            f"with a new role as {request.new_role}."
        )
        lines = [summary]
        lines.append(
            f"Source all relevant information and find executive and buyer movement within the last {request.lookback_days} days."
        )
        lines.append(
            "Keep all relevant Financial Services signals in scope, but bias the research toward executive movement, buyer movement, and why the move matters now."
        )
        if request.synthetic_scenario:
            lines.append(
                "Treat this as a hypothetical planning scenario for demo purposes, not a verified public executive move."
            )
        lines.extend(
            [
                f"Named mover match status: {preflight.person_resolution.match_status}",
                f"Warm intro path available: {'yes' if preflight.quick_indicators.warm_intro_path_available else 'no'}",
                f"Prior work at source account: {'yes' if preflight.quick_indicators.source_worked_before else 'no'}",
                f"Prior work at destination account: {'yes' if preflight.quick_indicators.destination_worked_before else 'no'}",
            ]
        )
        if preflight.opportunity_hypotheses:
            lines.append("Top hypotheses to investigate:")
            for hypothesis in preflight.opportunity_hypotheses[:3]:
                lines.append(f"- {hypothesis.title} ({hypothesis.confidence}): {hypothesis.rationale}")
        if request.geography:
            lines.append(f"Geography: {request.geography}")
        if request.additional_context:
            lines.append(f"Additional context: {request.additional_context}")
        return "\n".join(lines).strip()
