from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.case_loader import create_initial_state
from src.interrogation_mvp.contradiction import ContradictionDetector
from src.interrogation_mvp.models import DialogueTurn


class ContradictionDetectorTest(unittest.TestCase):
    def test_detects_multiple_categories_with_history(self) -> None:
        state = create_initial_state()
        detector = ContradictionDetector()

        state.turns.append(
            DialogueTurn(
                round_index=1,
                detective_thought="",
                detective_question="",
                suspect_thought="",
                suspect_answer="我11点前就在家睡了。",
            )
        )

        items = detector.detect(
            state=state,
            new_answer="我那晚出去买东西，后来又在家睡了。",
            round_index=2,
        )
        categories = {item.category for item in items}
        self.assertIn("LOCATION", categories)
        self.assertIn("ALIBI", categories)

    def test_evidence_aware_rules_trigger(self) -> None:
        state = create_initial_state()
        detector = ContradictionDetector()

        state.used_evidence_ids = ["e1", "e2", "e3", "e4"]
        items = detector.detect(
            state=state,
            new_answer="我只是去便利店买东西，没联系过他，也没有经济纠纷。",
            round_index=1,
        )
        categories = {item.category for item in items}
        self.assertIn("LOCATION", categories)
        self.assertIn("BEHAVIOR", categories)
        self.assertIn("MOTIVE", categories)

    def test_deduplicates_same_contradiction(self) -> None:
        state = create_initial_state()
        detector = ContradictionDetector()

        detector.detect(state=state, new_answer="我那晚出去买东西，后来又在家睡了。", round_index=1)
        initial_count = len(state.contradictions)
        detector.detect(state=state, new_answer="我那晚出去买东西，后来又在家睡了。", round_index=2)

        self.assertEqual(initial_count, len(state.contradictions))


if __name__ == "__main__":
    unittest.main()
