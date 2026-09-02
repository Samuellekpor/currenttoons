#!/usr/bin/env python3
"""Generate voiceover + opposite-language subtitles for a script row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.image_generation import parse_script_cell
from scripts.script_generation import format_script_cell
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED
from scripts.voiceover import apply_voiceover_to_sheet, generate_voiceover_for_row

load_dotenv(PROJECT_ROOT / ".env")

DRY_RUN_SCRIPT = {
    "title": "Budget",
    "language": "FR",
    "format": "Court",
    "characters": ["Emmanuel Macron"],
    "scenes": [
        {"shot": 1, "duration_s": 8, "visual": "v1", "dialogue": "Le budget est une pièce de théâtre."},
        {"shot": 2, "duration_s": 10, "visual": "v2", "dialogue": "Emmanuel Macron joue le premier rôle."},
        {"shot": 3, "duration_s": 8, "visual": "v3", "dialogue": "Le public, lui, paie sa place."},
    ],
}

DRY_RUN_ROW = {
    "URL Article": "https://dry-run.local/fr/budget",
    "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
    "Format Vidéo (Court/Long)": "Court",
    "Langue (FR/EN)": "FR",
    "Script Vidéo Généré": format_script_cell(DRY_RUN_SCRIPT),
    "Images Générées": True,
    "Voix-off Générée": False,
}


def load_row(config: dict, row_id: str, *, dry_run: bool, language: str | None):
    if dry_run:
        row = dict(DRY_RUN_ROW)
        if language:
            row["Langue (FR/EN)"] = language
            script = parse_script_cell(row["Script Vidéo Généré"])
            if language.upper() == "EN":
                script["scenes"] = [
                    {"shot": 1, "dialogue": "The budget is a stage play."},
                    {"shot": 2, "dialogue": "Emmanuel Macron takes the lead role."},
                ]
                row["Script Vidéo Généré"] = format_script_cell(script)
        return 2, row
    from scripts.sheets import get_row

    tab = config.get("google_sheet_tab") or "Sujets"
    return get_row(config["google_sheet_id"], tab, row_id)


def main() -> int:
    parser = build_parser("Generate voiceover and opposite-language subtitles")
    parser.add_argument("--row-id", required=True)
    parser.add_argument("--language", help="Override Langue in dry-run")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    try:
        row_index, row = load_row(config, args.row_id, dry_run=args.dry_run, language=args.language)
        payload = generate_voiceover_for_row(
            row,
            config=config,
            channel=args.channel,
            row_id=args.row_id,
            dry_run=args.dry_run,
        )
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet = apply_voiceover_to_sheet(
            config["google_sheet_id"],
            tab,
            row_index,
            row,
            payload,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "channel": args.channel,
                "row_id": args.row_id,
                "voiceover": {
                    "language": payload["language"],
                    "subtitle_language": payload["subtitle_language"],
                    "provider": payload["provider"],
                    "audio_url": payload["audio_url"],
                    "timestamps_url": payload["timestamps_url"],
                    "subtitles_url": payload["subtitles_url"],
                    "alignment_source": payload["alignment_source"],
                    "cost_eur": payload["cost_eur"],
                },
                "sheet": sheet,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
