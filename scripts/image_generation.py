"""Extract visual shots from a script and generate preview images."""

from __future__ import annotations

import json
from typing import Any

from scripts.character_bank import get_or_create_caricature
from scripts.config import read_prompt
from scripts.costs import add_video_cost, estimate_cost
from scripts.image_providers import generate_image
from scripts.llm import chat_json
from scripts.script_generation import FORMAT_SPECS, normalize_format, parse_characters
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED, TOPIC_SHEET_COLUMNS

VISUAL_PLAN_SYSTEM = """You extract illustration shots from a video script.
Confirm/refine the listed public figures. Name them in every relevant scene prompt.
Return JSON: {"characters": ["Full Name"], "shots": [{"shot": 1, "characters": ["Full Name"], "prompt": "scene prompt", "reuse_character": "Full Name or empty"}]}.
For Court keep 3-5 shots. For Long you may output more, but reuse the same character identity across shots (change setting/pose only).
Do not invent public figures that are not in the script or the provided list.
"""


def is_flag_checked(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "oui", "x", "checked"}


def parse_script_cell(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Script Vidéo Généré is empty")
    return json.loads(text)


def extract_visual_plan(
    script: dict[str, Any],
    *,
    identified_characters: list[str],
    style_prompt: str,
    video_format: str,
    dry_run: bool = False,
) -> tuple[dict[str, Any], float]:
    spec = FORMAT_SPECS[video_format]
    scenes = script.get("scenes") or []
    seed_characters = parse_characters(script.get("characters") or identified_characters)

    if dry_run:
        max_shots = spec["shot_max"] if video_format == "Court" else min(max(len(scenes), spec["shot_min"]), 12)
        shots = []
        for i, scene in enumerate(scenes[:max_shots]):
            who = parse_characters(scene.get("visual"))
            names = [n for n in seed_characters if n in str(scene.get("visual") or "")] or who[:1] or seed_characters[:1]
            shots.append(
                {
                    "shot": scene.get("shot") or i + 1,
                    "characters": names,
                    "prompt": f"{style_prompt}. {scene.get('visual', '')}",
                    "reuse_character": names[0] if names else "",
                }
            )
        if video_format == "Court":
            shots = shots[: spec["shot_max"]]
            if len(shots) < spec["shot_min"] and scenes:
                while len(shots) < spec["shot_min"]:
                    shots.append(dict(shots[-1], shot=len(shots) + 1))
        return {"characters": seed_characters, "shots": shots}, 0.0

    user = (
        f"Format: {video_format} ({spec['aspect_ratio']}, {spec['shots']}).\n"
        f"Known public figures: {', '.join(identified_characters) or '(none)'}\n"
        f"Image style:\n{style_prompt}\n\n"
        f"Script JSON:\n{json.dumps(script, ensure_ascii=False)[:8000]}\n"
    )
    payload, cost = chat_json(
        VISUAL_PLAN_SYSTEM,
        user,
        dry_run=False,
        cost_step="topic_analysis",
    )
    characters = parse_characters(payload.get("characters") or seed_characters)
    shots = payload.get("shots") or []
    if video_format == "Court":
        shots = shots[: spec["shot_max"]]
    return {"characters": characters, "shots": shots}, cost


def generate_images_for_row(
    row: dict[str, Any],
    *,
    config: dict[str, Any],
    dry_run: bool = False,
    quality: str = "preview",
) -> dict[str, Any]:
    status = str(row.get("Statut (À Revoir/Accepté/Rejeté)") or "").strip()
    if status != STATUS_SCRIPT_GENERATED:
        raise ValueError(f"Expected status Script Généré, got {status!r}")
    if is_flag_checked(row.get("Images Générées")):
        raise ValueError("Images Générées is already checked")

    video_format = normalize_format(row.get("Format Vidéo (Court/Long)") or config.get("default_format") or "Court")
    aspect_ratio = FORMAT_SPECS[video_format]["aspect_ratio"]
    identified = parse_characters(row.get("Personnages Identifiés"))
    script = parse_script_cell(row.get("Script Vidéo Généré"))
    style = read_prompt(config["image_style_prompt_path"])
    plan, plan_cost = extract_visual_plan(
        script,
        identified_characters=identified,
        style_prompt=style,
        video_format=video_format,
        dry_run=dry_run,
    )

    caricatures: dict[str, dict[str, Any]] = {}
    caricature_cost = 0.0
    if config.get("uses_caricatures"):
        names = plan.get("characters") or identified
        for name in names:
            record = get_or_create_caricature(
                name,
                "",
                dry_run=dry_run,
                video_sheet_id=None if dry_run else config.get("google_sheet_id"),
                video_row_key=None if dry_run else row.get("URL Article"),
            )
            caricatures[name] = record
            if record.get("created") and not dry_run:
                caricature_cost += estimate_cost("caricature_generation")

    images = []
    image_cost = 0.0
    for shot in plan.get("shots") or []:
        names = parse_characters(shot.get("characters") or shot.get("reuse_character"))
        ref = None
        if names and names[0] in caricatures:
            ref = caricatures[names[0]].get("Caricature URL")
        prompt = str(shot.get("prompt") or "")
        if ref:
            prompt = (
                f"{prompt} Keep the same recognizable caricature identity as the reference image; "
                "only change setting, camera, and pose."
            )
        generated = generate_image(
            prompt,
            aspect_ratio,
            reference_image_url=ref,
            quality=quality,
            dry_run=dry_run,
        )
        image_cost += float(generated.get("cost_eur") or 0)
        images.append(
            {
                "shot": shot.get("shot"),
                "url": generated["url"],
                "quality": generated["quality"],
                "characters": names,
                "reference_image_url": ref,
            }
        )

    total_cost = round(plan_cost + caricature_cost + image_cost, 4)
    return {
        "format": video_format,
        "aspect_ratio": aspect_ratio,
        "plan": plan,
        "caricatures": {name: rec.get("Caricature URL") for name, rec in caricatures.items()},
        "caricatures_created": [name for name, rec in caricatures.items() if rec.get("created")],
        "images": images,
        "cost_eur": total_cost,
        "quality": quality,
        "dry_run": dry_run,
    }


def apply_images_to_sheet(
    sheet_id: str,
    tab: str,
    row_index: int,
    row: dict[str, Any],
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from scripts.sheets import ensure_headers, update_row_values

    urls_cell = json.dumps(payload.get("images") or [], ensure_ascii=False)
    updates = {
        "URLs Images": urls_cell,
        "Images Générées": True,
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
