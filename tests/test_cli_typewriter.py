from __future__ import annotations

import io
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.cli import _print_turn, _typewriter_delay_seconds
from src.interrogation_mvp.models import DialogueTurn
from src.interrogation_mvp.orchestrator import TurnResult


class CliTypewriterTest(unittest.TestCase):
    def test_typewriter_delay_default_is_40ms(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INTERROGATION_TYPEWRITER_DELAY_MS", None)
            self.assertAlmostEqual(0.04, _typewriter_delay_seconds())

    def test_typewriter_delay_zero_disables_delay(self) -> None:
        with patch.dict(os.environ, {"INTERROGATION_TYPEWRITER_DELAY_MS": "0"}, clear=False):
            self.assertEqual(0.0, _typewriter_delay_seconds())

    def test_print_turn_uses_typewriter_for_speech_fields(self) -> None:
        turn = DialogueTurn(
            round_index=1,
            detective_thought="保持推进",
            detective_question="你昨晚在哪？",
            suspect_thought="先稳住",
            suspect_answer="我一直在家。",
            injected_evidence_id=None,
            new_contradictions=[],
        )
        result = TurnResult(turn=turn, new_contradiction_descriptions=[])

        captured = io.StringIO()
        with patch("sys.stdout", new=captured):
            with patch.dict(os.environ, {"INTERROGATION_TYPEWRITER_DELAY_MS": "0"}, clear=False):
                with patch("time.sleep") as sleep_mock:
                    _print_turn(result)
                    sleep_mock.assert_not_called()

        rendered = captured.getvalue()
        self.assertIn("侦探发问：你昨晚在哪？", rendered)
        self.assertIn("嫌疑人回答：我一直在家。", rendered)


if __name__ == "__main__":
    unittest.main()
