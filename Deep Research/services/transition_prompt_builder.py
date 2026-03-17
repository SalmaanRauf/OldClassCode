"""
Prompt composition for Transition Playbook Deep Research runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from models.transition_schemas import TransitionPreflight
from services.prompt_loader import PromptLoader


TRANSITION_OVERLAY = """

## Transition Playbook Overlay
- This research run supports an executive transition workflow rather than a generic company briefing.
- Prioritize role-relevant opportunities, timing, warm-path credibility, and Protiviti fit.
- Emphasize "why now" and likely executive priorities tied to the destination role.
- Treat any synthetic scenario as a hypothetical planning scenario, not as a verified public fact.
- Surface opportunities that can be supported with internal credentials and relationship context.
""".strip()


@dataclass
class TransitionPromptPackage:
    industry_key: str
    system_prompt: str
    user_prompt: str


class TransitionPromptBuilder:
    """Compose Deep Research prompts for transition scenarios."""

    def __init__(self, prompt_loader: PromptLoader | None = None) -> None:
        self.prompt_loader = prompt_loader or PromptLoader()

    def build(self, preflight: TransitionPreflight) -> TransitionPromptPackage:
        industry_key = self._select_industry(preflight)
        base_prompt = self.prompt_loader.load_prompt(industry_key)
        system_prompt = f"{base_prompt}\n\n{TRANSITION_OVERLAY}"
        user_prompt = self._build_user_prompt(preflight)
        return TransitionPromptPackage(
            industry_key=industry_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def _select_industry(self, preflight: TransitionPreflight) -> str:
        candidates = [
            preflight.request.industry_override,
            preflight.inferred_industry,
            "general",
        ]
        for candidate in candidates:
            if candidate is None or str(candidate).strip() == "":
                continue
            resolved = self.prompt_loader.resolve_industry_key(candidate)
            if resolved:
                return resolved
        return "general"

    def _build_user_prompt(self, preflight: TransitionPreflight) -> str:
        request = preflight.request
        lines: List[str] = []

        if request.synthetic_scenario:
            lines.append(
                "This is a hypothetical planning scenario for demo purposes, not a verified public executive move."
            )

        lines.extend(
            [
                f"Person: {request.person_name}",
                f"Transition: {request.from_company} -> {request.to_company}",
                f"Target role: {request.new_role}",
                f"Person match status: {preflight.person_resolution.match_status}",
                f"Warm intro path available: {'yes' if preflight.quick_indicators.warm_intro_path_available else 'no'}",
                f"Prior work at source account: {'yes' if preflight.quick_indicators.source_worked_before else 'no'}",
                f"Prior work at destination account: {'yes' if preflight.quick_indicators.destination_worked_before else 'no'}",
            ]
        )

        if preflight.suggested_research_prompt:
            lines.extend(
                [
                    "",
                    "Research objective:",
                    preflight.suggested_research_prompt,
                ]
            )

        if preflight.opportunity_hypotheses:
            lines.append("")
            lines.append("Top opportunity hypotheses to investigate:")
            for hypothesis in preflight.opportunity_hypotheses:
                lines.append(
                    f"- {hypothesis.title} ({hypothesis.confidence}): {hypothesis.rationale}"
                )

        if request.additional_context:
            lines.extend(
                [
                    "",
                    "Additional context:",
                    request.additional_context,
                ]
            )

        return "\n".join(lines).strip()
