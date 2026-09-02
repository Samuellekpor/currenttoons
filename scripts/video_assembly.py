"""Assemble a final video (short 9:16 or long 16:9) with burned-in opposite-language subtitles."""

from __future__ import annotations

import json
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.cli import PROJECT_ROOT
from scripts.costs import add_video_cost, estimate_cost
from scripts.image_generation import is_flag_checked, parse_script_cell
from scripts.script_generation import FORMAT_SPECS, normalize_format
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED, TOPIC_SHEET_COLUMNS
from scripts.voiceover import segments_to_srt

TRANSITION_S = 0.25
MUSIC_VOLUME_DEFAULT = 0.12

# 1x1 PNG (red) used as a dry-run still.
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


@dataclass
class Clip:
    path: Path
    start: float
    duration: float
    shot: int
    title: str = ""


def ffmpeg_cmd() -> str | None:
    return shutil.which("ffmpeg")


def parse_image_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return []
        items = json.loads(text)
        if isinstance(items, dict):
            items = items.get("images") or items.get("urls") or []
    out = []
    for i, item in enumerate(items, start=1):
        if isinstance(item, str):
            out.append({"shot": i, "url": item})
        else:
            url = item.get("url") or item.get("path") or ""
            if url:
                out.append({"shot": int(item.get("shot") or i), "url": url})
    return out


def youtube_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def chapters_from_clips(clips: list[Clip], video_format: str) -> list[dict[str, Any]]:
    if not clips:
        return []
    group = 1 if video_format == "Court" else 3
    chapters = []
    for i in range(0, len(clips), group):
        chunk = clips[i : i + group]
        idx = len(chapters) + 1
        title = chunk[0].title or (f"Chapitre {idx}" if video_format == "Long" else f"Plan {idx}")
        chapters.append(
            {
                "index": idx,
                "title": title,
                "start": chunk[0].start,
                "end": chunk[-1].start + chunk[-1].duration,
            }
        )
    return chapters


def youtube_chapters_text(chapters: list[dict[str, Any]]) -> str:
    lines = []
    for ch in chapters:
        lines.append(f"{youtube_timestamp(ch['start'])} {ch['title']}")
    return "\n".join(lines) + ("\n" if lines else "")


def ffmetadata_chapters(chapters: list[dict[str, Any]]) -> str:
    blocks = [";FFMETADATA1"]
    for ch in chapters:
        start_ms = int(ch["start"] * 1000)
        end_ms = int(ch["end"] * 1000)
        title = str(ch["title"]).replace("=", "\\=").replace(";", "\\;")
        blocks.append(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={end_ms}\ntitle={title}")
    return "\n".join(blocks) + "\n"


def plan_clips(
    image_paths: list[tuple[int, Path]],
    timestamps: dict[str, Any],
    audio_duration: float,
) -> list[Clip]:
    segments = list(timestamps.get("segments") or [])
    clips: list[Clip] = []
    if not image_paths:
        raise ValueError("No images to assemble")
    if segments:
        for i, (shot, path) in enumerate(image_paths):
            if i < len(segments):
                seg = segments[i]
                start = float(seg.get("start") or 0)
                end = float(seg.get("end") or start + 2)
            else:
                prev = clips[-1]
                start = prev.start + prev.duration
                end = start + max(1.0, audio_duration / len(image_paths))
            clips.append(Clip(path=path, start=start, duration=max(0.4, end - start), shot=shot))
    else:
        each = max(0.8, audio_duration / len(image_paths))
        t = 0.0
        for shot, path in image_paths:
            clips.append(Clip(path=path, start=t, duration=each, shot=shot))
            t += each
    total = sum(c.duration for c in clips) or 1.0
    if audio_duration > 0:
        factor = audio_duration / total
        t = 0.0
        fitted = []
        for clip in clips:
            duration = max(0.4, clip.duration * factor)
            fitted.append(Clip(path=clip.path, start=t, duration=duration, shot=clip.shot, title=clip.title))
            t += duration
        clips = fitted
    return clips


def _write_silence_wav(path: Path, duration: float = 4.0, rate: int = 44100) -> None:
    n = max(1, int(rate * duration))
    with wave.open(str(path), "w") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(b"\x00\x00" * n)


def _resolve_path(url: str) -> Path | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    if raw.startswith("https://dry-run.local/"):
        rel = raw.split("https://dry-run.local/", 1)[1]
        candidate = PROJECT_ROOT / rel
        return candidate if candidate.exists() else None
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return None
    path = Path(raw)
    if path.is_absolute() and path.exists():
        return path
    candidate = PROJECT_ROOT / raw
    return candidate if candidate.exists() else None


def materialize_asset(url: str, dest: Path, *, kind: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    local = _resolve_path(url)
    if local and local.exists():
        if local.resolve() != dest.resolve():
            shutil.copyfile(local, dest)
            return dest
        return local
    if str(url).startswith(("http://", "https://")) and "dry-run.local" not in url:
        import requests

        response = requests.get(url, timeout=60)
        response.raise_for_status()
        dest.write_bytes(response.content)
        return dest
    if kind == "image":
        dest.write_bytes(_TINY_PNG)
    elif kind == "audio":
        _write_silence_wav(dest, 4.0)
    elif kind == "srt":
        dest.write_text(segments_to_srt([{"text": "Dry-run subtitle", "start": 0, "end": 2}]), encoding="utf-8")
    elif kind == "json":
        dest.write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "x"}]}), encoding="utf-8")
    else:
        dest.write_bytes(b"")
    return dest


