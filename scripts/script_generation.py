"""Language- and format-aware video script generation."""

from __future__ import annotations

import json
from typing import Any

from scripts.config import read_prompt
from scripts.llm import chat_json
from scripts.topic_analysis import STATUS_ACCEPTED, STATUS_SCRIPT_GENERATED, TOPIC_SHEET_COLUMNS

FORMAT_SPECS = {
    "Court": {
        "duration": "45-60 seconds",
        "shots": "3-5",
        "shot_min": 3,
        "shot_max": 5,
        "structure": "one angle / one punchline",
        "aspect_ratio": "9:16",
        "framing": "vertical 9:16",
        "width": 1080,
        "height": 1920,
    },
    "Long": {
        "duration": "4-8 minutes",
        "shots": "multiple segments/chapters",
        "shot_min": 8,
        "shot_max": 20,
        "structure": "several segments; may develop more than one satirical angle on the same topic",
        "aspect_ratio": "16:9",
        "framing": "horizontal 16:9",
        "width": 1920,
        "height": 1080,
    },
}


def normalize_language(raw: str) -> str:
    value = (raw or "").strip().upper()
    aliases = {
        "FR": "FR",
        "FRANCAIS": "FR",
        "FRANÇAIS": "FR",
        "FRENCH": "FR",
        "EN": "EN",
        "ENGLISH": "EN",
        "ANGLAIS": "EN",
    }
    if value not in aliases:
        raise ValueError("Set Langue (FR/EN) when accepting a topic")
    return aliases[value]


def normalize_format(raw: str) -> str:
    value = (raw or "").strip().lower()
    aliases = {
        "court": "Court",
        "short": "Court",
        "9:16": "Court",
        "long": "Long",
        "16:9": "Long",
    }
    if value not in aliases:
        raise ValueError("Set Format Vidéo (Court/Long) when accepting a topic")
    return aliases[value]


def parse_characters(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = [p.strip() for p in str(raw or "").split(",")]
    names = []
    for item in parts:
        name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return names


def format_script_cell(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _dry_run_script(language: str, video_format: str, characters: list[str], title: str) -> dict[str, Any]:
    spec = FORMAT_SPECS[video_format]
    names = characters or (["Emmanuel Macron"] if language == "FR" else ["a public figure"])
    if video_format == "Court":
        scenes = []
        for i in range(4):
            who = names[i % len(names)]
            if language == "EN":
                visual = f"Vertical 9:16 caricature of {who}, exaggerated features, simple background."
                voice = f"Dry-run line {i + 1} about {title}."
            else:
                visual = f"Cadrage vertical 9:16, caricature de {who}, traits exagérés, fond simple."
                voice = f"Réplique dry-run {i + 1} sur {title}."
            scenes.append({"shot": i + 1, "duration_s": 12, "visual": visual, "dialogue": voice})
    else:
        scenes = []
        for i in range(10):
            who = names[i % len(names)]
            if language == "EN":
                visual = f"Horizontal 16:9 scene featuring {who} in chapter {i // 3 + 1}."
                voice = f"Chapter beat {i + 1} (dry-run)."
            else:
                visual = f"Plan horizontal 16:9 avec {who}, chapitre {i // 3 + 1}."
                voice = f"Segment {i + 1} (dry-run)."
            scenes.append({"shot": i + 1, "duration_s": 30, "visual": visual, "dialogue": voice})
    return {
        "title": title,
        "language": language,
        "format": video_format,
        "aspect_ratio": spec["aspect_ratio"],
        "target_duration": spec["duration"],
        "characters": names,
        "scenes": scenes,
        "dry_run": True,
    }


def generate_script(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    status = str(row.get("Statut (À Revoir/Accepté/Rejeté)") or "").strip()
    if status != STATUS_ACCEPTED:
        raise ValueError(f"Expected status Accepté, got {status!r}")
    language = normalize_language(row.get("Langue (FR/EN)") or "")
    video_format = normalize_format(row.get("Format Vidéo (Court/Long)") or "")
    spec = FORMAT_SPECS[video_format]
    characters = parse_characters(row.get("Personnages Identifiés"))
    prompt_path = config.get("script_generation_prompt_path") or config.get("script_system_prompt_path")
    if not prompt_path:
        raise ValueError("script_generation_prompt_path missing from channel config")
    system_prompt = read_prompt(prompt_path)
    tone = read_prompt(config["tone_prompt"]) if config.get("tone_prompt") else ""
    user_prompt = (
        f"Channel: {config.get('channel_name')}\n"
        f"Write the entire script (dialogue AND visual descriptions) in language: {language}.\n"
        f"Video format: {video_format} ({spec['framing']}, {spec['duration']}, {spec['shots']}, {spec['structure']}).\n"
        f"Tone:\n{tone}\n\n"
        f"Original title: {row.get('Titre Article Original')}\n"
        f"URL: {row.get('URL Article')}\n"
        f"Suggested video title: {row.get('Titre Vidéo Suggéré')}\n"
        f"Angle: {row.get('Angle Proposé')}\n"
        f"Identified public figures (name each explicitly in visuals): {', '.join(characters) or '(none)'}\n"
        "Return JSON with keys: title, language, format, aspect_ratio, target_duration, "
        "characters (array of real names used), scenes (array of {shot, duration_s, visual, dialogue}).\n"
    )
    dry_payload = _dry_run_script(
        language,
        video_format,
        characters,
        str(row.get("Titre Vidéo Suggéré") or row.get("Titre Article Original") or "Dry-run"),
    )
    payload, cost = chat_json(
        system_prompt,
        user_prompt,
        dry_run=dry_run,
        dry_run_payload=dry_payload,
        cost_step="script_generation",
    )
    payload["language"] = language
    payload["format"] = video_format
    payload["aspect_ratio"] = spec["aspect_ratio"]
    payload["target_duration"] = spec["duration"]
    payload["characters"] = parse_characters(payload.get("characters") or characters)
    payload["cost_eur"] = cost
    payload["dry_run"] = dry_run
    _assert_characters_named(payload, characters)
    return payload


def _assert_characters_named(payload: dict[str, Any], required: list[str]) -> None:
    visuals = " ".join(str(scene.get("visual") or "") for scene in payload.get("scenes") or [])
    missing = [name for name in required if name.lower() not in visuals.lower()]
    if missing:
        payload.setdefault("warnings", [])
        payload["warnings"].append(
            "Visual descriptions must name: " + ", ".join(missing)
        )


def apply_script_to_sheet(
    sheet_id: str,
    tab: str,
    row_index: int,
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from scripts.costs import add_video_cost
    from scripts.sheets import ensure_headers, update_row_values

    updates = {
        "Script Vidéo Généré": format_script_cell(payload),
        "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
    }
    result = {"row": row_index, "updates": updates, "cost_eur": payload.get("cost_eur") or 0}
    if dry_run:
        return {**result, "applied": False, "dry_run": True}
    ensure_headers(sheet_id, tab, TOPIC_SHEET_COLUMNS)
    update_row_values(sheet_id, tab, row_index, updates)
    url = str(row.get("URL Article") or "")
    if url and payload.get("cost_eur"):
        add_video_cost(sheet_id, url, float(payload["cost_eur"]), dry_run=False, tab=tab)
    return {**result, "applied": True, "dry_run": False}
