#!/usr/bin/env python3
"""Assemble the final video for a row that already has script, images, and voiceover."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.script_generation import format_script_cell
from scripts.topic_analysis import STATUS_SCRIPT_GENERATED
from scripts.video_assembly import apply_video_to_sheet, assemble_video_for_row
from scripts.voiceover import segments_to_srt

load_dotenv(PROJECT_ROOT / ".env")

DRY_RUN_ROW = {
    "URL Article": "https://dry-run.local/fr/budget",
    "Statut (À Revoir/Accepté/Rejeté)": STATUS_SCRIPT_GENERATED,
    "Format Vidéo (Court/Long)": "Court",
    "Langue (FR/EN)": "FR",
    "Script Vidéo Généré": format_script_cell(
        {
            "scenes": [
                {"shot": 1, "chapter": "Hook", "dialogue": "A"},
                {"shot": 2, "chapter": "Twist", "dialogue": "B"},
                {"shot": 3, "chapter": "Chute", "dialogue": "C"},
            ]
        }
    ),
    "URLs Images": json.dumps(
        [{"shot": 1, "url": "https://dry-run.local/a.png"}, {"shot": 2, "url": "https://dry-run.local/b.png"}, {"shot": 3, "url": "https://dry-run.local/c.png"}]
    ),
    "Images Générées": True,
    "URL Voix-off": "https://dry-run.local/voice.mp3",
    "URL Timestamps": "",
    "URL Sous-titres (langue opposée)": "",
    "Voix-off Générée": True,
    "Vidéo Montée": False,
}


def load_row(config: dict, row_id: str, *, dry_run: bool, video_format: str | None):
    if dry_run:
        row = dict(DRY_RUN_ROW)
        if video_format:
            row["Format Vidéo (Court/Long)"] = video_format
        if not row.get("URL Timestamps"):
            ts = {
                "segments": [
                    {"index": 1, "shot": 1, "start": 0, "end": 2, "text": "A"},
                    {"index": 2, "shot": 2, "start": 2, "end": 4, "text": "B"},
                    {"index": 3, "shot": 3, "start": 4, "end": 6, "text": "C"},
                ]
            }
            ts_path = PROJECT_ROOT / "assets_temp" / "dry_run_timestamps.json"
            ts_path.parent.mkdir(parents=True, exist_ok=True)
            ts_path.write_text(json.dumps(ts), encoding="utf-8")
            srt_path = PROJECT_ROOT / "assets_temp" / "dry_run_subtitles.srt"
            srt_path.write_text(
                segments_to_srt([{"text": "The budget is theater", "start": 0, "end": 2}]),
                encoding="utf-8",
            )
            row["URL Timestamps"] = str(ts_path)
            row["URL Sous-titres (langue opposée)"] = str(srt_path)
        return 2, row
    from scripts.sheets import get_row

    tab = config.get("google_sheet_tab") or "Sujets"
    return get_row(config["google_sheet_id"], tab, row_id)


def main() -> int:
    parser = build_parser("Assemble the final video with burned-in opposite-language subtitles")
    parser.add_argument("--row-id", required=True)
    parser.add_argument("--format", dest="video_format", help="Override Format Vidéo in dry-run")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    try:
        row_index, row = load_row(config, args.row_id, dry_run=args.dry_run, video_format=args.video_format)
        payload = assemble_video_for_row(
            row,
            config=config,
            channel=args.channel,
            row_id=args.row_id,
            dry_run=args.dry_run,
        )
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet = apply_video_to_sheet(
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
                "video": payload,
                "sheet": sheet,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
