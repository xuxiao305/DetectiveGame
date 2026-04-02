"""Turn orchestration for one full interrogation round."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .contradiction import ContradictionDetector
from .evidence import EvidenceInjectionHandler, find_evidence_text
from .guardrails import TurnGuard
from .llm_gateway import GenerationOptions, LLMGateway
from .models import DialogueTurn, GameState, SessionStatus
from .prompt_composer import PromptComposer, build_context


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
        if state.status in (SessionStatus.ENDED, SessionStatus.HARD_LIMIT):
            raise RuntimeError("会话已结束，不能继续推进回合。")

        next_round = state.round_index + 1
        evidence_id = self._evidence_handler.consume_next_pending(state)
        evidence_text = find_evidence_text(state, evidence_id)

        context = build_context(state, evidence_text)
        detective_prompt = self._composer.build_detective_prompt(context)
        suspect_prompt = self._composer.build_suspect_prompt(context)

        detective_output = self._gateway.generate(
            "detective",
            detective_prompt,
            self._generation_options,
        )
        suspect_output = self._gateway.generate(
            "suspect",
            suspect_prompt,
            self._generation_options,
        )

        detective_output, suspect_output = self._guard.apply(
            detective_output=detective_output,
            suspect_output=suspect_output,
            pending_evidence_text=evidence_text,
        )

        new_contradictions = self._detector.detect(
            state=state,
            new_answer=suspect_output.speech,
            round_index=next_round,
        )

        turn = DialogueTurn(
            round_index=next_round,
            detective_thought=detective_output.thought,
            detective_question=detective_output.speech,
            suspect_thought=suspect_output.thought,
            suspect_answer=suspect_output.speech,
            injected_evidence_id=evidence_id,
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

        return TurnResult(
            turn=turn,
            new_contradiction_descriptions=[
                f"[{item.category}/{item.severity}] {item.description}"
                for item in new_contradictions
            ],
        )
