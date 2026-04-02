"""Check model endpoint connectivity using environment variables.

Supported providers:
- anthropic: ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN
- google: GOOGLE_API_KEY
- bytedance: ByteDance_API_Key

Optional:
- CONNECTIVITY_PROVIDER (anthropic or google, default: anthropic)
- ANTHROPIC_MODEL (default: claude-3-5-sonnet-20241022)
- GOOGLE_MODEL (default: gemini-2.5-flash)
- BYTEDANCE_BASE_URL (default: https://ark.cn-beijing.volces.com/api/v3)
- BYTEDANCE_MODEL (default: doubao-seed-2-0-pro-260215)
"""

from __future__ import annotations

import json
import os
import sys
from urllib import error
from urllib import request
from urllib.parse import urljoin


def _resolve_messages_endpoint(base_url: str) -> str:
    trimmed = base_url.strip()
    if trimmed.endswith("/v1/messages") or trimmed.endswith("/messages"):
        return trimmed
    if trimmed.endswith("/"):
        return urljoin(trimmed, "v1/messages")
    return f"{trimmed}/v1/messages"


def _resolve_google_endpoint(model: str, api_key: str) -> str:
    return (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent?key={api_key}"
    )


def _resolve_bytedance_endpoints(base_url: str) -> tuple[str, str]:
    trimmed = base_url.strip().rstrip("/")
    if not trimmed:
        trimmed = "https://ark.cn-beijing.volces.com/api/v3"

    if trimmed.endswith("/responses"):
        root = trimmed[: -len("/responses")]
        return f"{root}/models", trimmed
    if trimmed.endswith("/models"):
        root = trimmed[: -len("/models")]
        return trimmed, f"{root}/responses"
    if trimmed.endswith("/api/v3"):
        return f"{trimmed}/models", f"{trimmed}/responses"

    return f"{trimmed}/models", f"{trimmed}/responses"


def _run_request(req: request.Request, timeout: float) -> tuple[int, str]:
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200)), resp.read().decode("utf-8")
    except error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        print("[FAIL] HTTP request failed")
        print(f"Status: {err.code}")
        print(f"Reason: {err.reason}")
        print(f"Response preview: {body[:400]}")
        raise


