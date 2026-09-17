"""OpenAI-compatible client. AIMLAPI is the preferred single key."""

from __future__ import annotations

import os

AIMLAPI_BASE_URL = "https://api.aimlapi.com/v1"


def ai_api_key() -> str:
    return (
        (os.environ.get("AIMLAPI_KEY") or os.environ.get("AIMLAPI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
        .strip()
    )


def uses_aimlapi() -> bool:
    if (os.environ.get("AIMLAPI_KEY") or os.environ.get("AIMLAPI_API_KEY") or "").strip():
        return True
    base = (os.environ.get("OPENAI_BASE_URL") or "").lower()
    return "aimlapi.com" in base and bool(ai_api_key())


def openai_client():
    """Chat / OpenAI-compatible calls. Points at AIMLAPI when AIMLAPI_KEY is set."""
    from openai import OpenAI

    key = ai_api_key()
    if not key:
        raise RuntimeError("Set AIMLAPI_KEY (or OPENAI_API_KEY)")
    kwargs: dict[str, str] = {"api_key": key}
    if uses_aimlapi():
        kwargs["base_url"] = (os.environ.get("OPENAI_BASE_URL") or AIMLAPI_BASE_URL).rstrip("/")
    elif os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"].rstrip("/")
    return OpenAI(**kwargs)
