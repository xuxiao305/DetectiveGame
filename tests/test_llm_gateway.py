from __future__ import annotations

import sys
import time
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.interrogation_mvp.llm_gateway import GenerationOptions, LLMGateway


class LLMGatewayTest(unittest.TestCase):
    def test_generate_detective_output_has_required_fields(self) -> None:
        gateway = LLMGateway()
        out = gateway.generate(
            role="detective",
            prompt={
                "role": "detective",
                "goal": "推进",
                "forced_constraint": "",
                "history": "无",
                "round": "1",
            },
            options=GenerationOptions(timeout_seconds=5, retry_times=1),
        )
        self.assertTrue(out.thought)
        self.assertTrue(out.speech)
        self.assertTrue(out.anchors)

    def test_generate_suspect_respects_boundary_in_fallback_style(self) -> None:
        gateway = LLMGateway()
        out = gateway.generate(
            role="suspect",
            prompt={
                "role": "suspect",
                "goal": "防御",
                "pressure": "4",
                "round": "3",
            },
            options=GenerationOptions(timeout_seconds=5, retry_times=1),
        )
        self.assertNotIn("我杀了", out.speech)

    def test_timeout_returns_quick_fallback(self) -> None:
        class SlowGateway(LLMGateway):
            def _raw_generate_payload(self, role, prompt):
                time.sleep(0.3)
                return super()._raw_generate_payload(role, prompt)

        gateway = SlowGateway()
        start = time.perf_counter()
        out = gateway.generate(
            role="detective",
            prompt={
                "role": "detective",
                "goal": "推进",
                "forced_constraint": "",
                "history": "无",
                "round": "1",
            },
            options=GenerationOptions(timeout_seconds=0.05, retry_times=0),
        )
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.2)
        self.assertIn("容错降级", out.anchors)

    def test_anthropic_compatible_without_env_falls_back(self) -> None:
        gateway = LLMGateway()
        out = gateway.generate(
            role="detective",
            prompt={
                "role": "detective",
                "goal": "推进",
                "forced_constraint": "",
                "history": "无",
                "round": "1",
            },
            options=GenerationOptions(
                timeout_seconds=0.2,
                retry_times=0,
                provider="anthropic_compatible",
                model_name="claude-3-5-sonnet-20241022",
                anthropic_base_url_env="THIS_BASE_URL_SHOULD_NOT_EXIST",
                anthropic_auth_token_env="THIS_TOKEN_SHOULD_NOT_EXIST",
            ),
        )
        self.assertIn("容错降级", out.anchors)


if __name__ == "__main__":
    unittest.main()