def _escape_subtitles_path(path: Path) -> str:
    text = path.resolve().as_posix()
    return text.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")


def run_ffmpeg_assembly(
    clips: list[Clip],
    *,
    voice_path: Path,
    srt_path: Path | None,
    music_path: Path | None,
    music_volume: float,
    width: int,
    height: int,
    output_path: Path,
    chapters_meta: Path | None = None,
) -> None:
    import ffmpeg

    cmd = ffmpeg_cmd()
    if not cmd:
        raise FileNotFoundError("ffmpeg is not installed (required for video assembly)")

    fade = TRANSITION_S
    streams = []
    for clip in clips:
        fade_d = min(fade, max(0.05, clip.duration / 4))
        out_start = max(0.0, clip.duration - fade_d)
        video = ffmpeg.input(str(clip.path), loop=1, t=clip.duration, framerate=30)
        video = (
            video.video.filter("scale", width, height, force_original_aspect_ratio="decrease")
            .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2", "black")
            .filter("fps", 30)
            .filter("format", "yuv420p")
            .filter("fade", type="in", start_time=0, duration=fade_d)
            .filter("fade", type="out", start_time=out_start, duration=fade_d)
        )
        streams.append(video)
    joined = ffmpeg.concat(*streams, v=1, a=0) if len(streams) > 1 else streams[0]
    if srt_path and srt_path.exists() and srt_path.stat().st_size > 0:
        joined = joined.filter(
            "subtitles",
            _escape_subtitles_path(srt_path),
            force_style="FontName=Arial,FontSize=18,Alignment=2,Outline=2,MarginV=48,PrimaryColour=&H00FFFFFF",
        )

    voice = ffmpeg.input(str(voice_path)).audio
    if music_path and music_path.exists():
        total = sum(c.duration for c in clips)
        music = ffmpeg.input(str(music_path), stream_loop=-1, t=total).audio.filter("volume", music_volume)
        audio = ffmpeg.filter([voice, music], "amix", inputs=2, duration="first", dropout_transition=0)
    else:
        audio = voice

    output_path.parent.mkdir(parents=True, exist_ok=True)
    extra = {}
    kwargs = dict(
        vcodec="libx264",
        acodec="aac",
        pix_fmt="yuv420p",
        shortest=None,
        movflags="+faststart",
        **extra,
    )
    out = ffmpeg.output(joined, audio, str(output_path), **kwargs)
    ffmpeg.run(out, cmd=cmd, overwrite_output=True, quiet=True)


