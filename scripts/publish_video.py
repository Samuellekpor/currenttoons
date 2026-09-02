#!/usr/bin/env python3
"""Draft-publish a mounted video (YouTube unlisted, TikTok inbox, IG container) + Telegram gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.publishing import apply_draft_to_sheet, prepare_and_upload_drafts
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED

load_dotenv(PROJECT_ROOT / ".env")

DRY_RUN_ROW = {
    "URL Article": "https://dry-run.local/fr/budget",
    "Titre Vidéo Suggéré": "Budget : la pièce trop bien jouée",
    "Angle Proposé": "Théâtre budgétaire",
    "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
    "Format Vidéo (Court/Long)": "Court",
    "Langue (FR/EN)": "FR",
    "Script Vidéo Généré": "{}",
    "URL Vidéo Finale": "output/currenttoons/2/final.mp4",
    "Vidéo Montée": True,
    "Publiée": False,
    "Coût Estimé (€)": 0.12,
}


def load_row(config: dict, row_id: str, *, dry_run: bool, video_format: str | None):
    if dry_run:
        row = dict(DRY_RUN_ROW)
        if video_format:
            row["Format Vidéo (Court/Long)"] = video_format
        return 2, row
    from scripts.sheets import get_row

    tab = config.get("google_sheet_tab") or "Sujets"
    return get_row(config["google_sheet_id"], tab, row_id)


def main() -> int:
    parser = build_parser("Upload drafts and request Telegram validation")
    parser.add_argument("--row-id", required=True)
    parser.add_argument("--format", dest="video_format")
    args = parser.parse_args()
    config = load_channel_config(args.channel)
    try:
        row_index, row = load_row(config, args.row_id, dry_run=args.dry_run, video_format=args.video_format)
        payload = prepare_and_upload_drafts(
            row, config=config, channel=args.channel, row_id=args.row_id, dry_run=args.dry_run
        )
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet = apply_draft_to_sheet(
            config["google_sheet_id"], tab, row_index, row, payload, dry_run=args.dry_run
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {"ok": True, "channel": args.channel, "row_id": args.row_id, "publish": payload, "sheet": sheet},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
