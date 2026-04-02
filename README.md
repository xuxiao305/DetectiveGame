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

## Anthropic Connectivity Check

Run this script to validate environment variables and endpoint connectivity:

```powershell
python scripts/anthropic_connectivity_check.py
```

Required environment variables:

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`

Optional:

- `ANTHROPIC_MODEL` (defaults to `claude-3-5-sonnet-20241022`)
