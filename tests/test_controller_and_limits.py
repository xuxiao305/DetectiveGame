from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.controller import GameController
from src.interrogation_mvp.models import SessionStatus


class ControllerAndLimitsTest(unittest.TestCase):
    def test_start_session_and_manual_turns(self) -> None:
        controller = GameController()
        state = controller.start_session()

        self.assertEqual(SessionStatus.RUNNING, state.status)
        self.assertEqual(0, state.round_index)

        result = controller.next_turn(state.session_id)
        self.assertEqual(1, result.turn.round_index)

    def test_soft_and_hard_limit_state_transition(self) -> None:
        controller = GameController()
        state = controller.start_session()

        for _ in range(12):
            controller.next_turn(state.session_id)
        state = controller.get_state(state.session_id)
        self.assertEqual(SessionStatus.SOFT_LIMIT, state.status)
        self.assertEqual(12, state.round_index)

        for _ in range(3):
            controller.next_turn(state.session_id)
        state = controller.get_state(state.session_id)
        self.assertEqual(SessionStatus.HARD_LIMIT, state.status)
        self.assertEqual(15, state.round_index)

        with self.assertRaises(RuntimeError):
            controller.next_turn(state.session_id)

    def test_next_turn_after_end_is_blocked(self) -> None:
        controller = GameController()
        state = controller.start_session()
        controller.end_session(state.session_id, "test end")

        with self.assertRaises(RuntimeError):
            controller.next_turn(state.session_id)


if __name__ == "__main__":
    unittest.main()