def _run_anthropic() -> int:
    base_url = os.getenv("ANTHROPIC_BASE_URL", "").strip()
    token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()

    if not base_url:
        print("[FAIL] Missing env: ANTHROPIC_BASE_URL")
        return 2
    if not token:
        print("[FAIL] Missing env: ANTHROPIC_AUTH_TOKEN")
        return 2

    endpoint = _resolve_messages_endpoint(base_url)

    payload = {
        "model": model,
        "max_tokens": 32,
        "temperature": 0.0,
        "system": "Reply with one short sentence in Chinese.",
        "messages": [
            {"role": "user", "content": "连接检查：请回复OK"},
        ],
    }

    req = request.Request(
        url=endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        _, body = _run_request(req, timeout=15)
    except Exception as err:
        print("[FAIL] Network/auth request failed")
        print(f"Reason: {err}")
        print(f"Endpoint: {endpoint}")
        return 3

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        print("[FAIL] Response is not valid JSON")
        print(f"Raw preview: {body[:200]}")
        return 4

    content_blocks = parsed.get("content", [])
    text_parts = [
        str(block.get("text", "")).strip()
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    text = "\n".join(part for part in text_parts if part)

    if not text:
        print("[FAIL] Response JSON parsed but no text content found")
        print(f"Top-level keys: {list(parsed.keys())}")
        return 5

    print("[PASS] Anthropic connectivity check succeeded")
    print(f"Endpoint: {endpoint}")
    print(f"Model: {model}")
    print(f"Response preview: {text[:120]}")
    return 0


def _run_google() -> int:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    model = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash").strip()

    if not api_key:
        print("[FAIL] Missing env: GOOGLE_API_KEY")
        return 2

    endpoint = _resolve_google_endpoint(model, api_key)
    payload = {
        "systemInstruction": {
            "parts": [
                {"text": "Reply with one short sentence in Chinese."},
            ]
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": "连接检查：请回复OK"},
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 32,
        },
    }

    req = request.Request(
        url=endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        _, body = _run_request(req, timeout=15)
    except Exception as err:
        print("[FAIL] Network/auth request failed")
        print(f"Reason: {err}")
        print(
            "Endpoint: "
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{model}:generateContent"
        )
        return 3

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        print("[FAIL] Response is not valid JSON")
        print(f"Raw preview: {body[:200]}")
        return 4

    candidates = parsed.get("candidates", [])
    text_parts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
        parts = content.get("parts", []) if isinstance(content, dict) else []
        for part in parts:
            if isinstance(part, dict) and part.get("text"):
                text_parts.append(str(part["text"]).strip())

    text = "\n".join(part for part in text_parts if part)
    if not text:
        print("[FAIL] Response JSON parsed but no text content found")
        print(f"Top-level keys: {list(parsed.keys())}")
        return 5

    print("[PASS] Google connectivity check succeeded")
    print(
        "Endpoint: "
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )
    print(f"Model: {model}")
    print(f"Response preview: {text[:120]}")
    return 0


def _extract_bytedance_model_id(models_payload: dict, preferred_model: str) -> str:
    data = models_payload.get("data", [])
    if preferred_model:
        return preferred_model
    if not isinstance(data, list):
        return ""
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            return str(item.get("id")).strip()
    return ""


def _run_bytedance() -> int:
    api_key = os.getenv("ByteDance_API_Key", "").strip() or os.getenv("BYTEDANCE_API_KEY", "").strip()
    base_url = os.getenv("BYTEDANCE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").strip()
    preferred_model = os.getenv("BYTEDANCE_MODEL", "doubao-seed-2-0-pro-260215").strip()

    if not api_key:
        print("[FAIL] Missing env: ByteDance_API_Key")
        return 2

    models_endpoint, chat_endpoint = _resolve_bytedance_endpoints(base_url)

    models_req = request.Request(
        url=models_endpoint,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="GET",
    )
    try:
        _, models_body = _run_request(models_req, timeout=15)
    except Exception as err:
        print("[FAIL] ByteDance models query failed")
        print(f"Reason: {err}")
        print(f"Endpoint: {models_endpoint}")
        return 3

    try:
        models_payload = json.loads(models_body)
    except json.JSONDecodeError:
        print("[FAIL] ByteDance models response is not valid JSON")
        print(f"Raw preview: {models_body[:300]}")
        return 4

    model = _extract_bytedance_model_id(models_payload, preferred_model)
    if not model:
        print("[FAIL] No available ByteDance model discovered")
        print(f"Top-level keys: {list(models_payload.keys())}")
        return 5

    # /responses endpoint uses typed input array (not messages)
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "连接检查：请回复OK"},
                ],
            }
        ],
    }
    chat_req = request.Request(
        url=chat_endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        _, chat_body = _run_request(chat_req, timeout=20)
    except Exception as err:
        print("[FAIL] ByteDance responses request failed")
        print(f"Reason: {err}")
        print(f"Endpoint: {chat_endpoint}")
        print(f"Model: {model}")
        return 3

    try:
        parsed = json.loads(chat_body)
    except json.JSONDecodeError:
        print("[FAIL] ByteDance response is not valid JSON")
        print(f"Raw preview: {chat_body[:300]}")
        return 4

    # /responses returns output array with typed items
    text = ""
    output = parsed.get("output", [])
    for item in (output if isinstance(output, list) else []):
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        for block in (content if isinstance(content, list) else []):
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = str(block.get("text", "")).strip()
                if text:
                    break
        if text:
            break

    if not text:
        print("[FAIL] ByteDance response JSON parsed but no output_text found")
        print(f"Top-level keys: {list(parsed.keys())}")
        print(f"Raw preview: {chat_body[:300]}")
        return 5

    print("[PASS] ByteDance connectivity check succeeded")
    print(f"Endpoint: {chat_endpoint}")
    print(f"Model: {model}")
    print(f"Response preview: {text[:120]}")
    return 0


def run() -> int:
    provider = os.getenv("CONNECTIVITY_PROVIDER", "anthropic").strip().lower()
    if provider == "google":
        return _run_google()
    if provider == "bytedance":
        return _run_bytedance()
    if provider == "anthropic":
        return _run_anthropic()

    print(f"[FAIL] Unsupported CONNECTIVITY_PROVIDER: {provider}")
    return 2


if __name__ == "__main__":
    raise SystemExit(run())
