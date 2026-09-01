#!/usr/bin/env python3
"""Generate images for a video. Always consults the character bank first."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.character_bank import get_or_create_caricature
from scripts.cli import build_parser
from scripts.config import load_channel_config, read_prompt
from scripts.costs import add_video_cost, estimate_cost


def main() -> int:
    parser = build_parser("Generate (or reuse) images for a video")
    parser.add_argument("--person", default="Exemple Politique")
    parser.add_argument("--photo-url", default="https://example.com/ref.jpg")
    parser.add_argument("--video", default="dry-run-video")
    args = parser.parse_args()

    config = load_channel_config(args.channel)
    style = read_prompt(config["image_style_prompt_path"])

    if config["uses_caricatures"]:
        record = get_or_create_caricature(
            args.person,
            args.photo_url,
            dry_run=args.dry_run,
            style_prompt=style,
            video_sheet_id=config["google_sheet_id"],
            video_row_key=args.video,
        )
        cost = estimate_cost("caricature_generation") if record.get("created") else 0.0
    else:
        record = {"skipped": True, "reason": "uses_caricatures is false"}
        cost = 0.0 if args.dry_run else estimate_cost("image_generation")

    cost_event = add_video_cost(
        config["google_sheet_id"],
        args.video,
        cost,
        dry_run=args.dry_run,
    )
    print(json.dumps({"record": record, "cost": cost_event}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
