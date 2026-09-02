#!/usr/bin/env python3
"""Human gate: switch YouTube/TikTok/Instagram from draft to public after Telegram confirm."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.publishing import apply_published_to_sheet, confirm_public_publish

load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    parser = build_parser("Confirm public publish after human validation")
    parser.add_argument("--row-id", required=True)
    parser.add_argument("--secret", default="", help="Must match PUBLISH_WEBHOOK_SECRET when set")
    args = parser.parse_args()
    expected = os.environ.get("PUBLISH_WEBHOOK_SECRET") or ""
    if expected and args.secret != expected:
        print(json.dumps({"ok": False, "error": "invalid webhook secret"}))
        return 1
    config = load_channel_config(args.channel)
    try:
        payload = confirm_public_publish(
            config=config, channel=args.channel, row_id=args.row_id, dry_run=args.dry_run
        )
        sheet = None
        if not args.dry_run:
            from scripts.sheets import get_row

            tab = config.get("google_sheet_tab") or "Sujets"
            row_index, _row = get_row(config["google_sheet_id"], tab, args.row_id)
            sheet = apply_published_to_sheet(
                config["google_sheet_id"], tab, row_index, payload, dry_run=False
            )
        else:
            sheet = apply_published_to_sheet("dry", "Sujets", 2, payload, dry_run=True)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "publish": payload, "sheet": sheet}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
