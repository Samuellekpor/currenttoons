"""Analyze collected topics with gpt-4o-mini and map them to the Sujets sheet."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.config import read_prompt
from scripts.llm import chat_json

TOPIC_SHEET_COLUMNS = [
    "Date",
    "Titre Article Original",
    "URL Article",
    "Angle Proposé",
    "Titre Vidéo Suggéré",
    "Personnages Identifiés",
    "Statut (À Revoir/Accepté/Rejeté)",
    "Format Vidéo (Court/Long)",
    "Langue (FR/EN)",
    "Coût Estimé (€)",
    "Commentaires",
    "Script Vidéo Généré",
    "URLs Images",
    "Images Générées",
    "URL Voix-off",
    "URL Timestamps",
    "URL Sous-titres (langue opposée)",
    "Voix-off Générée",
    "URL Vidéo Finale",
    "Vidéo Montée",
    "URL YouTube",
    "URL TikTok",
    "URL Instagram",
    "URL X",
    "Publiée",
]

STATUS_REVIEW = "À Revoir"
STATUS_ACCEPTED = "Accepté"
STATUS_SCRIPT_GENERATED = "Script Généré"
STATUS_PENDING_VALIDATION = "En Attente de Validation"
STATUS_PUBLISHED = "Publiée"
EMPTY_UNTIL_ACCEPTED = ""


def figures_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("public_figures") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    names = []
    for item in raw:
        name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return names


def analyze_topic(
    item: dict[str, str],
    *,
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    prompt_path = config.get("topic_analysis_prompt_path")
    if not prompt_path:
        raise ValueError("topic_analysis_prompt_path missing from channel config")
    system_prompt = read_prompt(prompt_path)
    user_prompt = (
        f"Titre: {item.get('title', '')}\n"
        f"URL: {item.get('url', '')}\n"
        f"Source: {item.get('source', '')}\n"
        f"Extrait: {item.get('excerpt', '')}\n"
    )
    dry_payload = None
    if dry_run:
        text = f"{item.get('title', '')} {item.get('excerpt', '')}"
        figures = ["Emmanuel Macron"] if "Macron" in text else []
        dry_payload = {
            "angle": "Angle factice (dry-run).",
            "suggested_video_title": "Titre vidéo factice (dry-run)",
            "public_figures": figures,
            "mentions_public_figures": bool(figures),
        }
    payload, cost = chat_json(system_prompt, user_prompt, dry_run=dry_run, dry_run_payload=dry_payload)
    figures = figures_from_payload(payload)
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source": item.get("source", ""),
        "excerpt": item.get("excerpt", ""),
        "angle": str(payload.get("angle") or "").strip(),
        "suggested_video_title": str(payload.get("suggested_video_title") or "").strip(),
        "public_figures": figures,
        "mentions_public_figures": bool(payload.get("mentions_public_figures")) or bool(figures),
        "cost_eur": cost,
        "dry_run": dry_run,
    }


def to_sheet_row(analysis: dict[str, Any], *, today: str | None = None) -> dict[str, Any]:
    date = today or datetime.now(timezone.utc).date().isoformat()
    figures = analysis.get("public_figures") or []
    return {
        "Date": date,
        "Titre Article Original": analysis.get("title", ""),
        "URL Article": analysis.get("url", ""),
        "Angle Proposé": analysis.get("angle", ""),
        "Titre Vidéo Suggéré": analysis.get("suggested_video_title", ""),
        "Personnages Identifiés": ", ".join(figures),
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_REVIEW,
        "Format Vidéo (Court/Long)": EMPTY_UNTIL_ACCEPTED,
        "Langue (FR/EN)": EMPTY_UNTIL_ACCEPTED,
        "Coût Estimé (€)": analysis.get("cost_eur") or 0,
        "Commentaires": (
            "Format et langue à renseigner uniquement en passant le statut à Accepté. "
            f"Source: {analysis.get('source', '')}"
        ),
        "Script Vidéo Généré": "",
        "URLs Images": "",
        "Images Générées": False,
        "URL Voix-off": "",
        "URL Timestamps": "",
        "URL Sous-titres (langue opposée)": "",
        "Voix-off Générée": False,
        "URL Vidéo Finale": "",
        "Vidéo Montée": False,
        "URL YouTube": "",
        "URL TikTok": "",
        "URL Instagram": "",
        "URL X": "",
        "Publiée": False,
    }


def write_topics_to_sheet(
    sheet_id: str,
    tab: str,
    analyses: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = [to_sheet_row(item) for item in analyses]
    if dry_run:
        return {"applied": False, "dry_run": True, "rows": rows, "skipped_urls": []}

    from scripts.sheets import ensure_headers, existing_column_values, upsert_record

    ensure_headers(sheet_id, tab, TOPIC_SHEET_COLUMNS)
    known = existing_column_values(sheet_id, tab, "URL Article")
    written = []
    skipped = []
    for row in rows:
        url = str(row.get("URL Article") or "")
        if url and url in known:
            skipped.append(url)
            continue
        upsert_record(sheet_id, tab, match_column="URL Article", match_value=url, values=row)
        written.append(url)
        known.add(url)
    return {"applied": True, "dry_run": False, "written": written, "skipped_urls": skipped}


def delivery_options_from_row(row: dict[str, Any]) -> dict[str, str]:
    """Format + language are chosen only when the row is set to Accepté."""
    from scripts.script_generation import normalize_format, normalize_language

    status = str(row.get("Statut (À Revoir/Accepté/Rejeté)") or "").strip()
    if status != STATUS_ACCEPTED:
        raise ValueError("Pipeline delivery options are only valid when status is Accepté")
    video_format = normalize_format(row.get("Format Vidéo (Court/Long)") or "")
    language = normalize_language(row.get("Langue (FR/EN)") or "")
    return {"format": video_format, "language": language}
