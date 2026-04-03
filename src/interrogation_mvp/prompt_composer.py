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
    recent_turn_summaries: List[str]       # 嫌疑人视角历史
    detective_turn_summaries: List[str]    # 侦探视角历史
    pending_evidence_text: Optional[str]
    contradiction_count: int
    suspect_claims: List[str] = None  # type: ignore[assignment]
    detective_claims: List[str] = None  # type: ignore[assignment]
    suspect_pressure_summary: str = ""

    def __post_init__(self) -> None:
        if self.suspect_claims is None:
            self.suspect_claims = []
        if self.detective_claims is None:
            self.detective_claims = []


class PromptComposer:
    def build_detective_prompt(self, context: PromptContext) -> Dict[str, str]:
        base_goal = "围绕时间线、地点、动机、证据推进追问。"
        forced = ""
        if context.pending_evidence_text:
            forced = f"本轮必须引用新证据：{context.pending_evidence_text}"
        cd = context.case_data
        claims_text = "\n".join(context.suspect_claims) if context.suspect_claims else "暂无"
        detective_notes_text = "\n".join(context.detective_claims) if context.detective_claims else "暂无"
        return {
            "role": "detective",
            "case_name": cd.case_name,
            "background": cd.background,
            "character_name": cd.detective_name,
            "character_known": " | ".join(cd.detective_known),
            "goal": base_goal,
            "forced_constraint": forced,
            "suspect_claims": claims_text,
            "detective_notes": detective_notes_text,
            "history": " | ".join(context.detective_turn_summaries[-3:]) or "无",
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
        claims_text = "\n".join(context.suspect_claims) if context.suspect_claims else "暂无"
        goal = context.suspect_pressure_summary or "保持防御叙述，不主动完整认罪。"
        return {
            "role": "suspect",
            "case_name": cd.case_name,
            "background": cd.background,
            "character_name": cd.suspect_name,
            "character_known": " | ".join(known_parts),
            "goal": goal,
            "confession_boundary": "允许阶段性松口，但禁止直接承认致死行为。",
            "pressure": str(context.contradiction_count),
            "detective_question": detective_question,
            "my_previous_claims": claims_text,
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
    # 嫌疑人视角：我说了什么（保持说辞一致用）
    suspect_summaries = [
        f"R{turn.round_index}: 我说了——{_truncate(turn.suspect_answer)}"
        for turn in state.turns
    ]
    # 侦探视角：我问了什么，对方怎么回应（追问策略用）
    detective_summaries = [
        f"R{turn.round_index}: 我追问了[{_truncate(turn.detective_question)}] → 对方答[{_truncate(turn.suspect_answer)}]"
        for turn in state.turns
    ]
    # 优先从 RoleMemory 读取；为空时降级到即时提取（兼容旧数据）
    suspect_claims = list(state.suspect_memory.recent_claims)
    if not suspect_claims:
        suspect_claims = [
            f"R{turn.round_index}: {_truncate(turn.suspect_answer, max_chars=80)}"
            for turn in state.turns
            if turn.suspect_answer.strip()
        ]
    detective_claims = list(state.detective_memory.recent_claims)

    return PromptContext(
        round_index=state.round_index + 1,
        case_data=state.case_data,
        recent_turn_summaries=suspect_summaries,
        detective_turn_summaries=detective_summaries,
        pending_evidence_text=pending_evidence_text,
        contradiction_count=len(state.contradictions),
        suspect_claims=suspect_claims,
        detective_claims=detective_claims,
        suspect_pressure_summary=state.suspect_memory.summary,
    )
