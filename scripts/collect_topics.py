#!/usr/bin/env python3
"""Daily topic intake for one channel. Collects, analyzes, writes the Sujets sheet."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.topic_analysis import analyze_topic, write_topics_to_sheet
from scripts.cli import PROJECT_ROOT, build_parser
from scripts.collectors import collect_topics_for_channel
from scripts.config import load_channel_config

load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    parser = build_parser("Collect and analyze topics for a channel")
    parser.add_argument("--skip-analyze", action="store_true", help="Collect only, no gpt-4o-mini")
    parser.add_argument("--skip-sheet", action="store_true", help="Do not write Google Sheets")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    raw = collect_topics_for_channel(
        config,
        dry_run=args.dry_run,
        newsapi_key=os.environ.get("NEWSAPI_KEY"),
    )

    analyses = []
    if args.skip_analyze:
        for item in raw:
            analyses.append(
                {
                    **item,
                    "angle": "",
                    "suggested_video_title": "",
                    "public_figures": [],
                    "mentions_public_figures": False,
                    "cost_eur": 0,
                    "dry_run": args.dry_run,
                }
            )
    else:
        for item in raw:
            analyses.append(analyze_topic(item, config=config, dry_run=args.dry_run))

    sheet_result = None
    if not args.skip_sheet:
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet_result = write_topics_to_sheet(
            config["google_sheet_id"],
            tab,
            analyses,
            dry_run=args.dry_run,
        )

    snapshot = {
        "channel": args.channel,
        "dry_run": args.dry_run,
        "collected": len(raw),
        "topics": analyses,
        "sheet": sheet_result,
    }
    out_dir = PROJECT_ROOT / "assets_temp"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"topics_{args.channel}_{stamp}.json"
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
