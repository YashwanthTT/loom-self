"""
Opencode Go ($10/mo) + Zen fallback. Fixed to handle muse-spark vs kimi correctly.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    for _env in (".env", ".env.example"):
        _p = Path(__file__).resolve().parent.parent / _env
        if _p.exists():
            load_dotenv(_p, override=False)
            break
except ImportError:
    pass

OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"
DEFAULT_ZEN_MODEL = "muse-spark-1.2-contributor-free"
DEFAULT_GO_MODEL = "kimi-k2.6"


def _pick_key() -> tuple[str | None, str | None]:
    if k := os.getenv("OPENCODE_GO_API_KEY"):
        return k, "go"
    if k := os.getenv("OPENCODE_ZEN_API_KEY"):
        return k, "zen"
    if k := os.getenv("OPENCODE_API_KEY"):
        # if Go base forced, treat as Go, else Zen
        hint = os.getenv("OPENCODE_GO_BASE_URL") or os.getenv("OPENCODE_BASE_URL") or ""
        if "/go" in hint:
            return k, "go"
        # legacy: if model is kimi, assume Go
        if "kimi" in (os.getenv("OPENCODE_MODEL") or ""):
            return k, "go"
        return k, "zen"
    return None, None


def get_llm_config(model_override: str | None = None) -> dict:
    api_key, source = _pick_key()
    base_url = os.getenv("OPENCODE_GO_BASE_URL") or os.getenv("OPENCODE_ZEN_BASE_URL") or os.getenv("OPENCODE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = model_override or os.getenv("OPENCODE_MODEL") or os.getenv("OPENAI_MODEL")

    if api_key:
        if not base_url:
            base_url = OPENCODE_GO_BASE_URL if source == "go" else OPENCODE_ZEN_BASE_URL
        if not model:
            model = DEFAULT_GO_MODEL if source == "go" or (base_url and "/go" in base_url) else DEFAULT_ZEN_MODEL
        # mismatch: muse-spark on Go endpoint → auto-fix
        if source == "go" and "muse-spark" in model:
            # user has Go key but asked for free model → switch to kimi, warn
            print(f"[inference] WARN: muse-spark not on Go (401). Using {DEFAULT_GO_MODEL} instead. Fix: set OPENCODE_MODEL={DEFAULT_GO_MODEL} in .env")
            model = DEFAULT_GO_MODEL
            base_url = OPENCODE_GO_BASE_URL
        # mismatch: kimi on Zen free key → also fix
        if source == "zen" and "kimi" in model and os.getenv("OPENCODE_API_KEY") == "public":
            print(f"[inference] WARN: kimi needs Go subscription. Using {DEFAULT_ZEN_MODEL}")
            model = DEFAULT_ZEN_MODEL
            base_url = OPENCODE_ZEN_BASE_URL
        return {"api_key": api_key, "base_url": base_url, "model": model, "provider": "opencode-go" if source == "go" else "opencode-zen"}

    if openai_key := os.getenv("OPENAI_API_KEY"):
        return {"api_key": openai_key, "base_url": base_url, "model": model or "gpt-4o", "provider": "openai"}

    raise ValueError("Set OPENCODE_GO_API_KEY (Go $10) or OPENCODE_API_KEY (Zen) — https://opencode.ai/auth")


def create_chat_openai(**kwargs):
    from langchain_openai import ChatOpenAI

    cfg = get_llm_config(model_override=kwargs.pop("model", None))
    api_key = kwargs.pop("api_key", cfg["api_key"])
    base_url = kwargs.pop("base_url", cfg["base_url"])
    model = kwargs.pop("model", cfg["model"])

    kwargs.setdefault("timeout", 90)
    kwargs.setdefault("max_retries", 2)

    if "muse-spark" in model:
        if base_url and base_url.endswith("/chat/completions"):
            base_url = base_url.replace("/chat/completions", "")
        elif base_url and "/v1" not in base_url:
            base_url = base_url.rstrip("/") + "/v1"
        if not base_url or "opencode.ai" not in base_url:
            base_url = OPENCODE_ZEN_BASE_URL
        kwargs.setdefault("use_responses_api", True)

    print(f"[inference] provider={cfg['provider']} base_url={base_url} model={model}")
    llm_kwargs = {"model": model, "api_key": api_key, **kwargs}
    if base_url:
        llm_kwargs["base_url"] = base_url
    return ChatOpenAI(**llm_kwargs)
