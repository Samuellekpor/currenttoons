#!/usr/bin/env python3
"""Show which live credentials are present. Never prints secret values."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config

load_dotenv(PROJECT_ROOT / ".env")


def _filled(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _row(ok: bool, label: str, hint: str = "") -> None:
    mark = "OK" if ok else "MISSING"
    extra = f"  — {hint}" if hint and not ok else ""
    print(f"[{mark}] {label}{extra}")


def main() -> int:
    parser = build_parser("Check live setup without printing secrets")
    parser.parse_args()

    print("Local")
    _row((PROJECT_ROOT / ".env").exists(), ".env file")
    _row(shutil.which("ffmpeg") is not None, "ffmpeg on PATH")
    print()
    print("Minimum to make a real video")
    from scripts.ai_client import ai_api_key, uses_aimlapi

    _row(bool(ai_api_key()), "AIMLAPI_KEY or OPENAI_API_KEY", "chat / scripts / TTS fallback")
    _row(_filled("NEWSAPI_KEY"), "NEWSAPI_KEY", "CurrentToons news")
    images = uses_aimlapi() or _filled("REPLICATE_API_TOKEN") or _filled("FAL_KEY")
    _row(images, "Image provider", "AIMLAPI, Replicate, or fal")
    eleven = _filled("ELEVENLABS_API_KEY") or uses_aimlapi()
    _row(eleven, "Voice (ElevenLabs or AIMLAPI TTS fallback)")
    cred = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH") or ""
    _row(bool(cred) and Path(cred).expanduser().exists(), "GOOGLE_SHEETS_CREDENTIALS_PATH file")
    _row(_filled("CURRENTTOONS_SHEET_ID"), "CURRENTTOONS_SHEET_ID")
    _row(_filled("HABITLENS_SHEET_ID"), "HABITLENS_SHEET_ID", "optional if you only run CurrentToons")

    current = load_channel_config("currenttoons")
    voices = current.get("elevenlabs_voice_id") or {}
    fr_ok = bool(voices.get("fr")) and not str(voices.get("fr")).startswith("REPLACE_WITH_")
    en_ok = bool(voices.get("en")) and not str(voices.get("en")).startswith("REPLACE_WITH_")
    fallback = uses_aimlapi() and bool((current.get("tts_voice_id") or {}).get("fr"))
    _row(fr_ok or fallback, "CurrentToons voice FR (ElevenLabs ID or AIMLAPI nova)")
    _row(en_ok or fallback, "CurrentToons voice EN (ElevenLabs ID or AIMLAPI onyx)")

    print()
    print("Later: publish to social (not needed for the first video)")
    _row(_filled("YOUTUBE_CLIENT_ID"), "YouTube OAuth")
    _row(_filled("TIKTOK_ACCESS_TOKEN"), "TikTok")
    _row(_filled("INSTAGRAM_ACCESS_TOKEN") and _filled("INSTAGRAM_USER_ID"), "Instagram")
    _row(_filled("TELEGRAM_BOT_TOKEN") and _filled("TELEGRAM_CHAT_ID"), "Telegram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
