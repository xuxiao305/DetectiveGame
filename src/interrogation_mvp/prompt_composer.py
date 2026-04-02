"""Prompt composing layer for detective and suspect role generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .models import CaseData, GameState


@dataclass
class PromptContext:
    round_index: int
    case_data: CaseData
    recent_turn_summaries: List[str]
    pending_evidence_text: Optional[str]
    contradiction_count: int


class PromptComposer:
    def build_detective_prompt(self, context: PromptContext) -> Dict[str, str]:
        base_goal = "围绕时间线、地点、动机、证据推进追问。"
        forced = ""
        if context.pending_evidence_text:
            forced = f"本轮必须引用新证据：{context.pending_evidence_text}"
        return {
            "role": "detective",
            "goal": base_goal,
            "forced_constraint": forced,
            "history": " | ".join(context.recent_turn_summaries[-3:]) or "无",
            "round": str(context.round_index),
        }

    def build_suspect_prompt(self, context: PromptContext) -> Dict[str, str]:
        return {
            "role": "suspect",
            "goal": "保持防御叙述，不主动完整认罪。",
            "confession_boundary": "允许阶段性松口，但禁止直接承认致死行为。",
            "pressure": str(context.contradiction_count),
            "round": str(context.round_index),
        }


def build_context(state: GameState, pending_evidence_text: Optional[str]) -> PromptContext:
    summaries = [
        f"R{turn.round_index}:侦探问[{turn.detective_question}] 嫌疑人答[{turn.suspect_answer}]"
        for turn in state.turns
    ]
    return PromptContext(
        round_index=state.round_index + 1,
        case_data=state.case_data,
        recent_turn_summaries=summaries,
        pending_evidence_text=pending_evidence_text,
        contradiction_count=len(state.contradictions),
    )
