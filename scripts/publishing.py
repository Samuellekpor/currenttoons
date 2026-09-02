"""Draft uploads (unlisted / private) then a human-gated public publish."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from scripts.cli import PROJECT_ROOT
from scripts.config import read_prompt
from scripts.costs import add_video_cost
from scripts.image_generation import is_flag_checked, parse_script_cell
from scripts.llm import chat_json
from scripts.script_generation import normalize_format, normalize_language
from scripts.topic_analysis import (
    STATUS_PENDING_VALIDATION,
    STATUS_PUBLISHED,
    TOPIC_SHEET_COLUMNS,
)

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
)
AI_DISCLOSURE = "Contenu généré par IA / AI-generated content"


def resolve_media_path(url: str) -> Path | None:
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


def state_path(channel: str, row_id: str) -> Path:
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(row_id))[:40] or "row"
    return PROJECT_ROOT / "output" / channel / slug / "publish_state.json"


def load_state(channel: str, row_id: str) -> dict[str, Any]:
    path = state_path(channel, row_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(channel: str, row_id: str, payload: dict[str, Any]) -> Path:
    path = state_path(channel, row_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _subtitle_note(language: str) -> str:
    return "English subtitles available" if normalize_language(language) == "FR" else "Sous-titres français disponibles"


def build_youtube_description(body: str, language: str, chapters_text: str = "") -> str:
    parts = [body.strip(), "", _subtitle_note(language), AI_DISCLOSURE]
    if chapters_text.strip():
        parts.extend(["", chapters_text.strip()])
    return "\n".join(parts).strip() + "\n"


def generate_seo_metadata(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    video_format: str,
    dry_run: bool = False,
) -> tuple[dict[str, Any], float]:
    language = normalize_language(row.get("Langue (FR/EN)") or config.get("default_language") or "FR")
    system = read_prompt("prompts/seo_metadata.md")
    title_hint = row.get("Titre Vidéo Suggéré") or row.get("Titre Article Original") or ""
    try:
        script = parse_script_cell(row.get("Script Vidéo Généré") or "{}")
        angle = str(script.get("title") or row.get("Angle Proposé") or "")
    except (ValueError, json.JSONDecodeError):
        angle = str(row.get("Angle Proposé") or "")
    user = (
        f"Language: {language}\nFormat: {video_format}\nChannel: {config.get('channel_name')}\n"
        f"Suggested title: {title_hint}\nAngle: {angle}\n"
    )
    dry_payload = {
        "title": title_hint or ("Short dry-run" if video_format == "Court" else "Long dry-run"),
        "description": "Description factice dry-run.",
        "hashtags": ["#dryrun", "#ia"],
        "tags": ["dry-run", "actualite"],
        "twitter_text": f"{title_hint} #dryrun",
        "instagram_caption": f"{title_hint} #dryrun",
    }
    payload, cost = chat_json(
        system,
        user,
        dry_run=dry_run,
        dry_run_payload=dry_payload,
        cost_step="seo_metadata",
    )
    title = str(payload.get("title") or title_hint or config.get("channel_name")).strip()
    if video_format == "Court" and "#shorts" not in title.lower() and "short" not in title.lower():
        title = f"{title} #Shorts"
    description = build_youtube_description(str(payload.get("description") or ""), language)
    hashtags = payload.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = [p.strip() for p in tags.split(",") if p.strip()]
    if "IA" not in tags and "AI" not in tags:
        tags.append("IA")
    return {
        "title": title[:100],
        "description": description,
        "hashtags": hashtags,
        "tags": [str(t).lstrip("#") for t in tags][:12],
        "twitter_text": str(payload.get("twitter_text") or title)[:280],
        "instagram_caption": str(payload.get("instagram_caption") or title),
        "language": language,
        "contains_synthetic_media": True,
        "ai_disclosure": AI_DISCLOSURE,
        "cost_eur": cost,
    }, cost


def upload_youtube_unlisted(
    video_path: Path,
    metadata: dict[str, Any],
    *,
    video_format: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return {
            "id": "dry-run-yt-id",
            "url": "https://youtu.be/dry-run-yt-id",
            "privacy": "unlisted",
            "containsSyntheticMedia": True,
            "dry_run": True,
        }
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    token_path = Path(os.environ.get("YOUTUBE_TOKEN_PATH") or PROJECT_ROOT / "token.json")
    if not token_path.exists():
        raise RuntimeError("YouTube OAuth token missing (YOUTUBE_TOKEN_PATH / token.json)")
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=list(YOUTUBE_SCOPES))
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": metadata.get("tags") or [],
            "categoryId": "25" if video_format == "Court" else "24",
            "defaultLanguage": "fr" if metadata.get("language") == "FR" else "en",
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    try:
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
    except Exception:
        body["status"].pop("containsSyntheticMedia", None)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
    video_id = response["id"]
    return {
        "id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy": "unlisted",
        "containsSyntheticMedia": True,
        "dry_run": False,
    }


def set_youtube_privacy(video_id: str, privacy: str, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"id": video_id, "privacy": privacy, "dry_run": True}
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = Path(os.environ.get("YOUTUBE_TOKEN_PATH") or PROJECT_ROOT / "token.json")
    creds = Credentials.from_authorized_user_file(str(token_path), scopes=list(YOUTUBE_SCOPES))
    youtube = build("youtube", "v3", credentials=creds)
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": privacy, "containsSyntheticMedia": True}},
    ).execute()
    return {"id": video_id, "privacy": privacy, "dry_run": False}


def upload_tiktok_draft(
    video_path: Path,
    metadata: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return {"id": "dry-run-tt", "url": "https://www.tiktok.com/@dry-run/video/0", "privacy_level": "SELF_ONLY", "dry_run": True}
    token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN is not set")
    size = video_path.stat().st_size
    init = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
        },
        timeout=60,
    )
    init.raise_for_status()
    data = (init.json().get("data") or {})
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id")
    if upload_url:
        with video_path.open("rb") as fh:
            put = requests.put(
                upload_url,
                data=fh,
                headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                timeout=300,
            )
            put.raise_for_status()
    return {"id": publish_id, "url": "", "privacy_level": "SELF_ONLY", "dry_run": False}


def publish_tiktok_public(video_path: Path, metadata: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"id": "dry-run-tt-public", "privacy_level": "PUBLIC_TO_EVERYONE", "dry_run": True}
    token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("TIKTOK_ACCESS_TOKEN is not set")
    size = video_path.stat().st_size
    init = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": {
                "title": metadata.get("title") or "",
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
        },
        timeout=60,
    )
    init.raise_for_status()
    data = init.json().get("data") or {}
    upload_url = data.get("upload_url")
    if upload_url:
        with video_path.open("rb") as fh:
            requests.put(upload_url, data=fh, headers={"Content-Type": "video/mp4", "Content-Length": str(size)}, timeout=300).raise_for_status()
    return {"id": data.get("publish_id"), "privacy_level": "PUBLIC_TO_EVERYONE", "dry_run": False}


def create_instagram_container(
    metadata: dict[str, Any],
    *,
    public_video_url: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return {"id": "dry-run-ig-container", "published": False, "dry_run": True}
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    user_id = os.environ.get("INSTAGRAM_USER_ID")
    if not token or not user_id:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID are required")
    if not public_video_url:
        return {"id": None, "published": False, "skipped": "PUBLIC_ASSET_BASE_URL missing", "dry_run": False}
    response = requests.post(
        f"https://graph.facebook.com/v21.0/{user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": public_video_url,
            "caption": metadata.get("instagram_caption") or metadata.get("title"),
            "share_to_feed": "true",
            "access_token": token,
        },
        timeout=120,
    )
    response.raise_for_status()
    return {"id": response.json().get("id"), "published": False, "dry_run": False}


def publish_instagram_container(container_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"id": container_id, "url": "https://www.instagram.com/reel/dry-run/", "published": True, "dry_run": True}
    if not container_id:
        return {"id": None, "published": False, "skipped": True}
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    user_id = os.environ.get("INSTAGRAM_USER_ID")
    response = requests.post(
        f"https://graph.facebook.com/v21.0/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=120,
    )
    response.raise_for_status()
    media_id = response.json().get("id")
    return {"id": media_id, "url": f"https://www.instagram.com/reel/{media_id}/", "published": True, "dry_run": False}


def post_to_x(text: str, *, dry_run: bool = False, enabled: bool = False) -> dict[str, Any]:
    if not enabled:
        return {"skipped": True, "reason": "x_auto_publish is false"}
    if dry_run:
        return {"id": "dry-run-x", "text": text, "dry_run": True}
    token = os.environ.get("TWITTER_BEARER_TOKEN") or os.environ.get("TWITTER_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("TWITTER_BEARER_TOKEN or TWITTER_ACCESS_TOKEN is not set")
    response = requests.post(
        "https://api.x.com/2/tweets",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"text": text},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json().get("data") or {}
    return {"id": data.get("id"), "dry_run": False}


def send_telegram_validation(
    *,
    title: str,
    youtube_url: str,
    channel: str,
    video_format: str,
    language: str,
    cost: Any,
    confirm_url: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    text = (
        f"Validation publication\n"
        f"Chaîne: {channel}\n"
        f"Titre: {title}\n"
        f"Format: {video_format} · Langue: {language}\n"
        f"Coût estimé: {cost} €\n"
        f"Preview YouTube: {youtube_url}\n"
        f"{AI_DISCLOSURE}"
    )
    if dry_run:
        return {"dry_run": True, "text": text, "confirm_url": confirm_url}
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if confirm_url:
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": "✅ Publier (YouTube public + TikTok + IG)", "url": confirm_url}]]}
            )
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=30)
        response.raise_for_status()
        return {"dry_run": False, "telegram": response.json().get("ok")}
    email_to = os.environ.get("NOTIFY_EMAIL")
    if email_to:
        return _send_validation_email(email_to, text, confirm_url)
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or NOTIFY_EMAIL")


def _send_validation_email(to_addr: str, text: str, confirm_url: str) -> dict[str, Any]:
    import smtplib
    from email.message import EmailMessage

    host = os.environ.get("SMTP_HOST") or "localhost"
    port = int(os.environ.get("SMTP_PORT") or "587")
    user = os.environ.get("SMTP_USER") or ""
    password = os.environ.get("SMTP_PASSWORD") or ""
    from_addr = os.environ.get("SMTP_FROM") or user or "noreply@localhost"
    message = EmailMessage()
    message["Subject"] = "Validation publication CurrentToons"
    message["From"] = from_addr
    message["To"] = to_addr
    body = text
    if confirm_url:
        body += f"\n\nPublier: {confirm_url}"
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)
    return {"dry_run": False, "email": True}


def confirm_url(channel: str, row_id: str) -> str:
    base = (os.environ.get("PUBLISH_WEBHOOK_URL") or "").rstrip("/")
    secret = os.environ.get("PUBLISH_WEBHOOK_SECRET") or ""
    if not base:
        return ""
    return f"{base}?channel={channel}&row_id={row_id}&secret={secret}"


def public_video_url(relative_or_local: str) -> str | None:
    base = (os.environ.get("PUBLIC_ASSET_BASE_URL") or "").rstrip("/")
    if not base:
        return None
    rel = relative_or_local.replace("https://dry-run.local/", "")
    return f"{base}/{rel.lstrip('/')}"


def prepare_and_upload_drafts(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    channel: str,
    row_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not is_flag_checked(row.get("Vidéo Montée")):
        raise ValueError("Vidéo Montée must be checked before publishing")
    if is_flag_checked(row.get("Publiée")):
        raise ValueError("Publiée is already checked")
    status = str(row.get("Statut (À Revoir/Accepté/Rejeté)") or "").strip()
    if status == STATUS_PENDING_VALIDATION:
        raise ValueError("Already waiting for validation")
    if status == STATUS_PUBLISHED:
        raise ValueError("Already published")

    video_format = normalize_format(row.get("Format Vidéo (Court/Long)") or "Court")
    language = normalize_language(row.get("Langue (FR/EN)") or "FR")
    video_path = resolve_media_path(str(row.get("URL Vidéo Finale") or ""))
    if not video_path or not video_path.exists():
        if dry_run:
            video_path = PROJECT_ROOT / "output" / channel / str(row_id) / "final.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            if not video_path.exists():
                video_path.write_bytes(b"dry-run-mp4-placeholder")
        else:
            raise FileNotFoundError("Final video file not found (URL Vidéo Finale)")

    chapters = ""
    chapters_file = video_path.parent / "chapters.txt"
    if video_format == "Long" and chapters_file.exists():
        chapters = chapters_file.read_text(encoding="utf-8")

    metadata, seo_cost = generate_seo_metadata(row, config=config, video_format=video_format, dry_run=dry_run)
    if chapters:
        metadata["description"] = build_youtube_description(
            metadata["description"].split(AI_DISCLOSURE)[0].replace(_subtitle_note(language), "").strip(),
            language,
            chapters,
        )

    youtube = upload_youtube_unlisted(video_path, metadata, video_format=video_format, dry_run=dry_run)
    tiktok = upload_tiktok_draft(video_path, metadata, dry_run=dry_run)
    try:
        rel = video_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = video_path.name
    ig = create_instagram_container(
        metadata,
        public_video_url=public_video_url(rel),
        dry_run=dry_run,
    )
    tweet_text = metadata["twitter_text"]
    if youtube.get("url"):
        tweet_text = f"{tweet_text}\n{youtube['url']}"
    twitter = post_to_x(tweet_text[:280], dry_run=dry_run, enabled=bool(config.get("x_auto_publish")))

    state = {
        "channel": channel,
        "row_id": row_id,
        "video_path": str(video_path),
        "metadata": metadata,
        "youtube": youtube,
        "tiktok": tiktok,
        "instagram": ig,
        "twitter": twitter,
        "format": video_format,
        "language": language,
    }
    save_state(channel, row_id, state)
    telegram = send_telegram_validation(
        title=metadata["title"],
        youtube_url=youtube.get("url") or "",
        channel=config.get("channel_name") or channel,
        video_format=video_format,
        language=language,
        cost=row.get("Coût Estimé (€)") or seo_cost,
        confirm_url=confirm_url(channel, row_id),
        dry_run=dry_run,
    )
    return {
        "status": STATUS_PENDING_VALIDATION,
        "metadata": metadata,
        "youtube": youtube,
        "tiktok": tiktok,
        "instagram": ig,
        "twitter": twitter,
        "telegram": telegram,
        "cost_eur": seo_cost,
        "dry_run": dry_run,
    }


def confirm_public_publish(
    *,
    config: dict[str, Any],
    channel: str,
    row_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = load_state(channel, row_id)
    if not state and not dry_run:
        raise FileNotFoundError("publish_state.json missing — run publish_video.py first")
    metadata = state.get("metadata") or {"title": "Video"}
    youtube_id = (state.get("youtube") or {}).get("id") or "dry-run-yt-id"
    video_path = Path(state.get("video_path") or "")
    if dry_run and not video_path.exists():
        video_path = PROJECT_ROOT / "output" / channel / str(row_id) / "final.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"dry-run-mp4-placeholder")

    youtube = set_youtube_privacy(youtube_id, "public", dry_run=dry_run)
    tiktok = publish_tiktok_public(video_path, metadata, dry_run=dry_run) if video_path.exists() else {"skipped": True}
    ig = publish_instagram_container((state.get("instagram") or {}).get("id") or "", dry_run=dry_run)
    youtube_url = f"https://youtu.be/{youtube_id}"
    return {
        "status": STATUS_PUBLISHED,
        "youtube": {**youtube, "url": youtube_url},
        "tiktok": tiktok,
        "instagram": ig,
        "dry_run": dry_run,
    }


def apply_draft_to_sheet(sheet_id: str, tab: str, row_index: int, row: dict[str, Any], payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    from scripts.sheets import ensure_headers, update_row_values

    updates = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_PENDING_VALIDATION,
        "URL YouTube": (payload.get("youtube") or {}).get("url") or "",
        "URL TikTok": (payload.get("tiktok") or {}).get("url") or "",
        "URL Instagram": (payload.get("instagram") or {}).get("url") or "",
        "URL X": (
            f"https://x.com/i/web/status/{(payload.get('twitter') or {}).get('id')}"
            if (payload.get("twitter") or {}).get("id")
            else ""
        ),
        "Publiée": False,
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


def apply_published_to_sheet(sheet_id: str, tab: str, row_index: int, payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    from scripts.sheets import ensure_headers, update_row_values

    updates = {
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_PUBLISHED,
        "URL YouTube": (payload.get("youtube") or {}).get("url") or "",
        "URL TikTok": (payload.get("tiktok") or {}).get("url") or "",
        "URL Instagram": (payload.get("instagram") or {}).get("url") or "",
        "Publiée": True,
    }
    result = {"row": row_index, "updates": updates}
    if dry_run:
        return {**result, "applied": False, "dry_run": True}
    ensure_headers(sheet_id, tab, TOPIC_SHEET_COLUMNS)
    update_row_values(sheet_id, tab, row_index, updates)
    return {**result, "applied": True, "dry_run": False}
