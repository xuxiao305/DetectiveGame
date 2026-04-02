"""Game controller exposing start, next turn, inject evidence and end actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .case_loader import create_initial_state
from .config import AppConfig, default_config
from .contradiction import ContradictionDetector
from .evidence import EvidenceInjectionHandler
from .exporter import TranscriptExporter
from .guardrails import TurnGuard
from .llm_gateway import GenerationOptions, LLMGateway
from .models import GameState, SessionStatus
from .orchestrator import TurnOrchestrator, TurnResult
from .prompt_composer import PromptComposer
from .state_store import InMemoryStateStore


@dataclass
class EndResult:
    reason: str
    transcript: str


class GameController:
    def __init__(
        self,
        store: Optional[InMemoryStateStore] = None,
        app_config: Optional[AppConfig] = None,
    ) -> None:
        self._store = store or InMemoryStateStore()
        self._config = app_config or default_config()
        self._orchestrator = TurnOrchestrator(
            composer=PromptComposer(),
            gateway=LLMGateway(),
            evidence_handler=EvidenceInjectionHandler(),
            detector=ContradictionDetector(),
            guard=TurnGuard(),
            generation_options=GenerationOptions(
                timeout_seconds=self._config.model.timeout_seconds,
                retry_times=self._config.model.retry_times,
                provider=self._config.model.provider,
                model_name=self._config.model.model_name,
                anthropic_base_url_env=self._config.model.anthropic_base_url_env,
                anthropic_auth_token_env=self._config.model.anthropic_auth_token_env,
            ),
        )
        self._evidence_handler = EvidenceInjectionHandler()
        self._exporter = TranscriptExporter()

    def start_session(self) -> GameState:
        state = create_initial_state(
            round_soft_limit=self._config.game.round_soft_limit,
            round_hard_limit=self._config.game.round_hard_limit,
        )
        state.status = SessionStatus.RUNNING
        self._store.save_state(state)
        return state

    def next_turn(self, session_id: str) -> TurnResult:
        state = self._store.load_state(session_id)
        if state.status == SessionStatus.ENDED:
            raise RuntimeError("会话已结束，不能继续推进回合。")
        if state.status == SessionStatus.HARD_LIMIT:
            raise RuntimeError("已达到硬上限，系统将结束会话。")
        result = self._orchestrator.run_turn(state)
        self._store.save_state(state)
        return result

    def inject_evidence(self, session_id: str, evidence_id: str) -> GameState:
        state = self._store.load_state(session_id)
        self._evidence_handler.inject(state, evidence_id)
        self._store.save_state(state)
        return state

    def get_state(self, session_id: str) -> GameState:
        return self._store.load_state(session_id)

    def end_session(self, session_id: str, reason: str) -> EndResult:
        state = self._store.load_state(session_id)
        state.status = SessionStatus.ENDED
        self._store.save_state(state)
        transcript = self._exporter.export_session(state)
        return EndResult(reason=reason, transcript=transcript)
