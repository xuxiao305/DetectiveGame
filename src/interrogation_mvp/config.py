"""Runtime configuration for MVP defaults and guardrails."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameConfig:
    round_soft_limit: int = 12
    round_hard_limit: int = 15
    manual_turn_only: bool = True


@dataclass(frozen=True)
class ModelConfig:
    strategy: str = "stable_consistent"
    randomness: str = "low"
    max_output_tokens: str = "medium"
    timeout_seconds: int = 20
    retry_times: int = 1
    provider: str = "bytedance"
    model_name: str = "doubao-seed-2-0-pro-260215"
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
    return AppConfig()
