"""Load per-channel JSON configuration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

REQUIRED_FIELDS = (
    "channel_name",
    "google_sheet_id",
    "tone_prompt",
    "script_system_prompt_path",
    "image_style_prompt_path",
    "uses_caricatures",
    "default_language",
    "supported_languages",
    "default_format",
)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def channel_config_path(slug: str) -> Path:
    return PROJECT_ROOT / "channels" / f"{slug}.config.json"


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_channel_config(slug: str) -> dict[str, Any]:
    path = channel_config_path(slug)
    if not path.exists():
        raise FileNotFoundError(f"Channel config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data = _expand_env(data)
    sheet_id = str(data.get("google_sheet_id") or "")
    if sheet_id.startswith("REPLACE_WITH_") or sheet_id.startswith("${"):
        from_env = os.environ.get(f"{slug.upper()}_SHEET_ID")
        if from_env:
            data["google_sheet_id"] = from_env
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValueError(f"{path.name} missing fields: {', '.join(missing)}")
    if "elevenlabs_voice_id" not in data and "tts_provider" not in data:
        raise ValueError(f"{path.name} needs elevenlabs_voice_id or tts_provider")
    return data


def read_prompt(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    return path.read_text(encoding="utf-8").strip()
