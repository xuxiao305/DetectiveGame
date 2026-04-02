"""Prompt composing layer for detective and suspect role generation."""

from __future__ import annotations

import re
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
        cd = context.case_data
        return {
            "role": "detective",
            "case_name": cd.case_name,
            "background": cd.background,
            "character_name": cd.detective_name,
            "character_known": " | ".join(cd.detective_known),
            "goal": base_goal,
            "forced_constraint": forced,
            "history": " | ".join(context.recent_turn_summaries[-3:]) or "无",
            "round": str(context.round_index),
        }

    def build_suspect_prompt(
        self,
        context: PromptContext,
        detective_question: str = "",
    ) -> Dict[str, str]:
        cd = context.case_data
        known_parts = list(cd.suspect_lie)
        if context.contradiction_count >= 2:
            known_parts.extend(cd.suspect_truth)
        return {
            "role": "suspect",
            "case_name": cd.case_name,
            "background": cd.background,
            "character_name": cd.suspect_name,
            "character_known": " | ".join(known_parts),
            "goal": "保持防御叙述，不主动完整认罪。",
            "confession_boundary": "允许阶段性松口，但禁止直接承认致死行为。",
            "pressure": str(context.contradiction_count),
            "detective_question": detective_question,
            "history": " | ".join(context.recent_turn_summaries[-2:]) or "无",
            "round": str(context.round_index),
        }


_SUMMARY_MAX_CHARS = 60


def _truncate(text: str, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """Keep the first max_chars characters to limit context growth."""
    text = text.strip()
    # Strip nested history reference prefixes that cause recursive bloat.
    text = re.sub(r'^(\|?\s*R\d+:侦探问\[|\|?\s*嫌疑人答\[)+', '', text).strip('[]| ')
    # Strip residual </think> tags and leading meta text.
    text = re.sub(r'^</think>\s*', '', text, flags=re.IGNORECASE).strip()
    return text[:max_chars] + "…" if len(text) > max_chars else text


def build_context(state: GameState, pending_evidence_text: Optional[str]) -> PromptContext:
    summaries = [
        f"R{turn.round_index}:侦探问[{_truncate(turn.detective_question)}] 嫌疑人答[{_truncate(turn.suspect_answer)}]"
        for turn in state.turns
    ]
    return PromptContext(
        round_index=state.round_index + 1,
        case_data=state.case_data,
        recent_turn_summaries=summaries,
        pending_evidence_text=pending_evidence_text,
        contradiction_count=len(state.contradictions),
    )
