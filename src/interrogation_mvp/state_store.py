"""In-memory state persistence for MVP sessions."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict

from .models import GameState


class InMemoryStateStore:
    def __init__(self) -> None:
        self._states: Dict[str, GameState] = {}

    def load_state(self, session_id: str) -> GameState:
        if session_id not in self._states:
            raise KeyError(f"Session not found: {session_id}")
        return deepcopy(self._states[session_id])

    def save_state(self, state: GameState) -> None:
        self._states[state.session_id] = deepcopy(state)
