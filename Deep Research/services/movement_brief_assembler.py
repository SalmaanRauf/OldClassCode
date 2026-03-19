"""
Deterministic assembly for the people movement brief.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger, SignalEvidence
from models.movement_schemas import (
    MovementAction,
    MovementBrief,
    MovementCredentialsProof,
    MovementLeverageSummary,
    MovementRecord,
)


@dataclass(frozen=True)
class MovementBriefAssemblyInput:
    """Input bundle for deterministic movement brief assembly."""

    trigger: BDTrigger
    signal_evidence: List[SignalEvidence]
    movement_rows: List[MovementRecord]
    ranked_rows: List[Dict[str, Any]]
    deep_enriched_rows: List[Dict[str, Any]]
    credential_packets: Dict[str, MovementCredentialsProof]
    deep_research_summary: str = ""


class MovementBriefAssembler:
    """Build the final movement brief without invoking a synthesis model."""

    def assemble(
        self,
        *,
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        movement_rows: Optional[List[MovementRecord]] = None,
        ranked_rows: List[Dict[str, Any]],
        deep_enriched_rows: List[Dict[str, Any]],
        credential_packets: Dict[str, MovementCredentialsProof],
        deep_research_summary: str = "",
    ) -> MovementBrief:
        ordered_rows = self._order_ranked_rows(ranked_rows)
        visible_rows = [
            self._attach_enrichment(item, credential_packets)
            for item in ordered_rows[:10]
        ]
        signal_summary = self._build_signal_summary(trigger, signal_evidence, deep_research_summary)
        where_to_act = self._build_actions(trigger, ordered_rows)
        executive_summary = self._build_executive_summary(
            trigger=trigger,
            signal_evidence=signal_evidence,
            visible_rows=visible_rows,
            deep_enriched_rows=deep_enriched_rows,
            credential_packets=credential_packets,
            deep_research_summary=deep_research_summary,
            where_to_act=where_to_act,
        )
        takeaway = self._build_takeaway(trigger, visible_rows, signal_summary, where_to_act)

        return MovementBrief(
            executive_summary=executive_summary,
            signal_summary=signal_summary,
            movement_rows=visible_rows,
            where_to_act=where_to_act,
            takeaway=takeaway,
        )

    def _order_ranked_rows(self, ranked_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not ranked_rows:
            return []
        if any("rank_score" in item for item in ranked_rows):
            return sorted(ranked_rows, key=lambda item: float(item.get("rank_score") or 0.0), reverse=True)
        return list(ranked_rows)

    def _attach_enrichment(
        self,
        row: Dict[str, Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> MovementRecord:
        movement = row["movement"]
        leverage = MovementLeverageSummary(
            known=bool(row.get("known")),
            worked_with=bool(row.get("worked_with")),
            project_count=int(row.get("project_count") or 0),
            win_count=int(row.get("win_count") or 0),
            relationship_owner=row.get("relationship_owner"),
            person_match_status=row.get("person_match_status"),
        )
        proof = credential_packets.get(movement.person_name)
        updates = {
            "leverage": leverage,
            "credentials_proof": proof,
        }
        return self._copy_model(movement, **updates)

    def _build_signal_summary(
        self,
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        deep_research_summary: str,
    ) -> List[str]:
        confirmed = [item for item in signal_evidence if item.status == "Confirmed"]
        summary: List[str] = []

        if confirmed:
            labels = ", ".join(item.signal_label for item in confirmed[:3])
            summary.append(f"Confirmed signals: {labels}.")
        else:
            summary.append(
                f"No confirmed signals were extracted for {trigger.company_focus or trigger.sector}."
            )

        if deep_research_summary.strip():
            summary.append(deep_research_summary.strip())

        return summary[:2]

    def _build_actions(
        self,
        trigger: BDTrigger,
        ranked_rows: List[Dict[str, Any]],
    ) -> List[MovementAction]:
        actions: List[MovementAction] = []
        for item in ranked_rows[:3]:
            actions.append(self._build_action_from_row(item))

        while len(actions) < 3:
            actions.append(
                MovementAction(
                    action_posture="Monitor",
                    person_name=trigger.company_focus or trigger.sector,
                    likely_play=f"Monitor {trigger.company_focus or trigger.sector} movement signals.",
                    why_now="Coverage remains sparse enough to warrant watchful monitoring.",
                    relationship_owner=None,
                )
            )

        return actions[:3]

    def _build_action_from_row(self, row: Dict[str, Any]) -> MovementAction:
        movement: MovementRecord = row["movement"]
        posture = str(row.get("action_posture") or "Monitor")
        if posture not in {"Immediate Re-engagement", "Expansion Opportunity", "Monitor"}:
            posture = "Monitor"

        relationship_owner = self._row_relationship_owner(row)
        project_count = int(row.get("project_count") or 0)
        win_count = int(row.get("win_count") or 0)
        known = bool(row.get("known"))
        worked_with = bool(row.get("worked_with"))

        project_bits = []
        if project_count or win_count:
            project_bits.append(f"{project_count} projects")
            project_bits.append(f"{win_count} wins")
        project_suffix = f" ({', '.join(project_bits)})" if project_bits else ""

        if movement.category == "BUYER":
            likely_play = f"Buyer-led expansion around {movement.new_role.lower()}{project_suffix}."
        else:
            likely_play = f"Executive support around {movement.new_role.lower()}{project_suffix}."

        why_now = movement.evidence.evidence_quote
        if relationship_owner:
            why_now = f"{why_now} Relationship owner: {relationship_owner}."
        if known or worked_with:
            leverage_suffix = []
            if known:
                leverage_suffix.append("known relationship")
            if worked_with:
                leverage_suffix.append("delivery history")
            why_now = f"{why_now} Leverage: {', '.join(leverage_suffix)}."

        return MovementAction(
            action_posture=posture,  # type: ignore[arg-type]
            person_name=movement.person_name,
            likely_play=likely_play,
            why_now=why_now,
            relationship_owner=relationship_owner,
        )

    def _build_executive_summary(
        self,
        *,
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        visible_rows: List[MovementRecord],
        deep_enriched_rows: List[Dict[str, Any]],
        credential_packets: Dict[str, MovementCredentialsProof],
        deep_research_summary: str,
        where_to_act: List[MovementAction],
    ) -> str:
        confirmed = [item for item in signal_evidence if item.status == "Confirmed"]
        matched = [packet for packet in credential_packets.values() if packet.lookup_status == "Matched"]
        matched_summary = ", ".join(
            f"{name} ({len(packet.matched_credentials)} creds)"
            for name, packet in list(credential_packets.items())[:3]
            if packet.lookup_status == "Matched"
        ) or "None"
        if not deep_research_summary.strip():
            deep_research_summary = f"{trigger.company_focus or trigger.sector} people movement scan completed."

        lines = [
            "Deep Research Findings",
            f"- {deep_research_summary.strip()}",
            f"- Confirmed signals: {len(confirmed)} | Movement rows retained: {len(visible_rows)} | Deep-enriched rows: {len(deep_enriched_rows[:10])}",
            "",
            "Credentials Agent Findings",
            f"- Lookups executed: {len(credential_packets)} | Matched: {len(matched)} | No Match: {len(credential_packets) - len(matched)} | Lookup Failed: {len([packet for packet in credential_packets.values() if packet.lookup_status == 'Lookup Failed'])}",
            f"- Top matched credentials by opportunity: {matched_summary}",
            "",
            "Combined Report & Action Items",
        ]

        for action in where_to_act[:3]:
            suffix = f" ({action.relationship_owner})" if action.relationship_owner else ""
            lines.append(f"- {action.person_name}: {action.likely_play}{suffix}")

        return "\n".join(lines)

    def _build_takeaway(
        self,
        trigger: BDTrigger,
        visible_rows: List[MovementRecord],
        signal_summary: List[str],
        where_to_act: List[MovementAction],
    ) -> str:
        if visible_rows:
            lead = visible_rows[0]
            posture = where_to_act[0].action_posture if where_to_act else "Monitor"
            return (
                f"{trigger.company_focus or trigger.sector} shows active executive and buyer movement. "
                f"Lead with {lead.person_name} first, then work the remaining {len(visible_rows) - 1} visible movers "
                f"under a {posture.lower()} posture."
            )
        if signal_summary:
            return signal_summary[0]
        return f"{trigger.company_focus or trigger.sector} movement coverage is currently sparse."

    @staticmethod
    def _copy_model(model: MovementRecord, **updates: Any) -> MovementRecord:
        if hasattr(model, "model_copy"):
            return model.model_copy(update=updates)  # type: ignore[no-any-return]
        return model.copy(update=updates)  # type: ignore[attr-defined, no-any-return]

    @staticmethod
    def _row_relationship_owner(row: Dict[str, Any]) -> Optional[str]:
        owner = str(row.get("relationship_owner") or "").strip()
        return owner or None
