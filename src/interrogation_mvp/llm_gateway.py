"""Model gateway with deterministic MVP fallback generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
import json
import os
from typing import Any, Dict
from urllib import request
from urllib.parse import urljoin


@dataclass
class GeneratedRoleOutput:
    thought: str
    speech: str
    anchors: str


@dataclass(frozen=True)
class GenerationOptions:
    timeout_seconds: float = 20
    retry_times: int = 1
    provider: str = "bytedance"
    model_name: str = "doubao-seed-2-0-pro-260215"
    anthropic_base_url_env: str = "ANTHROPIC_BASE_URL"
    anthropic_auth_token_env: str = "ANTHROPIC_AUTH_TOKEN"
    bytedance_api_key_env: str = "ByteDance_API_Key"
    bytedance_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"


class LLMGateway:
    """MVP gateway.

    This gateway provides deterministic outputs so the game can run without
    external model dependencies. It keeps behavior stable and low-random.
    """

    def __init__(self) -> None:
        # Keep a long-lived executor to avoid implicit blocking shutdown on timeout.
        self._executor = ThreadPoolExecutor(max_workers=1)

    def generate(
        self,
        role: str,
        prompt: Dict[str, str],
        options: GenerationOptions | None = None,
    ) -> GeneratedRoleOutput:
        if role not in ("detective", "suspect"):
            raise ValueError(f"Unsupported role: {role}")

        run_options = options or GenerationOptions()
        prompt_with_provider = self._with_provider_prompt(prompt, run_options)
        max_attempts = max(1, run_options.retry_times + 1)
        last_error: Exception | None = None

        for _ in range(max_attempts):
            try:
                payload = self._run_with_timeout(role, prompt_with_provider, run_options.timeout_seconds)
                return self._normalize_output(payload)
            except (ValueError, RuntimeError) as err:
                last_error = err
                continue

        if last_error:
            return self._safe_fallback(role)
        return self._safe_fallback(role)

    def _run_with_timeout(self, role: str, prompt: Dict[str, str], timeout_seconds: int) -> Any:
        future = self._executor.submit(self._raw_generate_payload, role, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as err:
            future.cancel()
            raise RuntimeError("Model generation timeout") from err

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass

    def _raw_generate_payload(self, role: str, prompt: Dict[str, str]) -> Any:
        provider = str(prompt.get("provider", "fallback")).strip().lower()
        if provider == "bytedance":
            return self._generate_bytedance(role, prompt)
        if provider == "anthropic_compatible":
            return self._generate_anthropic_compatible(role, prompt)
        if role == "detective":
            return self._generate_detective(prompt)
        return self._generate_suspect(prompt)

    def _generate_bytedance(self, role: str, prompt: Dict[str, str]) -> Any:
        api_key_env = str(prompt.get("bytedance_api_key_env", "ByteDance_API_Key"))
        base_url = str(prompt.get("bytedance_base_url", "https://ark.cn-beijing.volces.com/api/v3")).rstrip("/")
        api_key = os.getenv(api_key_env) or os.getenv("BYTEDANCE_API_KEY")
        if not api_key:
            raise RuntimeError(f"Missing API key env: {api_key_env}")

        model_name = str(prompt.get("model_name", "doubao-seed-2-0-pro-260215"))
        endpoint = f"{base_url}/responses"

        system_text = (
            "你是审讯对话引擎。输出严格 JSON，字段为 thought, speech, anchors。"
            "保持角色一致性，禁止输出额外字段。"
        )
        user_text = (
            f"角色:{role}\n"
            f"回合:{prompt.get('round', '')}\n"
            f"目标:{prompt.get('goal', '')}\n"
            f"约束:{prompt.get('forced_constraint', prompt.get('confession_boundary', ''))}\n"
            f"历史:{prompt.get('history', '')}"
        )
        payload = {
            "model": model_name,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_text}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_text}],
                },
            ],
        }
        req = request.Request(
            url=endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=float(prompt.get("request_timeout", 30))) as resp:
            body = resp.read().decode("utf-8")

        parsed = json.loads(body)
        text = ""
        for item in parsed.get("output", []):
            if not isinstance(item, dict):
                continue
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") == "output_text":
                    text = str(block.get("text", "")).strip()
                    if text:
                        break
            if text:
                break

        if not text:
            raise RuntimeError("Empty output_text from bytedance provider")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                "thought": "保持稳定叙事，不偏离角色目标。",
                "speech": text,
                "anchors": "剧情推进",
            }

    def _generate_anthropic_compatible(self, role: str, prompt: Dict[str, str]) -> Any:
        token_env_name = str(prompt.get("anthropic_auth_token_env", "ANTHROPIC_AUTH_TOKEN"))
        base_url_env_name = str(prompt.get("anthropic_base_url_env", "ANTHROPIC_BASE_URL"))
        api_key = os.getenv(token_env_name)
        base_url = os.getenv(base_url_env_name)
        if not api_key:
            raise RuntimeError("Missing API token for anthropic_compatible provider")
        if not base_url:
            raise RuntimeError("Missing base URL for anthropic_compatible provider")

        model_name = str(prompt.get("model_name", "claude-3-5-sonnet-20241022"))
        endpoint = self._resolve_anthropic_messages_endpoint(base_url)

        system_text = (
            "你是审讯对话引擎。输出严格 JSON，字段为 thought, speech, anchors。"
            "保持角色一致性，禁止输出额外字段。"
        )
        user_text = (
            f"角色:{role}\n"
            f"回合:{prompt.get('round', '')}\n"
            f"目标:{prompt.get('goal', '')}\n"
            f"约束:{prompt.get('forced_constraint', prompt.get('confession_boundary', ''))}\n"
            f"历史:{prompt.get('history', '')}"
        )
        payload = {
            "model": model_name,
            "max_tokens": 256,
            "temperature": 0.2,
            "system": system_text,
            "messages": [
                {"role": "user", "content": user_text},
            ],
        }
        req = request.Request(
            url=endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=float(prompt.get("request_timeout", 20))) as resp:
            body = resp.read().decode("utf-8")

        parsed = json.loads(body)
        content_blocks = parsed.get("content", [])
        text_parts = [
            str(block.get("text", "")).strip()
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        content = "\n".join(part for part in text_parts if part)
        if not content:
            raise RuntimeError("Empty content from anthropic_compatible provider")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "thought": "保持稳定叙事，不偏离角色目标。",
                "speech": content.strip(),
                "anchors": "剧情推进",
            }

    def _resolve_anthropic_messages_endpoint(self, base_url: str) -> str:
        trimmed = base_url.strip()
        if trimmed.endswith("/v1/messages"):
            return trimmed
        if trimmed.endswith("/messages"):
            return trimmed
        if trimmed.endswith("/"):
            return urljoin(trimmed, "v1/messages")
        return f"{trimmed}/v1/messages"

    def _normalize_output(self, payload: Any) -> GeneratedRoleOutput:
        if isinstance(payload, GeneratedRoleOutput):
            thought = (payload.thought or "").strip()
            speech = (payload.speech or "").strip()
            anchors = (payload.anchors or "").strip()
        elif isinstance(payload, dict):
            thought = str(payload.get("thought", "")).strip()
            speech = str(payload.get("speech", "")).strip()
            anchors = str(payload.get("anchors", "")).strip()
        elif isinstance(payload, str):
            thought = "保持策略并推进审讯。"
            speech = payload.strip()
            anchors = "时间线追问"
        else:
            raise ValueError("Unsupported payload type from model generation")

        if not speech:
            raise ValueError("Model output normalization failed: speech is empty")

        if not thought:
            thought = "保持稳定叙事，不偏离角色目标。"
        if not anchors:
            anchors = "剧情推进"

        return GeneratedRoleOutput(thought=thought, speech=speech, anchors=anchors)

    def _safe_fallback(self, role: str) -> GeneratedRoleOutput:
        if role == "detective":
            return GeneratedRoleOutput(
                thought="先稳住节奏，继续围绕时间线追问。",
                speech="你再确认一次，当晚11点前后你具体在哪里、做了什么？",
                anchors="时间线追问,容错降级",
            )
        return GeneratedRoleOutput(
            thought="先保留核心否认，避免彻底崩盘。",
            speech="我承认说法有不一致，但我没有想害死他。",
            anchors="阶段性松口,容错降级",
        )

    def _generate_detective(self, prompt: Dict[str, str]) -> GeneratedRoleOutput:
        forced = prompt.get("forced_constraint", "")
        if forced:
            thought = "新证据很关键，我要把它钉在时间线上。"
            speech = (
                "我们刚收到新证据。" + forced.replace("本轮必须引用新证据：", "") +
                " 你解释一下，你之前的说法和这个怎么对上？"
            )
            anchors = "证据引用,时间线追问"
        else:
            thought = "先卡住时间与行动轨迹，再压缩他的解释空间。"
            speech = "你坚持说11点前就睡了，那你手机为什么在河边附近出现？"
            anchors = "时间线追问,地点追问"
        return GeneratedRoleOutput(thought=thought, speech=speech, anchors=anchors)

    def _generate_suspect(self, prompt: Dict[str, str]) -> GeneratedRoleOutput:
        pressure = int(prompt.get("pressure", "0"))
        if pressure >= 3:
            thought = "压力很大，只能松口一部分，但不能承认致命细节。"
            speech = "我承认那晚和他吵过，也确实撒了谎，但我没有想害死他。"
            anchors = "阶段性松口,否认致死"
        else:
            thought = "必须守住底线，不能被他们带节奏。"
            speech = "我只是出去买点东西，很快就回家了，之后我就在家睡了。"
            anchors = "维持不在场,回避细节"
        return GeneratedRoleOutput(thought=thought, speech=speech, anchors=anchors)

    def _with_provider_prompt(self, prompt: Dict[str, str], options: GenerationOptions) -> Dict[str, str]:
        enriched = dict(prompt)
        enriched["provider"] = options.provider
        enriched["model_name"] = options.model_name
        enriched["anthropic_base_url_env"] = options.anthropic_base_url_env
        enriched["anthropic_auth_token_env"] = options.anthropic_auth_token_env
        enriched["bytedance_api_key_env"] = options.bytedance_api_key_env
        enriched["bytedance_base_url"] = options.bytedance_base_url
        enriched["request_timeout"] = str(options.timeout_seconds)
        return enriched
