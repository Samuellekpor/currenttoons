"""Wikimedia Commons portraits (libre licences) as caricature source photos."""

from __future__ import annotations

from typing import Any

import requests

USER_AGENT = "currenttoons-pipeline/0.1 (topic-monitoring; wikimedia portrait lookup)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

LIBRE_HINTS = (
    "cc-zero",
    "cc0",
    "cc-by",
    "cc by",
    "public domain",
    "pd-",
    "gfdl",
    "cc-by-sa",
    "creativecommons",
)


def _headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _license_ok(meta: dict[str, Any]) -> bool:
    license_short = str((meta.get("LicenseShortName") or {}).get("value") or "").lower()
    license_url = str((meta.get("LicenseUrl") or {}).get("value") or "").lower()
    usage = str((meta.get("UsageTerms") or {}).get("value") or "").lower()
    blob = f"{license_short} {license_url} {usage}"
    if not blob.strip():
        return True
    return any(hint in blob for hint in LIBRE_HINTS)


def find_wikimedia_portrait(person_name: str) -> str | None:
    """Return a Commons (or Wikipedia) image URL, or None if nothing usable."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{person_name} portrait",
        "gsrnamespace": 6,
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime",
        "iiurlwidth": 1024,
    }
    try:
        response = requests.get(COMMONS_API, params=params, headers=_headers(), timeout=20)
        response.raise_for_status()
        pages = (response.json().get("query") or {}).get("pages") or {}
    except requests.RequestException:
        pages = {}
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = str(info.get("mime") or "")
        if mime and not mime.startswith("image/"):
            continue
        if not _license_ok(info.get("extmetadata") or {}):
            continue
        url = info.get("thumburl") or info.get("url")
        if url:
            return url

    try:
        summary = requests.get(
            WIKI_SUMMARY.format(title=person_name.replace(" ", "_")),
            headers=_headers(),
            timeout=20,
        )
        if summary.ok:
            thumb = (summary.json().get("originalimage") or summary.json().get("thumbnail") or {}).get("source")
            if thumb:
                return thumb
    except requests.RequestException:
        return None
    return None