def assemble_video_for_row(
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
        raise ValueError("Images Générées must be checked before assembly")
    if not is_flag_checked(row.get("Voix-off Générée")):
        raise ValueError("Voix-off Générée must be checked before assembly")
    if is_flag_checked(row.get("Vidéo Montée")):
        raise ValueError("Vidéo Montée is already checked")

    video_format = normalize_format(row.get("Format Vidéo (Court/Long)") or "Court")
    spec = FORMAT_SPECS[video_format]
    width, height = spec["width"], spec["height"]
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(row_id))[:40] or "row"
    work_dir = PROJECT_ROOT / "assets_temp" / "assembly" / channel / slug
    out_dir = PROJECT_ROOT / "output" / channel / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    images = parse_image_list(row.get("URLs Images"))
    if dry_run and not images:
        images = [{"shot": i, "url": f"https://dry-run.local/img/{i}.png"} for i in range(1, 4)]

    image_paths = []
    for item in images:
        dest = work_dir / f"shot_{item['shot']}.png"
        path = materialize_asset(item["url"], dest, kind="image")
        image_paths.append((item["shot"], path))

    voice_path = materialize_asset(
        str(row.get("URL Voix-off") or ""),
        work_dir / "voiceover.wav",
        kind="audio",
    )
    ts_src = str(row.get("URL Timestamps") or "")
    ts_path = materialize_asset(ts_src, work_dir / "timestamps.json", kind="json")
    timestamps = json.loads(ts_path.read_text(encoding="utf-8")) if ts_path.exists() else {"segments": []}
    audio_duration = 0.0
    segs = timestamps.get("segments") or []
    if segs:
        audio_duration = float(segs[-1].get("end") or 0)
    if audio_duration <= 0:
        audio_duration = sum(float(s.get("duration_s") or 2) for s in (parse_script_cell(row.get("Script Vidéo Généré") or "{}").get("scenes") or [])) or 6.0

    srt_path = materialize_asset(
        str(row.get("URL Sous-titres (langue opposée)") or ""),
        work_dir / "subtitles.srt",
        kind="srt",
    )

    clips = plan_clips(image_paths, timestamps, audio_duration)
    script = {}
    try:
        script = parse_script_cell(row.get("Script Vidéo Généré") or "{}")
    except (ValueError, json.JSONDecodeError):
        script = {}
    scenes = {int(s.get("shot") or i): s for i, s in enumerate(script.get("scenes") or [], start=1)}
    for clip in clips:
        scene = scenes.get(clip.shot) or {}
        clip.title = str(scene.get("chapter") or scene.get("title") or "")

    chapters = chapters_from_clips(clips, video_format)
    chapters_txt = out_dir / "chapters.txt"
    chapters_txt.write_text(youtube_chapters_text(chapters), encoding="utf-8")
    meta_path = work_dir / "ffmetadata.txt"
    meta_path.write_text(ffmetadata_chapters(chapters), encoding="utf-8")

    music_url = str(config.get("background_music_url") or "")
    music_path = None
    if music_url:
        music_path = materialize_asset(music_url, work_dir / "music.mp3", kind="audio")
    volume = float(config.get("background_music_volume") or MUSIC_VOLUME_DEFAULT)

    output_path = out_dir / "final.mp4"
    encoded_with_ffmpeg = False
    try:
        run_ffmpeg_assembly(
            clips,
            voice_path=voice_path,
            srt_path=srt_path,
            music_path=music_path,
            music_volume=volume,
            width=width,
            height=height,
            output_path=output_path,
            chapters_meta=meta_path if video_format == "Long" else None,
        )
        encoded_with_ffmpeg = True
    except FileNotFoundError:
        if not dry_run:
            raise
        output_path.write_bytes(b"dry-run-mp4-placeholder")
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    rel = output_path.relative_to(PROJECT_ROOT).as_posix()
    video_url = f"https://dry-run.local/{rel}" if dry_run else rel
    return {
        "format": video_format,
        "width": width,
        "height": height,
        "clips": [{"shot": c.shot, "start": c.start, "duration": round(c.duration, 3)} for c in clips],
        "chapters": chapters,
        "chapters_url": (f"https://dry-run.local/{chapters_txt.relative_to(PROJECT_ROOT).as_posix()}" if dry_run else chapters_txt.relative_to(PROJECT_ROOT).as_posix()),
        "video_url": video_url,
        "subtitles_burned": True,
        "encoded_with_ffmpeg": encoded_with_ffmpeg,
        "cost_eur": 0.0 if dry_run else estimate_cost("video_assembly"),
        "dry_run": dry_run,
    }


def apply_video_to_sheet(
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
        "URL Vidéo Finale": payload.get("video_url") or "",
        "Vidéo Montée": True,
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
