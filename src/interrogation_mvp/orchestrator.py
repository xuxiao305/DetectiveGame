"""Turn orchestration for one full interrogation round."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter
from typing import List

from .claim_extractor import ClaimExtractor
from .contradiction import ContradictionDetector
from .evidence import EvidenceInjectionHandler, find_evidence_text
from .guardrails import TurnGuard
from .llm_gateway import GenerationOptions, LLMGateway
from .models import DialogueTurn, GameState, SessionStatus
from .prompt_composer import PromptComposer, build_context


LOGGER = logging.getLogger(__name__)


@dataclass
class TurnResult:
    turn: DialogueTurn
    new_contradiction_descriptions: List[str]


class TurnOrchestrator:
    def __init__(
        self,
        composer: PromptComposer,
        gateway: LLMGateway,
        evidence_handler: EvidenceInjectionHandler,
        detector: ContradictionDetector,
        guard: TurnGuard,
        generation_options: GenerationOptions,
    ) -> None:
        self._composer = composer
        self._gateway = gateway
        self._evidence_handler = evidence_handler
        self._detector = detector
        self._claim_extractor = ClaimExtractor()
        self._guard = guard
        self._generation_options = generation_options

    def run_turn(self, state: GameState) -> TurnResult:
        turn_started_at = perf_counter()
        if state.status in (SessionStatus.ENDED, SessionStatus.HARD_LIMIT):
            raise RuntimeError("会话已结束，不能继续推进回合。")

        next_round = state.round_index + 1

        evidence_started_at = perf_counter()
        evidence_id = self._evidence_handler.consume_next_pending(state)
        evidence_text = find_evidence_text(state, evidence_id)
        evidence_elapsed_ms = (perf_counter() - evidence_started_at) * 1000

        prompt_started_at = perf_counter()
        context = build_context(state, evidence_text)
        detective_prompt = self._composer.build_detective_prompt(context)
        prompt_elapsed_ms = (perf_counter() - prompt_started_at) * 1000

        model_started_at = perf_counter()
        detective_output = self._gateway.generate(
            "detective",
            detective_prompt,
            self._generation_options,
        )
        suspect_prompt = self._composer.build_suspect_prompt(
            context,
            detective_question=detective_output.speech,
        )
        suspect_output = self._gateway.generate(
            "suspect",
            suspect_prompt,
            self._generation_options,
        )
        model_wall_elapsed_ms = (perf_counter() - model_started_at) * 1000
        detective_model_elapsed_ms = detective_output.latency_ms
        suspect_model_elapsed_ms = suspect_output.latency_ms

        guard_started_at = perf_counter()
        detective_output, suspect_output = self._guard.apply(
            detective_output=detective_output,
            suspect_output=suspect_output,
            pending_evidence_text=evidence_text,
        )
        guard_elapsed_ms = (perf_counter() - guard_started_at) * 1000

        contradiction_started_at = perf_counter()
        new_contradictions = self._detector.detect(
            state=state,
            new_answer=suspect_output.speech,
            round_index=next_round,
        )
        contradiction_elapsed_ms = (perf_counter() - contradiction_started_at) * 1000

        turn = DialogueTurn(
            round_index=next_round,
            detective_thought=detective_output.thought,
            detective_question=detective_output.speech,
            suspect_thought=suspect_output.thought,
            suspect_answer=suspect_output.speech,
            injected_evidence_id=evidence_id,
            detective_source=detective_output.source,
            suspect_source=suspect_output.source,
            new_contradictions=[
                f"[{item.category}/{item.severity}] {item.description}"
                for item in new_contradictions
            ],
        )

        state.turns.append(turn)
        state.round_index = next_round

        # ── 更新角色记忆（两个角色的记忆存不同维度的信息）──
        claim_text = turn.suspect_answer.strip()
        if claim_text:
            extracted = self._claim_extractor.extract_key_claims(claim_text, max_chars=80)

            # 嫌疑人记忆：记录自己说过的话，用于保持说辞一致
            state.suspect_memory.recent_claims.append(f"R{next_round}: {extracted}")
            if len(state.suspect_memory.recent_claims) > 10:
                state.suspect_memory.recent_claims = state.suspect_memory.recent_claims[-10:]

            # 侦探记忆：记录侦探视角的发现——有矛盾则记矛盾，无矛盾则记疑点
            if new_contradictions:
                for item in new_contradictions:
                    state.detective_memory.recent_claims.append(
                        f"R{next_round} 矛盾[{item.severity}]: {item.description[:60]}"
                    )
            else:
                state.detective_memory.recent_claims.append(
                    f"R{next_round} 疑点待深挖: {extracted}"
                )
            if len(state.detective_memory.recent_claims) > 10:
                state.detective_memory.recent_claims = state.detective_memory.recent_claims[-10:]

        # 嫌疑人心理压力梯度（仅在 Dream 模式尚未生成摘要时作为兜底）
        if not state.suspect_memory.summary:
            contradiction_count = len(state.contradictions)
            if contradiction_count == 0:
                state.suspect_memory.summary = "坚决否认，维持不在场说法。"
            elif contradiction_count <= 2:
                state.suspect_memory.summary = "说辞出现漏洞，需要小心应对，可以局部松口但不能认罪。"
            else:
                state.suspect_memory.summary = "多处矛盾被揭穿，防线即将崩溃，考虑换一种辩解方式。"

        if state.round_index >= state.round_limit_hard:
            state.status = SessionStatus.HARD_LIMIT
        elif state.round_index >= state.round_limit_soft:
            state.status = SessionStatus.SOFT_LIMIT
        else:
            state.status = SessionStatus.RUNNING

        total_elapsed_ms = (perf_counter() - turn_started_at) * 1000
        LOGGER.info(
            "turn_timing round=%s total_ms=%.1f model_chain_ms=%.1f model_detective_ms=%.1f model_suspect_ms=%.1f prompt_ms=%.1f evidence_ms=%.1f guard_ms=%.1f contradiction_ms=%.1f",
            next_round,
            total_elapsed_ms,
            model_wall_elapsed_ms,
            detective_model_elapsed_ms,
            suspect_model_elapsed_ms,
            prompt_elapsed_ms,
            evidence_elapsed_ms,
            guard_elapsed_ms,
            contradiction_elapsed_ms,
        )

        return TurnResult(
            turn=turn,
            new_contradiction_descriptions=[
                f"[{item.category}/{item.severity}] {item.description}"
                for item in new_contradictions
            ],
        )

    def maybe_consolidate(self, state: GameState, every: int = 3) -> None:
        """Dream 模式：每隔 every 轮，让两个角色 AI 各自更新自己的记忆摘要。
        调用失败时静默跳过，不影响主流程。"""
        if state.round_index == 0 or state.round_index % every != 0:
            return
        LOGGER.info("dream_consolidate round=%s", state.round_index)
        # 嫌疑人自我整理：我承诺过什么，我现在的处境
        suspect_summary = self._gateway.generate_summary(
            "suspect",
            state.suspect_memory.recent_claims,
            self._generation_options,
        )
        if suspect_summary:
            state.suspect_memory.summary = suspect_summary
            LOGGER.info("dream_suspect_summary updated: %s", suspect_summary[:60])
        # 侦探自我整理：我发现了什么漏洞，下一步怎么施压
        detective_summary = self._gateway.generate_summary(
            "detective",
            state.detective_memory.recent_claims,
            self._generation_options,
        )
        if detective_summary:
            state.detective_memory.summary = detective_summary
            LOGGER.info("dream_detective_summary updated: %s", detective_summary[:60])
