"""Turn orchestration for one full interrogation round."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import perf_counter
from typing import List

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
