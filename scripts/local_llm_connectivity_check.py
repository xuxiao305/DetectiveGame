"""Check local LLM endpoint connectivity and model availability.

Environment variables required:
- LOCAL_LLM_BASE_URL: base URL for OpenAI-compatible endpoint
  (default: http://127.0.0.1:11434/v1)

Optional:
- LOCAL_LLM_API_KEY: API key if the local server requires authentication
- LOCAL_LLM_MODEL: model name to test
  (default: deepseek-r1-distill-qwen-14b)
- LOCAL_LLM_MODEL_PATH: local file path to model
  (default: D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L)

This script tests:
1. Environment variables are set correctly
2. Base URL is reachable
3. Model endpoint accepts requests
4. Response format is valid JSON with expected fields
"""

from __future__ import annotations

import json
import os
import sys
from urllib import error, request
from urllib.parse import urljoin


def _resolve_openai_chat_endpoint(base_url: str) -> str:
    """Resolve base URL to /v1/chat/completions endpoint."""
    trimmed = base_url.strip()
    if trimmed.endswith("/v1/chat/completions"):
        return trimmed
    if trimmed.endswith("/chat/completions"):
        return trimmed
    if trimmed.endswith("/v1"):
        return f"{trimmed}/chat/completions"
    if trimmed.endswith("/"):
        return urljoin(trimmed, "v1/chat/completions")
    return f"{trimmed}/v1/chat/completions"


def check_local_llm_connectivity() -> bool:
    """Check local LLM endpoint connectivity and model availability."""
    base_url_env = "LOCAL_LLM_BASE_URL"
    api_key_env = "LOCAL_LLM_API_KEY"
    model_env = "LOCAL_LLM_MODEL"
    model_path_env = "LOCAL_LLM_MODEL_PATH"

    # Defaults
    default_base_url = "http://127.0.0.1:11434/v1"
    default_model = "deepseek-r1-distill-qwen-14b"
    default_path = "D:/AI/Models/DeepSeek-R1-Distill-Qwen-14B-Q4_K_L"

    print("=" * 70)
    print("Local LLM Connectivity Check")
    print("=" * 70)

    # Check environment variables
    base_url = os.getenv(base_url_env, default_base_url).strip()
    api_key = os.getenv(api_key_env, "").strip()
    model_name = os.getenv(model_env, default_model).strip()
    model_path = os.getenv(model_path_env, default_path).strip()

    print("\n[Environment Variables]")
    print(f"  {base_url_env}: {base_url}")
    if api_key:
        print(f"  {api_key_env}: (set, masked)")
    else:
        print(f"  {api_key_env}: (not set, will attempt unauthenticated)")
    print(f"  {model_env}: {model_name}")
    print(f"  {model_path_env}: {model_path}")

    # Check model path exists
    path_exists = os.path.exists(model_path)
    print(f"  Model path exists: {path_exists}")
    if not path_exists:
        print(f"    ⚠️  Warning: Model path not found at {model_path}")

    # Resolve endpoint
    endpoint = _resolve_openai_chat_endpoint(base_url)
    print(f"\n[Endpoint Resolution]")
    print(f"  Base URL: {base_url}")
    print(f"  Chat endpoint: {endpoint}")

    # Test connectivity
    print(f"\n[Testing Connectivity...]")
    try:
        # Simple test request
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": "你好，请回复 OK。",
                }
            ],
            "temperature": 0.2,
            "max_tokens": 50,
        }
        payload_text = json.dumps(payload, ensure_ascii=False)

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = request.Request(
            url=endpoint,
            data=payload_text.encode("utf-8"),
            headers=headers,
            method="POST",
        )

        print(f"  Sending test request to {endpoint}...")
        with request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")

        result = json.loads(body)

        # Check response structure
        choices = result.get("choices", [])
        if not choices:
            print("  ❌ FAILED: Empty choices in response")
            print(f"  Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return False

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content:
            print("  ❌ FAILED: Empty content in response")
            print(f"  Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
            return False

        print(f"  ✅ SUCCESS: Got response from model")
        print(f"  Model response: {content[:100]}...")

        return True

    except error.URLError as e:
        print(f"  ❌ FAILED: Cannot reach endpoint")
        print(f"  Error: {e}")
        print(f"\n  Troubleshooting tips:")
        print(f"  1. Check if local LLM service is running")
        print(f"  2. Verify {base_url_env} is correct")
        print(f"  3. For Ollama: http://127.0.0.1:11434 (port 11434)")
        print(f"  4. For LM Studio: http://127.0.0.1:8000 (port 8000)")
        print(f"  5. For vLLM: http://127.0.0.1:8000 (port 8000)")
        return False

    except json.JSONDecodeError as e:
        print(f"  ❌ FAILED: Invalid JSON response from endpoint")
        print(f"  Error: {e}")
        print(f"  This usually means:")
        print(f"  - The endpoint is not OpenAI-compatible")
        print(f"  - Or the model is not responding properly")
        return False

    except Exception as e:
        print(f"  ❌ FAILED: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    success = check_local_llm_connectivity()
    print("\n" + "=" * 70)
    if success:
        print("✅ Local LLM endpoint is ready for InterrogationRoom!")
        print("   You can now run: python main.py")
    else:
        print("❌ Local LLM endpoint check failed")
        print("   Please fix the issues above and try again")
    print("=" * 70)

    sys.exit(0 if success else 1)
