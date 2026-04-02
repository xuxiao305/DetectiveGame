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
                raise RuntimeError("simulated slow failure")

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
            options=GenerationOptions(provider="bytedance", timeout_seconds=0.05, retry_times=0),
        )
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 1.0)
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

    def test_local_provider_route_success(self) -> None:
        class LocalGateway(LLMGateway):
            def _generate_local_openai_compatible(self, role, prompt):
                return {
                    "thought": "本地推理",
                    "speech": f"{role} local ok",
                    "anchors": "local",
                }

        gateway = LocalGateway()
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
                provider="local_openai_compatible",
                timeout_seconds=0.5,
                retry_times=0,
            ),
        )
        self.assertEqual("detective local ok", out.speech)
        self.assertEqual("Local Deepseek", out.source)
        self.assertEqual("local", out.anchors)

    def test_secondary_provider_is_used_after_primary_failure(self) -> None:
        class RoutedGateway(LLMGateway):
            def _generate_local_openai_compatible(self, role, prompt):
                raise RuntimeError("primary unavailable")

            def _generate_bytedance(self, role, prompt):
                return {
                    "thought": "二级兜底",
                    "speech": "secondary ok",
                    "anchors": "secondary",
                }

        gateway = RoutedGateway()
        out = gateway.generate(
            role="suspect",
            prompt={
                "role": "suspect",
                "goal": "防御",
                "pressure": "2",
                "detective_question": "你昨晚在哪？",
                "round": "2",
            },
            options=GenerationOptions(
                provider="local_openai_compatible",
                secondary_provider="bytedance",
                timeout_seconds=0.5,
                retry_times=0,
            ),
        )
        self.assertEqual("secondary ok", out.speech)
        self.assertEqual("Remote", out.source)
        self.assertEqual("secondary", out.anchors)

    def test_bytedance_payload_includes_temperature_and_max_tokens(self) -> None:
        captured_payloads = []

        class PayloadCapturingGateway(LLMGateway):
            def _generate_bytedance(self, role, prompt):
                temperature = float(prompt.get("bytedance_temperature", 0.7))
                max_tokens = int(prompt.get("bytedance_max_tokens", 500))
                payload_info = {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                captured_payloads.append(payload_info)
                return {
                    "thought": "测试",
                    "speech": "ok",
                    "anchors": "test",
                }

        gateway = PayloadCapturingGateway()
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
                provider="bytedance",
                timeout_seconds=0.5,
                retry_times=0,
                bytedance_temperature=0.5,
                bytedance_max_tokens=300,
            ),
        )
        self.assertTrue(captured_payloads, "Should have captured bytedance payload")
        payload = captured_payloads[0]
        self.assertIn("temperature", payload)
        self.assertEqual(0.5, payload["temperature"])
        self.assertIn("max_tokens", payload)
        self.assertEqual(300, payload["max_tokens"])


    def test_no_env_vars_falls_back_to_safe_fallback(self) -> None:
        """Reproduce the crash seen when running python main.py without any env vars set.

        local_openai_compatible fails (no BASE_URL) → bytedance fires but raises
        HTTPError/URLError (no API key, would hit network) → must NOT crash,
        must return a safe fallback instead.
        """
        import urllib.error

        class NoEnvGateway(LLMGateway):
            def _generate_local_openai_compatible(self, role, prompt):
                raise RuntimeError("Missing base URL for local_openai_compatible provider")

            def _generate_bytedance(self, role, prompt):
                raise urllib.error.HTTPError(
                    url="https://example.com",
                    code=403,
                    msg="Forbidden",
                    hdrs=None,  # type: ignore[arg-type]
                    fp=None,
                )

        gateway = NoEnvGateway()
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
                provider="local_openai_compatible",
                secondary_provider="bytedance",
                timeout_seconds=0.5,
                retry_times=0,
            ),
        )
        self.assertIn("容错降级", out.anchors)
        self.assertEqual("Fallback", out.source)


if __name__ == "__main__":
    unittest.main()
