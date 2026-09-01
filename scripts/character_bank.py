"""Character bank: caricature once, reuse forever.

Lookup order:
1. Local cache under characters/
2. Remote bank (Google Sheets tab Personnages, or Supabase public.personnages)
3. Image generation API (skipped in --dry-run)

Every image-generation script must call get_or_create_caricature before a paid image API.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT
from scripts.costs import add_video_cost, estimate_cost

load_dotenv(PROJECT_ROOT / ".env")

CHARACTERS_DIR = PROJECT_ROOT / "characters"
SHEET_HEADERS = (
    "Nom",
    "Photo Référence URL",
    "Caricature URL",
    "Date Génération",
    "Nb Utilisations",
)


def _slug(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower().strip())
    return normalized.strip("-") or "unknown"


def _local_meta_path(name: str) -> Path:
    return CHARACTERS_DIR / f"{_slug(name)}.json"


def read_local_cache(name: str) -> dict[str, Any] | None:
    path = _local_meta_path(name)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_local_cache(record: dict[str, Any]) -> None:
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = _local_meta_path(record["Nom"])
    with path.open("w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)


def _dry_run_record(person_name: str, reference_photo_url: str) -> dict[str, Any]:
    slug = _slug(person_name)
    return {
        "Nom": person_name,
        "Photo Référence URL": reference_photo_url,
        "Caricature URL": f"https://dry-run.local/characters/{quote(slug)}.png",
        "Date Génération": datetime.now(timezone.utc).date().isoformat(),
        "Nb Utilisations": 1,
        "dry_run": True,
        "created": True,
    }


def _backend() -> str:
    explicit = (os.environ.get("CHARACTER_BANK_BACKEND") or "").strip().lower()
    if explicit in {"supabase", "google_sheets"}:
        return explicit
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        return "supabase"
    return "google_sheets"


def _sheets_lookup(person_name: str) -> dict[str, Any] | None:
    from scripts.sheets import open_worksheet

    sheet_id = os.environ.get("PERSONNAGES_SHEET_ID")
    tab = os.environ.get("PERSONNAGES_SHEET_TAB", "Personnages")
    if not sheet_id:
        return None
    ws = open_worksheet(sheet_id, tab)
    for row in ws.get_all_records():
        if str(row.get("Nom", "")).strip().lower() == person_name.strip().lower():
            return dict(row)
    return None


def _sheets_upsert(record: dict[str, Any]) -> dict[str, Any]:
    from scripts.sheets import upsert_record

    sheet_id = os.environ.get("PERSONNAGES_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("PERSONNAGES_SHEET_ID is required for the Google Sheets character bank")
    tab = os.environ.get("PERSONNAGES_SHEET_TAB", "Personnages")
    return upsert_record(
        sheet_id,
        tab,
        match_column="Nom",
        match_value=record["Nom"],
        values={k: record.get(k, "") for k in SHEET_HEADERS},
    )


def _supabase_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
    return create_client(url, key)


def _supabase_lookup(person_name: str) -> dict[str, Any] | None:
    client = _supabase_client()
    result = (
        client.table("personnages")
        .select("*")
        .ilike("nom", person_name.strip())
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    row = result.data[0]
    return {
        "Nom": row["nom"],
        "Photo Référence URL": row.get("photo_reference_url") or "",
        "Caricature URL": row.get("caricature_url") or "",
        "Date Génération": row.get("date_generation") or "",
        "Nb Utilisations": row.get("nb_utilisations") or 0,
        "_id": row.get("id"),
    }


def _supabase_upsert(record: dict[str, Any], existing_id: Any | None) -> dict[str, Any]:
    client = _supabase_client()
    payload = {
        "nom": record["Nom"],
        "photo_reference_url": record.get("Photo Référence URL"),
        "caricature_url": record.get("Caricature URL"),
        "date_generation": record.get("Date Génération"),
        "nb_utilisations": record.get("Nb Utilisations", 1),
    }
    if existing_id:
        client.table("personnages").update(payload).eq("id", existing_id).execute()
    else:
        client.table("personnages").insert(payload).execute()
    return record


def _generate_caricature(person_name: str, reference_photo_url: str, style_prompt: str) -> str:
    """Paid image generation — never called in dry-run.

    Placeholder until Partie 2.1 wires Replicate/FAL.
    """
    raise NotImplementedError(
        "Image generation API is not wired yet. "
        f"Would generate caricature for {person_name!r} from {reference_photo_url!r} "
        f"with style {style_prompt[:80]!r}."
    )


def get_or_create_caricature(
    person_name: str,
    reference_photo_url: str,
    *,
    dry_run: bool = False,
    style_prompt: str = "",
    video_sheet_id: str | None = None,
    video_row_key: str | None = None,
) -> dict[str, Any]:
    """Return an existing caricature or create one.

    Always check the bank before calling a paid image API.
    """
    cached = read_local_cache(person_name)
    if cached and cached.get("Caricature URL"):
        cached["Nb Utilisations"] = int(cached.get("Nb Utilisations") or 0) + 1
        cached["created"] = False
        write_local_cache(cached)
        return cached

    if dry_run:
        record = _dry_run_record(person_name, reference_photo_url)
        write_local_cache(record)
        return record

    backend = _backend()
    existing = _supabase_lookup(person_name) if backend == "supabase" else _sheets_lookup(person_name)
    if existing and existing.get("Caricature URL"):
        existing["Nb Utilisations"] = int(existing.get("Nb Utilisations") or 0) + 1
        existing["created"] = False
        if backend == "supabase":
            _supabase_upsert(existing, existing.get("_id"))
        else:
            _sheets_upsert(existing)
        write_local_cache(existing)
        return existing

    url = _generate_caricature(person_name, reference_photo_url, style_prompt)
    record = {
        "Nom": person_name,
        "Photo Référence URL": reference_photo_url,
        "Caricature URL": url,
        "Date Génération": datetime.now(timezone.utc).date().isoformat(),
        "Nb Utilisations": 1,
        "created": True,
    }
    if backend == "supabase":
        _supabase_upsert(record, None)
    else:
        _sheets_upsert(record)
    write_local_cache(record)

    if video_sheet_id and video_row_key:
        add_video_cost(
            video_sheet_id,
            video_row_key,
            estimate_cost("caricature_generation"),
            dry_run=False,
        )
    return record
