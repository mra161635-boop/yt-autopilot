"""
utils/llm.py — Unified LLM interface supporting multiple backends.

Backends:
  - ollama (default): Fully free, runs locally. Install from ollama.com
  - openai_compat: Any OpenAI-compatible API (OpenRouter, Groq, Together, etc.)
"""

import json
import requests
from config import LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL


def llm_complete(prompt: str, max_tokens: int = 2000) -> str:
    """Send a prompt to the configured LLM and return the text response."""
    url = f"{LLM_BASE_URL}/v1/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}

    if LLM_PROVIDER == "openai_compat":
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"Cannot reach {LLM_PROVIDER} at {LLM_BASE_URL}. "
            f"Make sure it's running. "
            f"(Hint: for Ollama, run 'ollama serve' and 'ollama pull {LLM_MODEL}')"
        )
    except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
        raise RuntimeError(f"LLM call failed: {e}")
