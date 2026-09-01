"""
LLM configuration for Opencode (Zen / Go) with OpenAI-compatible SDK.

Priority:
  1. OPENCODE_GO_API_KEY  -> https://opencode.ai/zen/go/v1 (Go subscription, $10/mo)
  2. OPENCODE_ZEN_API_KEY  -> https://opencode.ai/zen/v1   (Zen pay-as-you-go)
  3. OPENCODE_API_KEY      -> auto-detected (Zen if no GO hint, else Go if baseURL contains /go)
  4. OPENAI_API_KEY        -> fallback to OpenAI direct

Both Zen and Go are OpenAI-compatible, so we keep using `ChatOpenAI` (langchain-openai)
and `openai` SDK under the hood, but pointed at Opencode endpoints. This is the
official pattern per https://opencode.ai/docs/zen and https://opencode.ai/docs/go
and community example https://github.com/awtotty/pi-opencode.

Optional `opencode-ai` Python SDK (pip install opencode-ai) is for controlling the
Opencode *server* (sessions/events), not for LLM chat completions. Chat completions
still go via OpenAI-compatible /v1/chat/completions.

Env vars:
  OPENCODE_API_KEY / OPENCODE_ZEN_API_KEY / OPENCODE_GO_API_KEY
  OPENCODE_BASE_URL / OPENCODE_ZEN_BASE_URL / OPENCODE_GO_BASE_URL  (optional override)
  OPENCODE_MODEL / OPENAI_MODEL                                (optional model override)
  OPENCODE_SMALL_MODEL                                          (optional small model)
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    # Load .env first (real keys); fallback to env.example/.env.example for template
    # User requested env.example — so we support both filenames.
    for _env_file in (".env", "env.example", ".env.example"):
        _p = Path(__file__).parent / _env_file
        if _p.exists():
            load_dotenv(_p, override=False)
            break
except ImportError:
    pass

# Default endpoints (OpenAI-compatible)
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"

# Free models (Zen) — verified via https://opencode.ai/docs/zen 2026-08:
# User requested Muse Spark 1.2 free only
# - muse-spark-1.2-contributor-free (free, requires /v1/responses with @ai-sdk/openai, NOT chat/completions — see issue #44847)
DEFAULT_ZEN_MODEL = "muse-spark-1.2-contributor-free"
DEFAULT_GO_MODEL = "kimi-k2.6"
DEFAULT_FREE_MODEL = "muse-spark-1.2-contributor-free"


def _pick_api_key() -> tuple[str | None, str | None]:
    """Return (api_key, source) where source hints provider."""
    if key := os.getenv("OPENCODE_GO_API_KEY"):
        return key, "go"
    if key := os.getenv("OPENCODE_ZEN_API_KEY"):
        return key, "zen"
    if key := os.getenv("OPENCODE_API_KEY"):
        # Heuristic: if user set a Go base URL, treat as Go
        base_hint = (
            os.getenv("OPENCODE_BASE_URL") or os.getenv("OPENCODE_GO_BASE_URL") or ""
        )
        if "/go" in base_hint:
            return key, "go"
        return key, "zen"
    return None, None


def get_llm_config(model_override: str | None = None) -> dict:
    """
    Resolve LLM credentials + endpoint for ChatOpenAI.

    Returns dict with keys: api_key, base_url (or None for OpenAI direct), model
    """
    api_key, source = _pick_api_key()

    # Explicit base_url overrides take precedence
    base_url = (
        os.getenv("OPENCODE_GO_BASE_URL")
        or os.getenv("OPENCODE_ZEN_BASE_URL")
        or os.getenv("OPENCODE_BASE_URL")
        or os.getenv("OPENCODE_API_BASE")  # legacy alt
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("OPENAI_BASE_URL")
    )

    model = model_override or os.getenv("OPENCODE_MODEL") or os.getenv("OPENAI_MODEL")

    if api_key:
        # Default base_url based on source if not explicitly set
        if not base_url:
            base_url = OPENCODE_GO_BASE_URL if source == "go" else OPENCODE_ZEN_BASE_URL

        # Default model based on provider
        if not model:
            if base_url and "/go" in base_url:
                model = os.getenv("OPENCODE_SMALL_MODEL") or DEFAULT_GO_MODEL
            else:
                model = os.getenv("OPENCODE_SMALL_MODEL") or DEFAULT_ZEN_MODEL

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "provider": "opencode",
        }

    # Fallback: direct OpenAI
    if openai_key := os.getenv("OPENAI_API_KEY"):
        return {
            "api_key": openai_key,
            "base_url": base_url,  # None or explicit proxy
            "model": model or "gpt-4o",
            "provider": "openai",
        }

    raise ValueError(
        "No LLM credentials found. Set one of: "
        "OPENCODE_GO_API_KEY / OPENCODE_ZEN_API_KEY / OPENCODE_API_KEY (https://opencode.ai/auth) "
        "or OPENAI_API_KEY. See https://opencode.ai/docs/zen and https://opencode.ai/docs/go"
    )


def create_chat_openai(**kwargs):
    """
    Factory for langchain_openai.ChatOpenAI pre-wired for Opencode.

    Free models: big-pickle (default, chat/completions) or muse-spark-1.2-contributor-free
    which requires /v1/responses (use_responses_api=True). See https://opencode.ai/docs/zen
    """
    from langchain_openai import ChatOpenAI

    cfg = get_llm_config(model_override=kwargs.pop("model", None))

    # Allow explicit overrides to win over env
    api_key = kwargs.pop("api_key", cfg["api_key"])
    base_url = kwargs.pop("base_url", cfg["base_url"])
    model = kwargs.pop("model", cfg["model"])

    # Sensible defaults (free models are fast, kimi is slow)
    kwargs.setdefault("timeout", 90)
    kwargs.setdefault("max_retries", 2)

    # muse-spark-1.2-contributor-free requires Responses API, not Chat Completions
    # per https://opencode.ai/docs/zen + issue #44847 (500 on /chat/completions, 200 on /responses)
    is_muse_spark = "muse-spark" in model
    if is_muse_spark:
        # Use responses endpoint base without /chat/completions suffix
        if base_url and base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        elif base_url and "/v1" not in base_url:
            base_url = base_url.rstrip("/") + "/v1"
        # Ensure base is https://opencode.ai/zen/v1
        if not base_url or "opencode.ai" not in base_url:
            base_url = OPENCODE_ZEN_BASE_URL
        # ChatOpenAI will route to /responses when model name indicates it or flag is set
        kwargs.setdefault("use_responses_api", True)
        print(
            f"[LLM] provider={cfg['provider']} base_url={base_url} model={model} (responses API) timeout={kwargs.get('timeout')}"
        )
    else:
        print(
            f"[LLM] provider={cfg['provider']} base_url={base_url} model={model} timeout={kwargs.get('timeout')}"
        )

    llm_kwargs = {
        "model": model,
        "api_key": api_key,
        **kwargs,
    }
    if base_url:
        llm_kwargs["base_url"] = base_url

    return ChatOpenAI(**llm_kwargs)
