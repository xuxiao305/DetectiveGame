"""Evidence injection handling for fixed evidence list."""

from __future__ import annotations

from .models import GameState


class EvidenceInjectionHandler:
    def inject(self, state: GameState, evidence_id: str) -> None:
        if evidence_id in state.used_evidence_ids or evidence_id in state.pending_evidence_ids:
            raise ValueError("该证据已使用或已在待注入队列中。")
        all_ids = {item.evidence_id for item in state.case_data.evidence_items}
        if evidence_id not in all_ids:
            raise ValueError("无效证据ID。")
        state.pending_evidence_ids.append(evidence_id)

    def consume_next_pending(self, state: GameState) -> str | None:
        if not state.pending_evidence_ids:
            return None
        evidence_id = state.pending_evidence_ids.pop(0)
        if evidence_id not in state.used_evidence_ids:
            state.used_evidence_ids.append(evidence_id)
        return evidence_id


def find_evidence_text(state: GameState, evidence_id: str | None) -> str | None:
    if not evidence_id:
        return None
    for item in state.case_data.evidence_items:
        if item.evidence_id == evidence_id:
            return f"{item.title}：{item.content}"
    return None
