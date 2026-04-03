"""Runtime configuration for MVP defaults and guardrails."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    round_soft_limit: int = 16
    round_hard_limit: int = 20
    manual_turn_only: bool = True


@dataclass(frozen=True)
class ModelConfig:
    strategy: str = "stable_consistent"
    randomness: str = "low"
    max_output_tokens: str = "medium"
    timeout_seconds: int = 20
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
    local_request_timeout_seconds: int = 45
    local_max_tokens: int = 1024
    local_num_ctx: int = 8192
    local_temperature: float = 0.2
    anthropic_model_name: str = "claude-sonnet-4-6"
    anthropic_temperature: float = 0.2
    anthropic_max_tokens: int = 512
    anthropic_base_url_env: str = "ANTHROPIC_BASE_URL"
    anthropic_auth_token_env: str = "ANTHROPIC_AUTH_TOKEN"
    bytedance_api_key_env: str = "ByteDance_API_Key"
    bytedance_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"


@dataclass(frozen=True)
class GuardrailConfig:
    enforce_detective_progress: bool = True
    enforce_no_full_confession: bool = True


@dataclass(frozen=True)
class AppConfig:
    game: GameConfig = GameConfig()
    model: ModelConfig = ModelConfig()
    guardrail: GuardrailConfig = GuardrailConfig()


def default_config() -> AppConfig:
    provider_override = os.getenv("INTERROGATION_PROVIDER", "").strip()
    model_override = os.getenv("INTERROGATION_MODEL_NAME", "").strip()
    if provider_override:
        model_kwargs: dict = {"provider": provider_override}
        if model_override:
            if provider_override == "anthropic_compatible":
                model_kwargs["anthropic_model_name"] = model_override
            elif provider_override == "local_openai_compatible":
                model_kwargs["local_model_name"] = model_override
            else:
                model_kwargs["model_name"] = model_override
        return AppConfig(model=ModelConfig(**model_kwargs))
    return AppConfig()
