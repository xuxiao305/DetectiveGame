# InterrogationRoom MVP Prototype

This repository contains a runnable CLI prototype that follows the MVP handoff constraints.

## Run

```powershell
python main.py
```

## Implemented Scope

- Fixed single case loading
- Manual turn progression
- Evidence injection (fixed list)
- Per-turn contradiction detection with immediate display
- Session end export (full transcript, deduplicated contradictions, used evidence)

## Notes

- Current implementation uses in-memory session state.
- LLM generation is deterministic fallback to keep behavior stable for MVP testing.

## Performance Logging

You can enable timing logs to analyze slow runtime paths.

PowerShell example:

```powershell
$env:INTERROGATION_LOG_LEVEL = "INFO"
$env:INTERROGATION_LOG_FILE = "logs/interrogation.log"
python main.py
```

Timing log fields:

- `turn_timing`: per round total and stage timing (`model_ms`, `prompt_ms`, `evidence_ms`, `guard_ms`, `contradiction_ms`)
- `llm_generate_success`: per model call success latency
- `llm_generate_retry`: per retry latency and error reason
- `llm_generate_fallback`: model call downgraded to fallback output

## Optional Real Model Mode

Default behavior uses deterministic fallback generation.

You can enable an Anthropic-compatible endpoint by configuring `AppConfig.model` with:

- `provider="anthropic_compatible"`
- `model_name` set to your deployed model
- `anthropic_base_url_env` set to an environment variable name that stores base URL
- `anthropic_auth_token_env` set to an environment variable name that stores API token

Default expected environment variable names:

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`

If provider call fails (missing key, timeout, invalid output), runtime automatically degrades to fallback generation.

## Local DeepSeek Mode (Recommended)

You can run with a local OpenAI-compatible endpoint (for example Ollama/LM Studio/vLLM) and route to remote provider only as secondary fallback.

Suggested local model:

- `DeepSeek-R1-Distill-Qwen-14B` (Q4_K_L quantized version recommended)
- Local files path: `D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L`

Environment variables (PowerShell):

```powershell
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LOCAL_LLM_API_KEY = ""
$env:LOCAL_LLM_MODEL = "deepseek-r1-distill-qwen-14b"
$env:LOCAL_LLM_MODEL_PATH = "D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L"
python main.py
```

Route behavior:

- Primary provider: `local_openai_compatible`
- Secondary provider: `bytedance` (if configured)
- Final fallback: deterministic safe fallback output

Key logs:

- `llm_provider_route` (primary/secondary route)
- `llm_request` (`payload_bytes`, `model_path_exists`)
- `llm_generate_success` / `llm_generate_retry` / `llm_generate_fallback`

## ByteDance Provider Configuration

When using ByteDance provider (as secondary fallback or primary), inference parameters are now configurable:

- Temperature (controls randomness): configurable via `ModelConfig.bytedance_temperature`, default `0.7`
- Max tokens (response length): configurable via `ModelConfig.bytedance_max_tokens`, default `500`

These parameters help control generation variability and prevent excessive response lengths.

## Local Container Setup & Diagnostics

### Quick Start: Deploy Local Model (Ollama Example)

```powershell
# 1. Install Ollama from https://ollama.ai
# 2. Download the model (first time only, ~25GB for 14B)
ollama pull deepseek-r1:14b-qwen-q4_K_L

# 3. Start Ollama service (usually runs on port 11434)
ollama serve

# 4. In another terminal, set environment and test
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
python scripts/local_llm_connectivity_check.py
```

### Container Options

| Container | Default Port | Base URL | Notes |
|-----------|--------|----------|-------|
| Ollama | 11434 | `http://127.0.0.1:11434/v1` | Recommended, easiest setup |
| LM Studio | 8000 | `http://127.0.0.1:8000/v1` | GUI, good for monitoring |
| vLLM | 8000 | `http://127.0.0.1:8000/v1` | Fastest inference, requires more setup |

### Diagnostic Script

After deploying container, run diagnostic check:

```powershell
python scripts/local_llm_connectivity_check.py
```

This script verifies:
- Environment variables are configured
- Endpoint is reachable
- Model responds correctly
- Response format is valid

Sample output:
```
===========================================================================
Local LLM Connectivity Check
===========================================================================

[Environment Variables]
  LOCAL_LLM_BASE_URL: http://127.0.0.1:11434/v1
  LOCAL_LLM_API_KEY: (not set, will attempt unauthenticated)
  LOCAL_LLM_MODEL: deepseek-r1-distill-qwen-14b
  LOCAL_LLM_MODEL_PATH: D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L
  Model path exists: True

[Endpoint Resolution]
  Base URL: http://127.0.0.1:11434/v1
  Chat endpoint: http://127.0.0.1:11434/v1/chat/completions

[Testing Connectivity...]
  Sending test request to http://127.0.0.1:11434/v1/chat/completions...
  ✅ SUCCESS: Got response from model
  Model response: OK

===========================================================================
✅ Local LLM endpoint is ready for InterrogationRoom!
   You can now run: python main.py
===========================================================================
```

### Troubleshooting

**"Cannot reach endpoint"**:
```powershell
# Check if container is running on expected port
netstat -ano | findstr :11434  # For Ollama

# Try manual test
$url = "http://127.0.0.1:11434/v1/chat/completions"
(Invoke-WebRequest -Uri $url -Method Get).StatusCode
```

**"Model not found" or "Empty choices"**:
- Model name may differ; run `ollama list` to check available models
- Update `LOCAL_LLM_MODEL` env var to match

**"Empty content in response"**:
- Container may be overloaded or the model generation failed
- Check container logs and reduce `LOCAL_LLM_MODEL` max_tokens if needed



Run this script to validate environment variables and endpoint connectivity:

```powershell
python scripts/anthropic_connectivity_check.py
```

Required environment variables:

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`

Optional:

- `ANTHROPIC_MODEL` (defaults to `claude-3-5-sonnet-20241022`)
