"""Turn guardrails to enforce MVP behavior boundaries."""

from __future__ import annotations

from .llm_gateway import GeneratedRoleOutput


class TurnGuard:
    def apply(
        self,
        detective_output: GeneratedRoleOutput,
        suspect_output: GeneratedRoleOutput,
        pending_evidence_text: str | None,
    ) -> tuple[GeneratedRoleOutput, GeneratedRoleOutput]:
        detective_fixed = self._enforce_detective_progress(
            detective_output=detective_output,
            pending_evidence_text=pending_evidence_text,
        )
        suspect_fixed = self._enforce_confession_boundary(suspect_output)
        return detective_fixed, suspect_fixed

    def _enforce_detective_progress(
        self,
        detective_output: GeneratedRoleOutput,
        pending_evidence_text: str | None,
    ) -> GeneratedRoleOutput:
        if not pending_evidence_text:
            return detective_output
        if pending_evidence_text not in detective_output.speech:
            detective_output.speech = (
                f"{detective_output.speech} 另外，新证据显示：{pending_evidence_text}，"
                "请你正面解释。"
            )
            if "证据引用" not in detective_output.anchors:
                detective_output.anchors = f"{detective_output.anchors},证据引用"
        return detective_output

    def _enforce_confession_boundary(
        self,
        suspect_output: GeneratedRoleOutput,
    ) -> GeneratedRoleOutput:
        full_confession_keywords = [
            "我杀了",
            "是我杀的",
            "我把他推入河",
            "我害死了他",
            "就是我干的",
        ]
        if any(keyword in suspect_output.speech for keyword in full_confession_keywords):
            suspect_output.thought = "不能在当前阶段完整认罪，只能做有限让步。"
            suspect_output.speech = "我承认那晚有激烈争执，也有隐瞒，但我没有想害死他。"
            suspect_output.anchors = "阶段性松口,否认致死"
        return suspect_output
