"""
Deterministic derivation of financial-services opportunities from confirmed signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from models.bd_schemas import BDTrigger, PhaseOpportunity, SignalEvidence


@dataclass(frozen=True)
class _OpportunityTemplate:
    overview: str
    technical_explanation: str
    layman_explanation: str
    service_lines: List[str]
    actions: List[str]


class FSOpportunityDeriver:
    """Maps confirmed FS signals to deterministic phase opportunities."""

    PRIORITY = {
        "FS.CONSUMER.LITIGATION_SETTLEMENT": 100,
        "FS.REGULATORY.DEADLINE": 95,
        "FS.EXEC.TRANSITION": 90,
        "FS.AML.BSA_FINDINGS": 85,
        "FS.MODEL_RISK.FINDINGS": 80,
        "FS.STRESS_TEST.ISSUES": 75,
        "FS.CECL.IMPLEMENTATION": 70,
    }

    TEMPLATES: Dict[str, _OpportunityTemplate] = {
        "FS.CONSUMER.LITIGATION_SETTLEMENT": _OpportunityTemplate(
            overview=(
                "Consumer remediation obligations appear to be in execution mode, creating demand for "
                "governance over eligibility logic, payout controls, and remediation reporting."
            ),
            technical_explanation=(
                "Settlement execution requires traceable calculation logic, source-to-report data lineage, "
                "exception handling controls, and defensible evidence packs for oversight."
            ),
            layman_explanation=(
                "The bank must prove it is paying the right customers the right amounts on time, and keep "
                "clear documentation in case regulators challenge the results."
            ),
            service_lines=[
                "Consumer remediation governance & controls advisory",
                "Data lineage and calculation controls assessment",
                "Independent testing / QA of remediation execution",
            ],
            actions=[
                "Stand up a remediation governance blueprint with evidence standards within the next 30-90 days.",
                "Pressure-test calculation logic and data lineage with independent sample-based testing within the next 30-90 days.",
                "Define remediation reporting cadence tied to settlement milestones within the next 30-90 days.",
            ],
        ),
        "FS.REGULATORY.DEADLINE": _OpportunityTemplate(
            overview=(
                "Formal regulatory deliverable timelines create near-term pressure on governance, document control, "
                "and evidence traceability."
            ),
            technical_explanation=(
                "Deadline-driven submissions require section-level ownership, version control, claim-to-source "
                "traceability, and pre-submission defensibility reviews."
            ),
            layman_explanation=(
                "Regulators want a high-quality plan on a strict schedule, so the work must be tightly managed "
                "with clear evidence and approvals."
            ),
            service_lines=[
                "Governance and documentation readiness advisory",
                "Control/evidence framework design for regulatory deliverables",
                "Independent quality review of planning artifacts",
            ],
            actions=[
                "Build an interim submission workplan mapped to accountable owners within the next 30-90 days.",
                "Implement an evidence traceability register (claim-source-owner-version) within the next 30-90 days.",
                "Run an independent defensibility review before filing milestones within the next 30-90 days.",
            ],
        ),
        "FS.EXEC.TRANSITION": _OpportunityTemplate(
            overview=(
                "Executive risk leadership transitions around strategic initiatives create governance-alignment "
                "opportunities at the operating model level."
            ),
            technical_explanation=(
                "Early alignment typically defines risk appetite articulation, first-line control expectations, "
                "oversight forums, and audit-ready decision documentation."
            ),
            layman_explanation=(
                "A new risk executive can set guardrails early so growth initiatives don’t require expensive control "
                "rework later."
            ),
            service_lines=[
                "Risk governance and operating model advisory",
                "Control framework design for new initiatives",
                "Readiness support for audit / oversight expectations",
            ],
            actions=[
                "Run a mandate-translation workshop for executive risk leadership within the next 30-90 days.",
                "Define operating model RACI and control standards for the initiative within the next 30-90 days.",
                "Establish initial governance metrics and evidence expectations within the next 30-90 days.",
            ],
        ),
        "FS.AML.BSA_FINDINGS": _OpportunityTemplate(
            overview=(
                "AML/BSA scrutiny indicates demand for program uplift, monitoring quality, and governance remediation."
            ),
            technical_explanation=(
                "Sustainable remediation requires control redesign, SAR quality governance, CDD process discipline, "
                "and independent effectiveness testing."
            ),
            layman_explanation=(
                "Banks must quickly improve financial-crime controls so issues do not become enforcement actions."
            ),
            service_lines=[
                "AML/BSA program transformation",
                "Transaction monitoring and investigation quality uplift",
                "Independent AML controls testing",
            ],
            actions=[
                "Prioritize AML control-gap triage and remediation sequencing within the next 30-90 days.",
                "Validate SAR/CDD process quality and exception handling within the next 30-90 days.",
                "Implement independent AML controls testing cadence within the next 30-90 days.",
            ],
        ),
        "FS.MODEL_RISK.FINDINGS": _OpportunityTemplate(
            overview=(
                "Model risk expectations support opportunity for independent validation and governance hardening."
            ),
            technical_explanation=(
                "Programs should align model inventory, validation standards, challenger methodology, and "
                "governance escalation under SR 11-7 expectations."
            ),
            layman_explanation=(
                "The organization needs stronger checks to prove models are reliable, explainable, and compliant."
            ),
            service_lines=[
                "Model risk governance advisory",
                "Independent model validation and challenge",
                "MRM process and documentation uplift",
            ],
            actions=[
                "Refresh model inventory and risk-tiering governance within the next 30-90 days.",
                "Run independent validation on priority models within the next 30-90 days.",
                "Strengthen model governance committee reporting within the next 30-90 days.",
            ],
        ),
        "FS.STRESS_TEST.ISSUES": _OpportunityTemplate(
            overview=(
                "Stress-testing methodology and capital-planning volatility create demand for scenario and model assurance."
            ),
            technical_explanation=(
                "Opportunity centers on methodology review, scenario governance, and capital-planning narrative "
                "consistency across internal and supervisory expectations."
            ),
            layman_explanation=(
                "Banks need stronger stress-testing discipline to avoid surprises in capital requirements."
            ),
            service_lines=[
                "CCAR/DFAST scenario and methodology advisory",
                "Stress-testing governance and controls",
                "Capital planning readiness support",
            ],
            actions=[
                "Perform stress-testing methodology review against latest guidance within the next 30-90 days.",
                "Tighten scenario governance and model-change controls within the next 30-90 days.",
                "Align capital-planning narrative and evidence packs within the next 30-90 days.",
            ],
        ),
        "FS.CECL.IMPLEMENTATION": _OpportunityTemplate(
            overview=(
                "CECL operating-model changes create opportunity for governance, model calibration, and M&A readiness."
            ),
            technical_explanation=(
                "Priority needs include allowance model performance monitoring, documentation rigor, and impact "
                "analysis for portfolio or acquisition scenarios."
            ),
            layman_explanation=(
                "The bank can improve credit-loss forecasting quality while preparing for strategic balance-sheet changes."
            ),
            service_lines=[
                "CECL model governance and optimization",
                "Allowance process and control uplift",
                "M&A accounting impact readiness",
            ],
            actions=[
                "Assess CECL model performance drift and governance controls within the next 30-90 days.",
                "Strengthen allowance documentation and control evidence within the next 30-90 days.",
                "Evaluate CECL implications for strategic portfolio actions within the next 30-90 days.",
            ],
        ),
    }

    def derive(
        self,
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        max_opportunities: int = 3,
    ) -> List[PhaseOpportunity]:
        confirmed = [item for item in signal_evidence if item.status == "Confirmed"]
        requested_codes = [code for code in trigger.signals if code.startswith("FS.")]
        requested_is_single = len(requested_codes) == 1
        requested_code = requested_codes[0] if requested_is_single else None

        if requested_is_single:
            confirmed_for_requested = [item for item in confirmed if item.signal_code == requested_code]
            if confirmed_for_requested:
                return [self._build_phase_opportunity(confirmed_for_requested[0])]
            return [
                PhaseOpportunity(
                    derived_from_signal=requested_code or "FS.UNKNOWN",
                    overview="Requested signal did not meet confirmed evidence threshold in this run.",
                    technical_explanation=(
                        "Available evidence was insufficient after deterministic source and confidence checks."
                    ),
                    layman_explanation=(
                        "There is not enough reliable public evidence yet to treat this as a confirmed opportunity."
                    ),
                    relevant_service_lines=[],
                    credentials_summary="No materially aligned credentials identified.",
                    recommended_actions=[
                        "Monitor this signal and re-validate when stronger evidence appears within the next 30-90 days."
                    ],
                    sources=[],
                )
            ]

        ranked = sorted(
            confirmed,
            key=lambda item: self.PRIORITY.get(item.signal_code, 0),
            reverse=True,
        )
        opportunities = [self._build_phase_opportunity(item) for item in ranked[:max_opportunities]]
        return opportunities

    def _build_phase_opportunity(self, evidence: SignalEvidence) -> PhaseOpportunity:
        template = self.TEMPLATES.get(
            evidence.signal_code,
            _OpportunityTemplate(
                overview="Confirmed signal created a targeted client enablement opportunity.",
                technical_explanation="Use confirmed evidence to design governance and control uplift actions.",
                layman_explanation="A verified market signal points to near-term advisory demand.",
                service_lines=["Risk advisory"],
                actions=["Develop a targeted client enablement plan within the next 30-90 days."],
            ),
        )

        sources = [evidence.source_url] if evidence.source_url else []
        return PhaseOpportunity(
            derived_from_signal=evidence.signal_code,
            overview=template.overview,
            technical_explanation=template.technical_explanation,
            layman_explanation=template.layman_explanation,
            relevant_service_lines=list(template.service_lines),
            credentials_summary="No materially aligned credentials identified.",
            recommended_actions=list(template.actions),
            sources=sources,
        )

