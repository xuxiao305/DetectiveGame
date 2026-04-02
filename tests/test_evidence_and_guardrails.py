from __future__ import annotations

import sys
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.case_loader import create_initial_state
from src.interrogation_mvp.evidence import EvidenceInjectionHandler, find_evidence_text
from src.interrogation_mvp.guardrails import TurnGuard
from src.interrogation_mvp.llm_gateway import GeneratedRoleOutput


class EvidenceAndGuardrailsTest(unittest.TestCase):
    def test_inject_and_consume_evidence_once(self) -> None:
        state = create_initial_state()
        handler = EvidenceInjectionHandler()

        handler.inject(state, "e1")
        self.assertIn("e1", state.pending_evidence_ids)

        consumed = handler.consume_next_pending(state)
        self.assertEqual("e1", consumed)
        self.assertIn("e1", state.used_evidence_ids)
        self.assertEqual([], state.pending_evidence_ids)

        with self.assertRaises(ValueError):
            handler.inject(state, "e1")

    def test_find_evidence_text(self) -> None:
        state = create_initial_state()
        text = find_evidence_text(state, "e2")
        self.assertIsNotNone(text)
        self.assertIn("邻居证词", text)

    def test_guardrail_blocks_full_confession(self) -> None:
        guard = TurnGuard()
        detective = GeneratedRoleOutput(
            thought="推进",
            speech="请回答。",
            anchors="时间线追问",
        )
        suspect = GeneratedRoleOutput(
            thought="失控",
            speech="是我杀的。",
            anchors="失控",
        )

        _, fixed_suspect = guard.apply(detective, suspect, None)
        self.assertNotIn("是我杀的", fixed_suspect.speech)
        self.assertIn("没有想害死他", fixed_suspect.speech)


if __name__ == "__main__":
    unittest.main()
