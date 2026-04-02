"""Session export for final transcript and summary lists."""

from __future__ import annotations

from .models import GameState


class TranscriptExporter:
    def export_session(self, state: GameState) -> str:
        lines = []
        lines.append(f"《审讯室》MVP 会话记录 | Session: {state.session_id}")
        lines.append(f"总回合数：{state.round_index}")
        lines.append("")
        lines.append("=== 对话记录 ===")
        for turn in state.turns:
            lines.append(f"\n[第 {turn.round_index} 回合]")
            lines.append(f"侦探内心：{turn.detective_thought}")
            lines.append(f"侦探发问：{turn.detective_question}")
            lines.append(f"嫌疑人内心：{turn.suspect_thought}")
            lines.append(f"嫌疑人回答：{turn.suspect_answer}")
            if turn.new_contradictions:
                for desc in turn.new_contradictions:
                    lines.append(f"⚠️ 矛盾点：{desc}")

        lines.append("\n=== 矛盾点汇总（去重）===")
        if not state.contradictions:
            lines.append("无")
        else:
            for item in state.contradictions:
                rounds = ",".join(str(i) for i in sorted(item.related_round_indexes))
                lines.append(
                    f"- [{item.category}/{item.severity}] {item.description} (回合: {rounds})"
                )

        lines.append("\n=== 使用证据 ===")
        if not state.used_evidence_ids:
            lines.append("无")
        else:
            evidence_map = {item.evidence_id: item for item in state.case_data.evidence_items}
            for evidence_id in state.used_evidence_ids:
                item = evidence_map.get(evidence_id)
                if item:
                    lines.append(f"- {item.title}：{item.content}")

        return "\n".join(lines)
