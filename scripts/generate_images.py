#!/usr/bin/env python3
"""Generate preview images for a row in status Script Généré."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.character_bank import get_or_create_caricature
from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.image_generation import apply_images_to_sheet, generate_images_for_row
from scripts.script_generation import format_script_cell
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED

load_dotenv(PROJECT_ROOT / ".env")

DRY_RUN_SCRIPT = {
    "title": "Budget : la pièce (trop) bien jouée",
    "language": "FR",
    "format": "Court",
    "aspect_ratio": "9:16",
    "characters": ["Emmanuel Macron"],
    "scenes": [
        {"shot": 1, "visual": "Cadrage vertical 9:16, caricature de Emmanuel Macron au pupitre.", "dialogue": "A"},
        {"shot": 2, "visual": "Emmanuel Macron face à un budget géant.", "dialogue": "B"},
        {"shot": 3, "visual": "Plan serré Emmanuel Macron, sourire exagéré.", "dialogue": "C"},
        {"shot": 4, "visual": "Emmanuel Macron quitte la scène, 9:16.", "dialogue": "D"},
    ],
}

DRY_RUN_ROW = {
    "Titre Article Original": "Budget",
    "URL Article": "https://dry-run.local/fr/budget",
    "Personnages Identifiés": "Emmanuel Macron",
    "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
    "Format Vidéo (Court/Long)": "Court",
    "Langue (FR/EN)": "FR",
    "Script Vidéo Généré": format_script_cell(DRY_RUN_SCRIPT),
    "Images Générées": False,
    "URLs Images": "",
}


def load_row(config: dict, row_id: str, *, dry_run: bool, video_format: str | None):
    if dry_run:
        row = dict(DRY_RUN_ROW)
        if not config.get("uses_caricatures"):
            script = {
                "title": "Deux minutes pour mieux dormir",
                "language": "FR",
                "format": "Court",
                "aspect_ratio": "9:16",
                "characters": [],
                "scenes": [
                    {"shot": 1, "visual": "Cadrage vertical 9:16, lampe de chevet, téléphone posé loin du lit.", "dialogue": "A"},
                    {"shot": 2, "visual": "Une personne pose le téléphone dans une autre pièce, lumière chaude.", "dialogue": "B"},
                    {"shot": 3, "visual": "Respiration calme, rideaux tirés, 9:16.", "dialogue": "C"},
                    {"shot": 4, "visual": "Réveil le lendemain, lumière naturelle, pas de visage caricaturé.", "dialogue": "D"},
                ],
            }
            row["Titre Article Original"] = "Sommeil"
            row["URL Article"] = "https://dry-run.local/habits/sleep"
            row["Personnages Identifiés"] = ""
            row["Script Vidéo Généré"] = format_script_cell(script)
        if video_format:
            row["Format Vidéo (Court/Long)"] = video_format
            if video_format.lower() == "long":
                if config.get("uses_caricatures"):
                    script = dict(DRY_RUN_SCRIPT)
                    script["format"] = "Long"
                    script["aspect_ratio"] = "16:9"
                    script["scenes"] = [
                        {"shot": i + 1, "visual": f"Plan 16:9 Emmanuel Macron, chapitre {i // 3 + 1}.", "dialogue": str(i)}
                        for i in range(10)
                    ]
                    row["Script Vidéo Généré"] = format_script_cell(script)
                else:
                    script = {
                        "title": "Le rituel du soir",
                        "language": "FR",
                        "format": "Long",
                        "aspect_ratio": "16:9",
                        "characters": [],
                        "scenes": [
                            {"shot": i + 1, "visual": f"Plan 16:9, intérieur calme, chapitre {i // 3 + 1}.", "dialogue": str(i)}
                            for i in range(10)
                        ],
                    }
                    row["Script Vidéo Généré"] = format_script_cell(script)
        return 2, row
    from scripts.sheets import get_row

    tab = config.get("google_sheet_tab") or "Sujets"
    return get_row(config["google_sheet_id"], tab, row_id)


def main() -> int:
    parser = build_parser("Generate preview images for an accepted script row")
    parser.add_argument("--row-id", help="Sheet row number (>= 2) or URL Article")
    parser.add_argument("--person", help="Bank-only: get or create one caricature")
    parser.add_argument("--photo-url", default="", help="Optional reference photo for --person")
    parser.add_argument("--format", dest="video_format", help="Override format in dry-run")
    parser.add_argument("--upscale", action="store_true", help="Final quality (retained images only)")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    try:
        if args.person and not args.row_id:
            record = get_or_create_caricature(args.person, args.photo_url, dry_run=args.dry_run)
            print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
            return 0
        if not args.row_id:
            raise SystemExit("Provide --row-id (or --person for the character bank only)")
        row_index, row = load_row(config, args.row_id, dry_run=args.dry_run, video_format=args.video_format)
        payload = generate_images_for_row(
            row,
            config=config,
            dry_run=args.dry_run,
            quality="final" if args.upscale else "preview",
        )
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet = apply_images_to_sheet(
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
                "images": payload,
                "sheet": sheet,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
