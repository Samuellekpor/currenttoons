"""Load per-channel JSON configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.cli import PROJECT_ROOT

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


def channel_config_path(slug: str) -> Path:
    return PROJECT_ROOT / "channels" / f"{slug}.config.json"


def load_channel_config(slug: str) -> dict[str, Any]:
    path = channel_config_path(slug)
    if not path.exists():
        raise FileNotFoundError(f"Channel config not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ValueError(f"{path.name} missing fields: {', '.join(missing)}")
    if "elevenlabs_voice_id" not in data and "tts_provider" not in data:
        raise ValueError(f"{path.name} needs elevenlabs_voice_id or tts_provider")
    return data


def read_prompt(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    return path.read_text(encoding="utf-8").strip()
