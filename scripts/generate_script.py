#!/usr/bin/env python3
"""Generate a video script for one accepted Google Sheet row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.script_generation import apply_script_to_sheet, generate_script
from scripts.topic_analysis import STATUS_ACCEPTED

load_dotenv(PROJECT_ROOT / ".env")

DRY_RUN_FIXTURE = {
    "Titre Article Original": "Le gouvernement présente un budget rectificatif",
    "URL Article": "https://dry-run.local/fr/budget",
    "Angle Proposé": "Le budget comme théâtre politique",
    "Titre Vidéo Suggéré": "Budget : la pièce (trop) bien jouée",
    "Personnages Identifiés": "Emmanuel Macron",
    "Statut (À Revoir/Accepté/Rejeté)": STATUS_ACCEPTED,
    "Format Vidéo (Court/Long)": "Court",
    "Langue (FR/EN)": "FR",
}


def load_row(config: dict, row_id: str, *, dry_run: bool, language: str | None, video_format: str | None):
    if dry_run:
        row = dict(DRY_RUN_FIXTURE)
        if language:
            row["Langue (FR/EN)"] = language
        if video_format:
            row["Format Vidéo (Court/Long)"] = video_format
        return 2, row
    from scripts.sheets import get_row

    tab = config.get("google_sheet_tab") or "Sujets"
    return get_row(config["google_sheet_id"], tab, row_id)


def main() -> int:
    parser = build_parser("Generate a video script for an accepted topic row")
    parser.add_argument("--row-id", required=True, help="Sheet row number (>= 2) or URL Article")
    parser.add_argument("--language", help="Override Langue (dry-run / tests)")
    parser.add_argument("--format", dest="video_format", help="Override Format Vidéo (dry-run / tests)")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    try:
        row_index, row = load_row(
            config,
            args.row_id,
            dry_run=args.dry_run,
            language=args.language,
            video_format=args.video_format,
        )
        payload = generate_script(row, config=config, dry_run=args.dry_run)
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet = apply_script_to_sheet(
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
                "row_index": row_index,
                "script": payload,
                "sheet": sheet,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
