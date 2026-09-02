"""Voiceover TTS with word timestamps and opposite-language SRT subtitles."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from scripts.cli import PROJECT_ROOT
from scripts.costs import add_video_cost, estimate_cost, load_pricing
from scripts.image_generation import is_flag_checked, parse_script_cell
from scripts.llm import chat_json
from scripts.script_generation import normalize_language
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED, TOPIC_SHEET_COLUMNS

TRANSLATE_SYSTEM = """You translate voice-over segments for subtitles.
Keep the same number of segments, same order, same indexes.
Do not merge or split segments. Translate naturally; do not translate word-by-word.
Return JSON: {"segments": [{"index": 1, "text": "..."}]}.
"""


def opposite_language(language: str) -> str:
    lang = normalize_language(language)
    return "EN" if lang == "FR" else "FR"


def extract_voiceover_text(script: dict[str, Any]) -> dict[str, Any]:
    """Narrator dialogues only, in script order."""
    segments = []
    parts = []
    for i, scene in enumerate(script.get("scenes") or [], start=1):
        text = str(scene.get("dialogue") or scene.get("voiceover") or scene.get("narration") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "index": len(segments) + 1,
                "shot": scene.get("shot") or i,
                "text": text,
                "duration_s": float(scene.get("duration_s") or 0) or None,
            }
        )
        parts.append(text)
    if not parts:
        raise ValueError("No narrator dialogue found in script scenes")
    return {"text": " ".join(parts), "segments": segments}


def resolve_tts(config: dict[str, Any], language: str) -> tuple[str, str, str]:
    lang = normalize_language(language).lower()
    provider = str(config.get("tts_provider") or "elevenlabs").lower()
    if provider == "elevenlabs":
        voices = config.get("elevenlabs_voice_id") or {}
        model = str(config.get("tts_model") or "eleven_multilingual_v2")
    else:
        voices = config.get("tts_voice_id") or config.get("elevenlabs_voice_id") or {}
        model = str(config.get("tts_model") or "tts-1")
    if isinstance(voices, str):
        voice_id = voices
    else:
        voice_id = str(voices.get(lang) or voices.get(lang.upper()) or "")
    if provider in {"openai", "openai_tts"} and (not voice_id or voice_id.startswith("REPLACE_WITH_")):
        voice_id = "nova"
    if not voice_id:
        raise ValueError(f"Missing voice id for language {lang} and provider {provider}")
    return provider, voice_id, model


def characters_to_words(
    characters: list[str],
    starts: list[float],
    ends: list[float],
) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    buf: list[str] = []
    start: float | None = None
    last_end = 0.0
    for ch, s, e in zip(characters, starts, ends):
        last_end = float(e)
        if str(ch).isspace():
            if buf and start is not None:
                words.append({"word": "".join(buf), "start": start, "end": float(e)})
                buf = []
                start = None
            continue
        if start is None:
            start = float(s)
        buf.append(str(ch))
    if buf and start is not None:
        words.append({"word": "".join(buf), "start": start, "end": last_end})
    return words


def _map_segments_to_words(segments: list[dict[str, Any]], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = 0
    mapped = []
    for seg in segments:
        tokens = [t for t in re.findall(r"\S+", seg["text"])]
        if not tokens:
            continue
        take = min(len(tokens), max(1, len(words) - cursor))
        chunk = words[cursor : cursor + take] or words[-1:]
        cursor += take
        mapped.append(
            {
                **seg,
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "words": chunk,
            }
        )
    if mapped and words:
        mapped[-1]["end"] = words[-1]["end"]
        mapped[-1]["words"] = (mapped[-1].get("words") or []) + words[cursor:]
    return mapped


def srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for i, seg in enumerate(segments, start=1):
        start = srt_timestamp(seg.get("start") or 0)
        end = srt_timestamp(seg.get("end") or ((seg.get("start") or 0) + 2))
        if end <= start:
            end = srt_timestamp((seg.get("start") or 0) + 0.5)
        text = str(seg.get("text") or "").strip()
        blocks.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _tts_cost(provider: str, text: str) -> float:
    pricing = load_pricing()
    if provider == "elevenlabs":
        rate = float(pricing.get("elevenlabs", {}).get("tts_per_1k_chars") or 0.12)
        return round(len(text) / 1000 * rate, 4)
    return estimate_cost("tts_openai")


def _dry_run_words(text: str, pace: float = 0.22) -> list[dict[str, Any]]:
    words = []
    t = 0.0
    for token in re.findall(r"\S+", text):
        dur = max(0.12, pace * max(1, len(token) / 5))
        words.append({"word": token, "start": round(t, 3), "end": round(t + dur, 3)})
        t += dur + 0.05
    return words


def generate_voiceover(
    text: str,
    provider: str,
    voice_id: str,
    language: str,
    *,
    model: str | None = None,
    dry_run: bool = False,
    audio_path: Path | None = None,
) -> dict[str, Any]:
    """Synthesize speech and return audio bytes plus word-level timestamps."""
    provider = provider.lower()
    lang = normalize_language(language).lower()
    if dry_run:
        words = _dry_run_words(text)
        payload = {
            "audio_bytes": b"",
            "words": words,
            "provider": provider,
            "voice_id": voice_id,
            "language": lang,
            "cost_eur": 0.0,
            "dry_run": True,
            "alignment_source": "dry-run",
        }
        if audio_path:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"")
            payload["audio_path"] = str(audio_path)
        return payload

    if provider == "elevenlabs":
        result = _elevenlabs_with_timestamps(text, voice_id, model or "eleven_multilingual_v2")
    elif provider in {"openai", "openai_tts"}:
        result = _openai_tts_then_align(text, voice_id, lang, model or "tts-1")
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")

    result["cost_eur"] = _tts_cost(provider, text)
    result["dry_run"] = False
    result["provider"] = provider
    result["voice_id"] = voice_id
    result["language"] = lang
    if audio_path:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(result["audio_bytes"])
        result["audio_path"] = str(audio_path)
    return result


def _elevenlabs_with_timestamps(text: str, voice_id: str, model: str) -> dict[str, Any]:
    import requests

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    if not voice_id or voice_id.startswith("REPLACE_WITH_"):
        raise RuntimeError("elevenlabs_voice_id is not configured")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                headers={"xi-api-key": api_key, "Accept": "application/json", "Content-Type": "application/json"},
                json={"text": text, "model_id": model},
                timeout=120,
            )
            if response.status_code in {429, 500, 502, 503}:
                time.sleep(1.5 * (attempt + 1))
                last_error = RuntimeError(f"ElevenLabs HTTP {response.status_code}")
                continue
            response.raise_for_status()
            data = response.json()
            audio = base64.b64decode(data.get("audio_base64") or "")
            alignment = data.get("normalized_alignment") or data.get("alignment") or {}
            chars = alignment.get("characters") or []
            starts = alignment.get("character_start_times_seconds") or []
            ends = alignment.get("character_end_times_seconds") or []
            words = characters_to_words(chars, starts, ends)
            return {"audio_bytes": audio, "words": words, "alignment_source": "elevenlabs"}
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ElevenLabs TTS failed: {last_error}") from last_error


def _openai_tts_then_align(text: str, voice_id: str, language: str, model: str) -> dict[str, Any]:
    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = OpenAI()
    speech = client.audio.speech.create(model=model, voice=voice_id, input=text)
    audio_bytes = speech.read() if hasattr(speech, "read") else bytes(speech.content)
    words = _align_audio_bytes(audio_bytes, language)
    return {"audio_bytes": audio_bytes, "words": words, "alignment_source": "whisper"}


def _align_audio_bytes(audio_bytes: bytes, language: str) -> list[dict[str, Any]]:
    import tempfile

    suffix = ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        path = tmp.name
    try:
        try:
            return _align_whisper_timestamped(path, language)
        except ImportError:
            return _align_openai_whisper(path, language)
    finally:
        Path(path).unlink(missing_ok=True)


def _align_whisper_timestamped(audio_path: str, language: str) -> list[dict[str, Any]]:
    import whisper_timestamped as whisper  # type: ignore

    audio = whisper.load_audio(audio_path)
    model = whisper.load_model("tiny")
    lang = "fr" if language.lower().startswith("fr") else "en"
    result = whisper.transcribe(model, audio, language=lang)
    words = []
    for segment in result.get("segments") or []:
        for item in segment.get("words") or []:
            token = str(item.get("text") or item.get("word") or "").strip()
            if token:
                words.append(
                    {
                        "word": token,
                        "start": float(item.get("start") or 0),
                        "end": float(item.get("end") or 0),
                    }
                )
    if not words:
        raise RuntimeError("whisper-timestamped returned no words")
    return words


def _align_openai_whisper(audio_path: str, language: str) -> list[dict[str, Any]]:
    from openai import OpenAI

    client = OpenAI()
    lang = "fr" if language.lower().startswith("fr") else "en"
    with open(audio_path, "rb") as fh:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=fh,
            language=lang,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    items = getattr(transcript, "words", None) or []
    if not items and isinstance(transcript, dict):
        items = transcript.get("words") or []
    words = []
    for item in items:
        if hasattr(item, "word"):
            token, start, end = item.word, item.start, item.end
        else:
            token, start, end = item.get("word"), item.get("start"), item.get("end")
        if token:
            words.append({"word": str(token), "start": float(start or 0), "end": float(end or 0)})
    if not words:
        raise RuntimeError("OpenAI whisper returned no word timestamps")
    return words


def translate_segments(
    segments: list[dict[str, Any]],
    *,
    source_language: str,
    target_language: str,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], float]:
    source = normalize_language(source_language)
    target = normalize_language(target_language)
    if dry_run:
        translated = []
        for seg in segments:
            translated.append({**seg, "text": f"[{target}] {seg['text']}", "source_text": seg["text"]})
        return translated, 0.0
    user = (
        f"Source language: {source}. Target language: {target}.\n"
        f"Segments:\n{json.dumps([{'index': s['index'], 'text': s['text']} for s in segments], ensure_ascii=False)}"
    )
    payload, cost = chat_json(TRANSLATE_SYSTEM, user, dry_run=False, cost_step="translation")
    by_index = {int(item.get("index")): str(item.get("text") or "").strip() for item in payload.get("segments") or []}
    translated = []
    for seg in segments:
        text = by_index.get(int(seg["index"])) or seg["text"]
        translated.append({**seg, "text": text, "source_text": seg["text"]})
    return translated, cost


def generate_voiceover_for_row(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    channel: str,
    row_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    status = str(row.get("Statut (À Revoir/Accepté/Rejeté)") or "").strip()
    if status != STATUS_SCRIPT_GENERATED:
        raise ValueError(f"Expected status Script Généré, got {status!r}")
    if not is_flag_checked(row.get("Images Générées")):
        raise ValueError("Images Générées must be checked before voiceover")
    if is_flag_checked(row.get("Voix-off Générée")):
        raise ValueError("Voix-off Générée is already checked")

    language = normalize_language(row.get("Langue (FR/EN)") or config.get("default_language") or "FR")
    target = opposite_language(language)
    script = parse_script_cell(row.get("Script Vidéo Généré"))
    extracted = extract_voiceover_text(script)
    provider, voice_id, model = resolve_tts(config, language)

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(row_id))[:40] or "row"
    out_dir = PROJECT_ROOT / "output" / channel / slug
    audio_path = out_dir / "voiceover.mp3"
    ts_path = out_dir / "timestamps.json"
    srt_path = out_dir / f"subtitles_{target.lower()}.srt"

    tts = generate_voiceover(
        extracted["text"],
        provider,
        voice_id,
        language,
        model=model,
        dry_run=dry_run,
        audio_path=audio_path,
    )
    timed = _map_segments_to_words(extracted["segments"], tts["words"])
    translated, translation_cost = translate_segments(
        timed,
        source_language=language,
        target_language=target,
        dry_run=dry_run,
    )
    srt = segments_to_srt(translated)
    ts_path.parent.mkdir(parents=True, exist_ok=True)
    ts_payload = {
        "language": language,
        "subtitle_language": target,
        "provider": provider,
        "alignment_source": tts.get("alignment_source"),
        "words": tts["words"],
        "segments": timed,
        "translated_segments": translated,
    }
    ts_path.write_text(json.dumps(ts_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    srt_path.write_text(srt, encoding="utf-8")

    def as_url(path: Path) -> str:
        if dry_run:
            return f"https://dry-run.local/{path.relative_to(PROJECT_ROOT).as_posix()}"
        return path.relative_to(PROJECT_ROOT).as_posix()

    cost = round(float(tts.get("cost_eur") or 0) + translation_cost, 4)
    return {
        "language": language,
        "subtitle_language": target,
        "provider": provider,
        "voice_id": voice_id,
        "text": extracted["text"],
        "audio_url": as_url(audio_path),
        "timestamps_url": as_url(ts_path),
        "subtitles_url": as_url(srt_path),
        "segments": timed,
        "translated_segments": translated,
        "srt": srt,
        "cost_eur": cost,
        "dry_run": dry_run,
        "alignment_source": tts.get("alignment_source"),
    }


def apply_voiceover_to_sheet(
    sheet_id: str,
    tab: str,
    row_index: int,
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from scripts.sheets import ensure_headers, update_row_values

    updates = {
        "URL Voix-off": payload.get("audio_url") or "",
        "URL Timestamps": payload.get("timestamps_url") or "",
        "URL Sous-titres (langue opposée)": payload.get("subtitles_url") or "",
        "Voix-off Générée": True,
    }
    result = {"row": row_index, "updates": updates, "cost_eur": payload.get("cost_eur") or 0}
    if dry_run:
        return {**result, "applied": False, "dry_run": True}
    ensure_headers(sheet_id, tab, TOPIC_SHEET_COLUMNS)
    update_row_values(sheet_id, tab, row_index, updates)
    article_url = str(row.get("URL Article") or "")
    if article_url and payload.get("cost_eur"):
        add_video_cost(sheet_id, article_url, float(payload["cost_eur"]), dry_run=False, tab=tab)
    return {**result, "applied": True, "dry_run": False}
