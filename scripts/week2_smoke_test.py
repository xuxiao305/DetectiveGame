"""Week2 smoke test: run 10 rounds and verify guardrail expectations."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.controller import GameController


def run() -> int:
    controller = GameController()
    state = controller.start_session()

    # Inject one evidence to validate forced next-turn referencing.
    controller.inject_evidence(state.session_id, "e1")

    turns = []
    for _ in range(10):
        result = controller.next_turn(state.session_id)
        turns.append(result.turn)

    final_state = controller.get_state(state.session_id)

    assert final_state.round_index == 10, "Expected exactly 10 rounds in smoke test"
    assert final_state.status.name in ("RUNNING", "SOFT_LIMIT"), "Unexpected status before round 12"

    first_turn_question = turns[0].detective_question
    assert "便利店监控" in first_turn_question, "Evidence should be referenced in next turn after injection"

    banned = ["我杀了", "是我杀的", "我把他推入河", "我害死了他"]
    for turn in turns:
        for keyword in banned:
            assert keyword not in turn.suspect_answer, "Full confession boundary violated"

    print("Week2 smoke test passed: 10 rounds stable, evidence referenced, confession boundary respected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
