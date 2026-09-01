#!/usr/bin/env python3
"""Analyze already collected topics (JSON file or a single article)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from scripts.cli import PROJECT_ROOT, build_parser
from scripts.config import load_channel_config
from scripts.topic_analysis import analyze_topic, write_topics_to_sheet

load_dotenv(PROJECT_ROOT / ".env")


def items_from_args(args) -> list[dict[str, str]]:
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        topics = payload.get("topics") or payload.get("items") or []
        normalized = []
        for item in topics:
            normalized.append(
                {
                    "title": item.get("title") or item.get("Titre Article Original") or "",
                    "url": item.get("url") or item.get("URL Article") or "",
                    "source": item.get("source") or "",
                    "excerpt": item.get("excerpt") or "",
                }
            )
        return normalized
    if args.title and args.url:
        return [
            {
                "title": args.title,
                "url": args.url,
                "source": args.source or "",
                "excerpt": args.excerpt or "",
            }
        ]
    raise SystemExit("Provide --input JSON or --title and --url")


def main() -> int:
    parser = build_parser("Analyze topics with gpt-4o-mini")
    parser.add_argument("--input", help="JSON from collect_topics.py")
    parser.add_argument("--title")
    parser.add_argument("--url")
    parser.add_argument("--source", default="")
    parser.add_argument("--excerpt", default="")
    parser.add_argument("--skip-sheet", action="store_true")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    items = items_from_args(args)
    analyses = [analyze_topic(item, config=config, dry_run=args.dry_run) for item in items]
    sheet_result = None
    if not args.skip_sheet:
        tab = config.get("google_sheet_tab") or "Sujets"
        sheet_result = write_topics_to_sheet(
            config["google_sheet_id"],
            tab,
            analyses,
            dry_run=args.dry_run,
        )
    print(json.dumps({"topics": analyses, "sheet": sheet_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
