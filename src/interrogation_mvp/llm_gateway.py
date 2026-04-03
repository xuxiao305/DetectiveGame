"""Model gateway with deterministic MVP fallback generation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
import json
import logging
import os
import re
from time import perf_counter
from typing import Any, Dict
from urllib import error, request
from urllib.parse import urljoin


LOGGER = logging.getLogger(__name__)


@dataclass
class GeneratedRoleOutput:
    thought: str
    speech: str
    anchors: str
    latency_ms: float = 0.0
    source: str = ""


@dataclass(frozen=True)
class GenerationOptions:
    timeout_seconds: float = 20
    retry_times: int = 1
    provider: str = "local_openai_compatible"
    secondary_provider: str = ""
    model_name: str = "doubao-seed-2-0-pro-260215"
    bytedance_temperature: float = 0.7
    bytedance_max_tokens: int = 500
    local_model_name: str = "deepseek-r1-14b-q4"
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_model_path: str = "D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L"
    local_base_url_env: str = "LOCAL_LLM_BASE_URL"
    local_api_key_env: str = "LOCAL_LLM_API_KEY"
    local_request_timeout_seconds: float = 45
    local_max_tokens: int = 1024
    local_num_ctx: int = 8192
    local_temperature: float = 0.2
    anthropic_model_name: str = "claude-sonnet-4-20250514"
    anthropic_temperature: float = 0.2
    anthropic_max_tokens: int = 512
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
        self._executor = ThreadPoolExecutor(max_workers=4)

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
        provider_sequence = self._provider_sequence(prompt_with_provider)
        primary_provider = provider_sequence[0]
        secondary_provider = provider_sequence[1] if len(provider_sequence) > 1 else ""
        last_error: Exception | None = None

        LOGGER.info(
            "llm_provider_route role=%s selected_provider=%s secondary_provider=%s",
            role,
            primary_provider,
            secondary_provider or "none",
        )

        for provider_index, provider in enumerate(provider_sequence):
            source = "primary" if provider_index == 0 else "secondary"
            provider_prompt = dict(prompt_with_provider)
            provider_prompt["provider"] = provider
            if provider == "local_openai_compatible":
                provider_prompt["request_timeout"] = str(
                    provider_prompt.get("local_request_timeout", run_options.timeout_seconds)
                )
            else:
                provider_prompt["request_timeout"] = str(run_options.timeout_seconds)

            for attempt in range(1, max_attempts + 1):
                attempt_started_at = perf_counter()
                try:
                    payload = self._run_with_timeout(role, provider_prompt, float(provider_prompt["request_timeout"]))
                    elapsed_ms = (perf_counter() - attempt_started_at) * 1000
                    LOGGER.info(
                        "llm_generate_success role=%s provider=%s output_source=%s attempt=%s/%s elapsed_ms=%.1f",
                        role,
                        provider,
                        source,
                        attempt,
                        max_attempts,
                        elapsed_ms,
                    )
                    output = self._normalize_output(payload, role)
                    output.source = self._source_label(provider)
                    output.latency_ms = elapsed_ms
                    return output
                except Exception as err:
                    last_error = err
                    elapsed_ms = (perf_counter() - attempt_started_at) * 1000
                    LOGGER.warning(
                        "llm_generate_retry role=%s provider=%s output_source=%s attempt=%s/%s elapsed_ms=%.1f error=%s",
                        role,
                        provider,
                        source,
                        attempt,
                        max_attempts,
                        elapsed_ms,
                        err,
                    )
                    continue

        if last_error:
            LOGGER.warning(
                "llm_generate_fallback role=%s provider=%s output_source=safe_fallback reason=%s",
                role,
                ",".join(provider_sequence),
                last_error,
            )
            fallback_output = self._safe_fallback(role)
            fallback_output.source = "Fallback"
            return fallback_output
        LOGGER.warning(
            "llm_generate_fallback role=%s provider=%s output_source=safe_fallback reason=unknown",
            role,
            ",".join(provider_sequence),
        )
        fallback_output = self._safe_fallback(role)
        fallback_output.source = "Fallback"
        return fallback_output

    def _run_with_timeout(self, role: str, prompt: Dict[str, str], timeout_seconds: float) -> Any:
        future = self._executor.submit(self._raw_generate_payload, role, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as err:
            future.cancel()
            raise RuntimeError("Model generation timeout") from err

    def generate_summary(
        self,
        role: str,
        claims: list[str],
        options: GenerationOptions | None = None,
    ) -> str:
        """Dream 模式：让角色 AI 自己整理当前处境，返回不超过120字的纯文本摘要。失败时静默返回空串。"""
        run_options = options or GenerationOptions()
        context = "\n".join(claims) if claims else "暂无记录"
        if role == "suspect":
            system_text = (
                "你是嫌疑人。根据以下审讯记录，用不超过60字总结："
                "你目前最需要守住的核心说辞，以及你当前的心理压力状态。"
                "只输出结论，不要解释，不要输出JSON。"
            )
        else:
            system_text = (
                "你是侦探。根据以下侦察记录，用不超过60字总结："
                "你已发现的最关键漏洞，以及下一步最该从哪个角度施压。"
                "只输出结论，不要解释，不要输出JSON。"
            )
        user_text = f"记录：\n{context}"
        provider_seq = self._provider_sequence(
            {"provider": run_options.provider, "secondary_provider": run_options.secondary_provider}
        )
        for provider in provider_seq:
            try:
                text = self._call_text_provider(provider, system_text, user_text, run_options)
                if text:
                    return text.strip()[:120]
            except Exception as err:
                LOGGER.warning("dream_consolidation_failed role=%s provider=%s error=%s", role, provider, err)
        return ""

    def _call_text_provider(
        self, provider: str, system_text: str, user_text: str, options: GenerationOptions
    ) -> str:
        """向指定 provider 发一次简单 system+user 请求，返回裸文本。"""
        if provider == "local_openai_compatible":
            return self._consolidate_local(system_text, user_text, options)
        if provider == "bytedance":
            return self._consolidate_bytedance(system_text, user_text, options)
        if provider == "anthropic_compatible":
            return self._consolidate_anthropic(system_text, user_text, options)
        return ""

    def _consolidate_local(self, system_text: str, user_text: str, options: GenerationOptions) -> str:
        base_url = os.getenv(options.local_base_url_env) or options.local_base_url
        if not base_url:
            raise RuntimeError("Missing base URL for local consolidation")
        endpoint = self._resolve_ollama_chat_endpoint(base_url)
        model_name = os.getenv("LOCAL_LLM_MODEL", options.local_model_name) or options.local_model_name
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "options": {"temperature": options.local_temperature, "num_predict": 256},
        }
        req = request.Request(
            url=endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=options.local_request_timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return self._sanitize_model_text(str(body.get("message", {}).get("content", "")))

    def _consolidate_bytedance(self, system_text: str, user_text: str, options: GenerationOptions) -> str:
        api_key = os.getenv(options.bytedance_api_key_env) or os.getenv("BYTEDANCE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing ByteDance API key for consolidation")
        endpoint = f"{options.bytedance_base_url.rstrip('/')}/responses"
        payload = {
            "model": options.model_name,
            "temperature": options.bytedance_temperature,
            "max_tokens": 200,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
            ],
        }
        req = request.Request(
            url=endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with request.urlopen(req, timeout=options.timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        for item in body.get("output", []):
            for block in item.get("content", []):
                if isinstance(block, dict) and block.get("type") == "output_text":
                    return str(block.get("text", "")).strip()
        return ""

    def _consolidate_anthropic(self, system_text: str, user_text: str, options: GenerationOptions) -> str:
        api_key = os.getenv(options.anthropic_auth_token_env)
        base_url = os.getenv(options.anthropic_base_url_env)
        if not api_key or not base_url:
            raise RuntimeError("Missing Anthropic credentials for consolidation")
        endpoint = self._resolve_anthropic_messages_endpoint(base_url)
        payload = {
            "model": options.anthropic_model_name,
            "max_tokens": 200,
            "temperature": options.anthropic_temperature,
            "system": system_text,
            "messages": [{"role": "user", "content": user_text}],
        }
        req = request.Request(
            url=endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=options.timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        parts = [
            str(b.get("text", "")).strip()
            for b in body.get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:
        try:
            self.shutdown()
        except Exception:
            pass

    def _raw_generate_payload(self, role: str, prompt: Dict[str, str]) -> Any:
        provider = str(prompt.get("provider", "fallback")).strip().lower()
        if provider == "local_openai_compatible":
            return self._generate_local_openai_compatible(role, prompt)
        if provider == "bytedance":
            return self._generate_bytedance(role, prompt)
        if provider == "anthropic_compatible":
            return self._generate_anthropic_compatible(role, prompt)
        if role == "detective":
            return self._generate_detective(prompt)
        return self._generate_suspect(prompt)

    def _provider_sequence(self, prompt: Dict[str, str]) -> list[str]:
        primary = str(prompt.get("provider", "fallback")).strip().lower()
        secondary = str(prompt.get("secondary_provider", "")).strip().lower()
        sequence: list[str] = [primary or "fallback"]
        if secondary and secondary != sequence[0]:
            sequence.append(secondary)
        return sequence

    def _generate_local_openai_compatible(self, role: str, prompt: Dict[str, str]) -> Any:
        base_url_env_name = str(prompt.get("local_base_url_env", "LOCAL_LLM_BASE_URL"))
        api_key_env_name = str(prompt.get("local_api_key_env", "LOCAL_LLM_API_KEY"))
        base_url = os.getenv(base_url_env_name) or str(prompt.get("local_base_url", "")).strip()
        if not base_url:
            raise RuntimeError("Missing base URL for local_openai_compatible provider")

        default_local_model = str(
            prompt.get("local_model_name", prompt.get("model_name", "deepseek-r1-14b-q4"))
        )
        model_name = os.getenv("LOCAL_LLM_MODEL", default_local_model).strip() or default_local_model
        default_model_path = str(prompt.get("local_model_path", "")).strip()
        model_path = os.getenv("LOCAL_LLM_MODEL_PATH", default_model_path).strip()
        model_path_exists = bool(model_path and os.path.exists(model_path))

        endpoint = self._resolve_ollama_chat_endpoint(base_url)
        system_text = self._system_prompt(role)
        user_text = self._build_user_text(role, prompt)
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "stream": False,
            "options": {
                "temperature": float(prompt.get("local_temperature", 0.2)),
                "num_predict": int(prompt.get("local_max_tokens", 1024)),
                "num_ctx": int(prompt.get("local_num_ctx", 8192)),
            },
        }
        payload_text = json.dumps(payload, ensure_ascii=False)
        payload_size = len(payload_text.encode("utf-8"))
        LOGGER.info(
            "llm_request role=%s provider=local_openai_compatible model=%s payload_bytes=%s model_path_exists=%s",
            role,
            model_name,
            payload_size,
            model_path_exists,
        )

        req = request.Request(
            url=endpoint,
            data=payload_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=float(prompt.get("request_timeout", 45))) as resp:
            body = resp.read().decode("utf-8")

        parsed = json.loads(body)
        message = parsed.get("message", {}) if isinstance(parsed, dict) else {}
        content_text = self._sanitize_model_text(str(message.get("content", ""))) if isinstance(message, dict) else ""
        if not content_text:
            raise RuntimeError("Empty content from ollama /api/chat provider")
        extracted = self._extract_json_from_text(content_text)
        if extracted:
            return extracted
        return {
            "thought": "保持稳定叙事，不偏离角色目标。",
            "speech": content_text,
            "anchors": "剧情推进",
        }

    def _generate_bytedance(self, role: str, prompt: Dict[str, str]) -> Any:
        api_key_env = str(prompt.get("bytedance_api_key_env", "ByteDance_API_Key"))
        base_url = str(prompt.get("bytedance_base_url", "https://ark.cn-beijing.volces.com/api/v3")).rstrip("/")
        api_key = os.getenv(api_key_env) or os.getenv("BYTEDANCE_API_KEY")
        if not api_key:
            raise RuntimeError(f"Missing API key env: {api_key_env}")

        model_name = str(prompt.get("model_name", "doubao-seed-2-0-pro-260215"))
        endpoint = f"{base_url}/responses"

        system_text = self._system_prompt(role)
        user_text = self._build_user_text(role, prompt)
        temperature = float(prompt.get("bytedance_temperature", 0.7))
        max_tokens = int(prompt.get("bytedance_max_tokens", 500))
        payload = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
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
        payload_text = json.dumps(payload, ensure_ascii=False)
        payload_size = len(payload_text.encode("utf-8"))
        LOGGER.info(
            "llm_request role=%s provider=bytedance model=%s payload_bytes=%s",
            role,
            model_name,
            payload_size,
        )
        req = request.Request(
            url=endpoint,
            data=payload_text.encode("utf-8"),
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

        extracted = self._extract_json_from_text(text)
        if extracted:
            return extracted
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

        model_name = str(prompt.get("anthropic_model_name", "claude-sonnet-4-20250514"))
        temperature = float(prompt.get("anthropic_temperature", 0.2))
        max_tokens = int(prompt.get("anthropic_max_tokens", 512))
        endpoint = self._resolve_anthropic_messages_endpoint(base_url)

        system_text = self._system_prompt(role)
        user_text = self._build_user_text(role, prompt)
        payload = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_text,
            "messages": [
                {"role": "user", "content": user_text},
            ],
        }
        payload_text = json.dumps(payload, ensure_ascii=False)
        payload_size = len(payload_text.encode("utf-8"))
        LOGGER.info(
            "llm_request role=%s provider=anthropic_compatible model=%s payload_bytes=%s",
            role,
            model_name,
            payload_size,
        )
        req = request.Request(
            url=endpoint,
            data=payload_text.encode("utf-8"),
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

        extracted = self._extract_json_from_text(content)
        if extracted:
            return extracted
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

    def _resolve_ollama_chat_endpoint(self, base_url: str) -> str:
        trimmed = base_url.strip().rstrip("/")
        if trimmed.endswith("/api/chat"):
            return trimmed
        if trimmed.endswith("/v1"):
            return f"{trimmed[:-3]}/api/chat"
        return f"{trimmed}/api/chat"

    def _sanitize_model_text(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        # 1. Remove complete <think>...</think> reasoning blocks.
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        # 2. Remove any residual orphan <think> or </think> tags.
        cleaned = re.sub(r"</?think>", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or raw

    def _extract_json_from_text(self, text: str) -> dict | None:
        """Try to find a JSON object containing 'speech' in free-form text."""
        # Try the whole text first.
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "speech" in obj:
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        # Search for a JSON-like block.
        match = re.search(r'\{[^{}]*"speech"\s*:\s*"[^"]*"[^{}]*\}', text)
        if match:
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict) and obj.get("speech"):
                    return obj
            except (json.JSONDecodeError, ValueError):
                pass
        return None

    def _normalize_output(self, payload: Any, role: str = "detective") -> GeneratedRoleOutput:
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

        speech = self._clean_speech(speech, role)

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

    def _clean_speech(self, text: str, role: str = "detective") -> str:
        """Post-process speech: remove role confusion, loops, analysis frameworks."""
        # 1. Strip "作为XX，我会……" meta-narration prefix.
        text = re.sub(r'^作为\S{1,10}[，,]?\s*(我会|我将|我要|我需要).*?[，。,\.]\s*', '', text)
        # 2. Strip "姓名：台词" cross-role lines.
        text = re.sub(r'\n?\S{2,5}[：:].+', '', text)
        # 3. Strip "1. xxx：" numbered lists.
        text = re.sub(r'\d+\.\s*\S+[：:].+', '', text)
        
        # 4. Role-specific cleaning: suspect should not ask detective-style interrogation questions
        if role == "suspect":
            # Remove detective-style interrogation patterns (审讯式问题)
            # 这些是侦探才会问的问题，嫌疑人不应该问
            detective_interrogation_patterns = [
                r'你(具体|到底|为什么|怎么)(在哪里|做了什么|什么时候).{0,30}？',  # "你具体在哪里？"
                r'(在|于)(\w{2,6})(时间段|期间)内.{0,20}你.{0,20}？',  # "在某某时间段内，你..."
                r'是否有(证据|目击者|人|物证).{0,20}？',  # "是否有目击者？"
                r'(请|能不能|可以).{0,20}(解释|说明|澄清).{0,20}(你的|这个).{0,20}？',  # "请你解释你的行踪？"
            ]
            for pattern in detective_interrogation_patterns:
                text = re.sub(pattern, '', text)
            
            # If too many questions remain (likely contamination), extract statements only
            question_count = text.count('？') + text.count('?')
            if question_count >= 3:  # 提高阈值，允许1-2个合理提问
                sentences = re.split(r'[。！？]', text)
                # Keep declarative sentences and defensive questions (我能、我可以、您...)
                valid = [s.strip() for s in sentences 
                        if s.strip() and ('？' not in s and '?' not in s or 
                                         '我能' in s or '我可以' in s or '您' in s)]
                if valid:
                    text = '。'.join(valid[:2]) + '。'
        
        # 5. Deduplicate repeating blocks.
        text = self._dedup_repeating_blocks(text)
        # 6. Hard truncate at 150 chars.
        text = text.strip()
        if len(text) > 150:
            text = text[:147] + "……"
        return text

    def _dedup_repeating_blocks(self, text: str) -> str:
        """Detect and remove repeating blocks, keeping only the first occurrence."""
        lines = text.strip().split('\n')
        if len(lines) <= 2:
            return text
        seen: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in seen:
                break
            seen.append(stripped)
        return '\n'.join(seen)

    def _source_label(self, provider: str) -> str:
        provider_name = provider.strip().lower()
        if provider_name == "local_openai_compatible":
            return "Local Deepseek"
        if provider_name == "anthropic_compatible":
            return "Claude"
        if provider_name == "bytedance":
            return "ByteDance"
        return "Fallback"

    def _system_prompt(self, role: str = "detective") -> str:
        base = (
            "你是审讯对话引擎。严格遵守以下规则：\n"
            '1. 只输出一个JSON对象，格式：{"thought":"...","speech":"...","anchors":"..."}\n'
            "2. speech 是你这个角色说出口的一句话，必须直接对对方说，不超过100字\n"
            "3. 禁止在 speech 中扮演对方角色，禁止出现对方的名字+冒号+对方台词\n"
            "4. 禁止输出多轮对话、分析框架、编号列表、审讯计划\n"
            '5. 禁止输出“作为XX我会……”这类元叙述，直接说话\n'
            "6. thought 是内心独白，不超过50字\n"
        )
        if role == "detective":
            role_hint = (
                "7. 你是侦探，必须对嫌疑人提问，speech 必须是疑问句\n"
                "8. 正确示例：\n"
                '   {"thought":"他的时间线有破绽","speech":"你说11点在家，但邻居听到你开车出去了，怎么解释？","anchors":"时间线矛盾"}\n'
                "9. 错误示例（禁止输出）：\n"
                '   {"speech":"作为侦探陈明远，我会首先询问……1.时间线 2.地点"}\n'
                '   {"speech":"嫌疑人李建国应该回答……"}'
            )
        else:
            role_hint = (
                "7. 你是嫌疑人，主要任务是回答侦探的问题，保持说辞一致\n"
                "8. 禁止替侦探提问：不要问'你在哪里''你什么时候''是否有证据'等审讯式问题\n"
                "9. 允许防御性提问：可以问'我能请律师吗''您说的证据是什么'\n"
                "10. 正确示例：\n"
                '   {"thought":"不能承认出过门","speech":"警官，我真的在家睡觉，可能邻居听错了。","anchors":"否认出门"}\n'
                '   {"thought":"需要看证据","speech":"我能看一下您说的证据吗？","anchors":"要求证据"}\n'
                "11. 错误示例（禁止输出）：\n"
                '   {"speech":"李建国：警官您搞错了……陈明远：请你解释……"}\n'
                '   {"speech":"你具体在哪里？你在什么时候出去的？是否有目击者？"}\n'
                '   {"speech":"在某某时间段内，你具体在什么地方？"}'
            )
        return base + role_hint

    def _build_user_text(self, role: str, prompt: Dict[str, str]) -> str:
        case_name = prompt.get("case_name", "")
        background = prompt.get("background", "")
        character_name = prompt.get("character_name", "")
        character_known = prompt.get("character_known", "")

        if role == "detective":
            role_instruction = (
                f"【你的身份】你是侦探{character_name}，正在审讯嫌疑人。\n"
                f"【输出要求】直接对嫌疑人说一句提问，不要自言自语，"
                f"不要替嫌疑人回答，不要输出分析计划。"
            )
            claims_section = (
                f"【嫌疑人已承诺的说辞 - 注意矛盾】\n{prompt.get('suspect_claims', '暂无')}"
            )
            detective_notes_section = (
                f"【侦探笔记 - 我发现的疑点与矛盾】\n{prompt.get('detective_notes', '暂无')}"
            )
        else:
            role_instruction = (
                f"【你的身份】你是嫌疑人{character_name}，正在被侦探审讯。\n"
                f"【输出要求】直接回答侦探的问题，只说一句话或一段话，"
                f"不要替侦探提问，不要自问自答。"
            )
            claims_section = (
                f"【你之前说过的话 - 不可自相矛盾】\n{prompt.get('my_previous_claims', '暂无')}"
            )
            detective_notes_section = ""

        parts = [
            role_instruction,
            claims_section,
            detective_notes_section,
            f"案件:{case_name}" if case_name else "",
            f"背景:{background}" if background else "",
            f"你掌握的信息:{character_known}" if character_known else "",
            f"回合:{prompt.get('round', '')}",
            f"目标:{prompt.get('goal', '')}",
            f"警官提问:{prompt.get('detective_question', '')}" if prompt.get('detective_question') else "",
            f"约束:{prompt.get('forced_constraint', prompt.get('confession_boundary', ''))}" if prompt.get('forced_constraint') or prompt.get('confession_boundary') else "",
            f"历史:{prompt.get('history', '')}",
        ]
        return "\n".join(p for p in parts if p)

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
        enriched["secondary_provider"] = options.secondary_provider
        enriched["model_name"] = options.model_name
        enriched["bytedance_temperature"] = str(options.bytedance_temperature)
        enriched["bytedance_max_tokens"] = str(options.bytedance_max_tokens)
        enriched["local_model_name"] = options.local_model_name
        enriched["local_base_url"] = options.local_base_url
        enriched["local_model_path"] = options.local_model_path
        enriched["local_base_url_env"] = options.local_base_url_env
        enriched["local_api_key_env"] = options.local_api_key_env
        enriched["local_request_timeout"] = str(options.local_request_timeout_seconds)
        enriched["local_max_tokens"] = str(options.local_max_tokens)
        enriched["local_num_ctx"] = str(options.local_num_ctx)
        enriched["local_temperature"] = str(options.local_temperature)
        enriched["anthropic_model_name"] = options.anthropic_model_name
        enriched["anthropic_temperature"] = str(options.anthropic_temperature)
        enriched["anthropic_max_tokens"] = str(options.anthropic_max_tokens)
        enriched["anthropic_base_url_env"] = options.anthropic_base_url_env
        enriched["anthropic_auth_token_env"] = options.anthropic_auth_token_env
        enriched["bytedance_api_key_env"] = options.bytedance_api_key_env
        enriched["bytedance_base_url"] = options.bytedance_base_url
        enriched["request_timeout"] = str(options.timeout_seconds)
        return enriched
