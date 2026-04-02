"""Week3+Week4 smoke test: end-to-end flow with evidence, contradictions, and export checks."""

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

    # Inject all evidence across early rounds.
    for evidence_id in ["e1", "e2", "e3", "e4"]:
        controller.inject_evidence(state.session_id, evidence_id)
        controller.next_turn(state.session_id)

    # Continue to 10 rounds for stability check.
    while True:
        current = controller.get_state(state.session_id)
        if current.round_index >= 10:
            break
        controller.next_turn(state.session_id)

    final_state = controller.get_state(state.session_id)
    assert final_state.round_index == 10, "Expected 10 rounds"
    assert len(final_state.used_evidence_ids) == 4, "All evidence should be consumed"

    categories = {item.category for item in final_state.contradictions}
    assert len(categories) >= 3, "At least 3 contradiction categories should be detected"

    end_result = controller.end_session(state.session_id, "smoke test end")
    transcript = end_result.transcript

    assert "=== 对话记录 ===" in transcript
    assert "=== 矛盾点汇总（去重）===" in transcript
    assert "=== 使用证据 ===" in transcript

    print(
        "Week3+Week4 smoke test passed: 10 rounds stable, 4 evidence consumed, "
        f"{len(categories)} contradiction categories detected."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
