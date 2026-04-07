"""
Deterministic assembly for the people movement brief.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional

from models.bd_schemas import BDTrigger, SignalEvidence
from models.movement_schemas import (
    MovementBriefRequest,
    MovementAction,
    MovementBrief,
    MovementCredentialsProof,
    MovementLeverageSummary,
    MovementRecord,
)
from models.transition_schemas import TransitionPreflight


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
        request: Optional[MovementBriefRequest] = None,
        preflight: Optional[TransitionPreflight] = None,
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        movement_rows: Optional[List[MovementRecord]] = None,
        ranked_rows: List[Dict[str, Any]],
        deep_enriched_rows: List[Dict[str, Any]],
        credential_packets: Dict[str, MovementCredentialsProof],
        deep_research_summary: str = "",
        derived_opportunities: Optional[List[Any]] = None,
        credentials_lookup: Optional[Any] = None,
    ) -> MovementBrief:
        ordered_rows = self._dedupe_ranked_rows(self._order_ranked_rows(ranked_rows))
        visible_rows = [
            self._attach_enrichment(item, credential_packets)
            for item in ordered_rows
        ]
        signal_summary = self._build_signal_summary(trigger, signal_evidence, deep_research_summary)
        where_to_act = self._build_actions(trigger, ordered_rows, credential_packets)
        executive_summary = self._build_executive_summary(
            request=request,
            preflight=preflight,
            trigger=trigger,
            signal_evidence=signal_evidence,
            visible_rows=visible_rows,
            deep_enriched_rows=deep_enriched_rows,
            credential_packets=credential_packets,
            deep_research_summary=deep_research_summary,
            where_to_act=where_to_act,
            derived_opportunities=derived_opportunities or [],
            credentials_lookup=credentials_lookup,
        )
        takeaway = self._build_takeaway(trigger, visible_rows, signal_summary, where_to_act)

        return MovementBrief(
            executive_summary=executive_summary,
            signal_summary=signal_summary,
            movement_rows=visible_rows,
            where_to_act=where_to_act,
            takeaway=takeaway,
        )

    def apply_synthesis(self, brief: MovementBrief, synthesis: Any) -> MovementBrief:
        """Overlay bounded synthesis on the compact cover fields only."""
        move_summary = self._normalized_text(getattr(synthesis, "move_summary", "") or "")
        signal_summary = [
            self._normalized_text(item)
            for item in list(getattr(synthesis, "signal_summary", []) or [])
            if self._normalized_text(item)
        ]
        takeaway = self._normalized_text(getattr(synthesis, "takeaway", "") or "")

        return self._copy_model(
            brief,
            executive_summary=move_summary or brief.executive_summary,
            signal_summary=signal_summary[:3] or brief.signal_summary,
            takeaway=takeaway or brief.takeaway,
        )

    def _order_ranked_rows(self, ranked_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not ranked_rows:
            return []
        if any("rank_score" in item for item in ranked_rows):
            return sorted(ranked_rows, key=lambda item: float(item.get("rank_score") or 0.0), reverse=True)
        return list(ranked_rows)

    def _dedupe_ranked_rows(self, ranked_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not ranked_rows:
            return []

        unique_rows: List[Dict[str, Any]] = []
        seen_people: set[str] = set()
        for item in ranked_rows:
            movement = item.get("movement")
            person_key = self._normalized_person_key(getattr(movement, "person_name", ""))
            if not person_key or person_key in seen_people:
                continue
            seen_people.add(person_key)
            unique_rows.append(item)
        return unique_rows

    def _attach_enrichment(
        self,
        row: Dict[str, Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> MovementRecord:
        movement = row["movement"]
        opportunity_id = str(row.get("opportunity_id") or getattr(movement, "opportunity_id", "") or "").strip()
        leverage = MovementLeverageSummary(
            known=bool(row.get("known")),
            worked_with=bool(row.get("worked_with")),
            project_count=int(row.get("project_count") or 0),
            win_count=int(row.get("win_count") or 0),
            relationship_owner=row.get("relationship_owner"),
            person_match_status=row.get("person_match_status"),
        )
        proof = (
            credential_packets.get(opportunity_id)
            or credential_packets.get(movement.person_name)
            or credential_packets.get(str(getattr(movement, "title", "") or "").strip())
        )
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

        account_context = self._compact_deep_research_summary(deep_research_summary)
        if account_context:
            summary.append(f"Account context: {account_context}")

        return summary[:2]

    def _build_actions(
        self,
        trigger: BDTrigger,
        ranked_rows: List[Dict[str, Any]],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> List[MovementAction]:
        actions: List[MovementAction] = []
        action_rows = sorted(
            ranked_rows,
            key=lambda item: self._action_rank_score(item, credential_packets),
            reverse=True,
        )
        for item in action_rows[:3]:
            actions.append(self._build_action_from_row(item, credential_packets))

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

    def _build_action_from_row(
        self,
        row: Dict[str, Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> MovementAction:
        movement: MovementRecord = row["movement"]
        posture = str(row.get("action_posture") or "Monitor")
        if posture not in {"Immediate Re-engagement", "Expansion Opportunity", "Monitor"}:
            posture = "Monitor"

        relationship_owner = self._row_relationship_owner(row)
        project_count = int(row.get("project_count") or 0)
        win_count = int(row.get("win_count") or 0)
        known = bool(row.get("known"))
        worked_with = bool(row.get("worked_with"))
        proof = self._lookup_proof_packet(row, credential_packets)

        project_bits = []
        if project_count or win_count:
            project_bits.append(f"{project_count} current projects")
            project_bits.append(f"{win_count} wins")
        project_suffix = f" ({', '.join(project_bits)})" if project_bits else ""

        likely_play = self._build_likely_play(
            movement,
            project_suffix,
            buyer=(movement.category == "BUYER"),
        )

        why_now = movement.evidence.evidence_quote
        if relationship_owner:
            why_now = f"{why_now} Relationship owner: {relationship_owner}."
        if known or worked_with:
            leverage_suffix = []
            if known:
                leverage_suffix.append("known in ProConnect")
            if worked_with:
                leverage_suffix.append("delivery history")
            why_now = f"{why_now} Leverage: {', '.join(leverage_suffix)}."
        if proof and proof.lookup_status == "Matched" and proof.summary:
            why_now = f"{why_now} Credential proof: {proof.summary}"
        elif proof and proof.lookup_status == "Lookup Failed" and proof.summary:
            why_now = f"{why_now} Credential lookup warning: {proof.summary}"

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
        request: Optional[MovementBriefRequest],
        preflight: Optional[TransitionPreflight],
        trigger: BDTrigger,
        signal_evidence: List[SignalEvidence],
        visible_rows: List[MovementRecord],
        deep_enriched_rows: List[Dict[str, Any]],
        credential_packets: Dict[str, MovementCredentialsProof],
        deep_research_summary: str,
        where_to_act: List[MovementAction],
        derived_opportunities: List[Any],
        credentials_lookup: Optional[Any],
    ) -> str:
        confirmed = [item for item in signal_evidence if item.status == "Confirmed"]
        lead = visible_rows[0].person_name if visible_rows else (request.person_name if request else trigger.company_focus or trigger.sector)
        from_company = preflight.from_account.company_name if preflight else (request.from_company if request else "the source account")
        to_company = preflight.to_account.company_name if preflight else (request.to_company if request else trigger.company_focus or "the destination account")
        new_role = request.new_role if request else "the new role"
        matched_count = len([packet for packet in credential_packets.values() if packet.lookup_status == "Matched"])
        action_hint = where_to_act[0].likely_play if where_to_act else "prioritize the strongest movement-led advisory opening"
        visible_count = len(visible_rows)
        signal_count = len(confirmed)
        prioritized_count = len(derived_opportunities)
        coverage_summary = (
            f"The cover brief retains {visible_count} visible mover{'' if visible_count == 1 else 's'}, "
            f"confirms {signal_count} supporting signal{'' if signal_count == 1 else 's'}, "
            f"and matched credentials for {matched_count} of {prioritized_count} prioritized "
            f"play{'' if prioritized_count == 1 else 's'}."
        )
        if not visible_rows:
            account_context = self._compact_deep_research_summary(deep_research_summary)
            context_line = f" Account context: {account_context}" if account_context else ""
            return (
                f"In this planning scenario, {request.person_name if request else lead} is moving from {from_company} to {to_company} as {new_role}. "
                f"Movement extraction returned no visible rows for the cover brief, so treat this run as degraded "
                f"and review the full research report and movement evidence artifacts before acting.{context_line}"
            )
        lead_in = (
            f"In this planning scenario, {request.person_name if request else lead} is moving from {from_company} to {to_company} as {new_role}. "
            if request and request.synthetic_scenario
            else f"{request.person_name if request else lead} moved from {from_company} to {to_company} as {new_role}. "
        )
        return (
            f"{lead_in}"
            f"{coverage_summary} "
            f"Start with {lead} and {action_hint.lower()}."
        )

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
            if posture == "Monitor":
                return (
                    f"{trigger.company_focus or trigger.sector} shows active executive and buyer movement. "
                    f"Keep {lead.person_name} at the top of the watchlist, then track the remaining {len(visible_rows) - 1} visible movers "
                    f"for role changes or warm-path openings."
                )
            return (
                f"{trigger.company_focus or trigger.sector} shows active executive and buyer movement. "
                f"Lead with {lead.person_name} first, then work the remaining {len(visible_rows) - 1} visible movers "
                f"under a {posture.lower()} posture."
            )
        if signal_summary:
            return signal_summary[0]
        return f"{trigger.company_focus or trigger.sector} movement coverage is currently sparse."

    @staticmethod
    def _compact_deep_research_summary(summary: str) -> str:
        text = str(summary or "").strip()
        if not text:
            return ""

        text = re.sub(r"(?is)^final report:\s*", "", text)
        text = re.sub(r"(?is)^executive summary:\s*", "", text)
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r"\s+", " ", text).strip()
        text = re.split(r"(?i)\bSources?:\b", text, maxsplit=1)[0].strip()
        text = re.sub(r"^#{1,6}\s*", "", text)
        text = re.sub(r"\s+#{1,6}\s+", " ", text)
        if not text:
            return ""

        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
        compact = sentences[0] if sentences else text
        if len(compact) > 220:
            compact = compact[:217].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
        return compact

    @staticmethod
    def _normalized_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    @classmethod
    def _normalized_person_key(cls, value: Any) -> str:
        text = cls._normalized_text(value).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _build_likely_play(
        movement: MovementRecord,
        project_suffix: str,
        *,
        buyer: bool,
    ) -> str:
        new_role = (movement.new_role or "").strip()
        previous_role = (movement.previous_role or "the prior role").strip()
        movement_type = (movement.movement_type or "").strip().lower()
        is_departure = (
            "depart" in movement_type
            or new_role.lower() in {"departed", "departure"}
            or "depart" in new_role.lower()
        )
        if is_departure:
            prefix = "Buyer transition coverage" if buyer else "Executive transition coverage"
            return f"{prefix} around {previous_role.lower()} departure{project_suffix}."
        if buyer:
            return f"Buyer-led expansion around {new_role.lower()}{project_suffix}."
        return f"Executive support around {new_role.lower()}{project_suffix}."

    def _action_rank_score(
        self,
        row: Dict[str, Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> float:
        score = float(row.get("rank_score") or 0.0)
        score += float(row.get("project_count") or 0) * 0.5
        score += float(row.get("win_count") or 0) * 1.5
        if row.get("known"):
            score += 3.0
        if row.get("worked_with"):
            score += 4.0
        proof = self._lookup_proof_packet(row, credential_packets)
        if proof:
            if proof.lookup_status == "Matched":
                score += 15.0 + (len(proof.matched_credentials or []) * 2.0)
            elif proof.lookup_status == "Lookup Failed":
                score -= 2.0
        return score

    def _lookup_proof_packet(
        self,
        row: Dict[str, Any],
        credential_packets: Dict[str, MovementCredentialsProof],
    ) -> Optional[MovementCredentialsProof]:
        movement: MovementRecord = row["movement"]
        opportunity_id = str(row.get("opportunity_id") or getattr(movement, "opportunity_id", "") or "").strip()
        return (
            credential_packets.get(opportunity_id)
            or credential_packets.get(movement.person_name)
            or credential_packets.get(str(getattr(movement, "title", "") or "").strip())
        )

    @staticmethod
    def _copy_model(model: MovementRecord, **updates: Any) -> MovementRecord:
        if hasattr(model, "model_copy"):
            return model.model_copy(update=updates)  # type: ignore[no-any-return]
        return model.copy(update=updates)  # type: ignore[attr-defined, no-any-return]

    @staticmethod
    def _row_relationship_owner(row: Dict[str, Any]) -> Optional[str]:
        owner = str(row.get("relationship_owner") or "").strip()
        return owner or None
