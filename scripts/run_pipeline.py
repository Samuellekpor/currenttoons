#!/usr/bin/env python3
"""Placeholder pipeline entrypoint. Every script must accept --dry-run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cli import build_parser
from scripts.config import load_channel_config, read_prompt


def main() -> int:
    parser = build_parser("Run the local pipeline for one channel")
    args = parser.parse_args()
    config = load_channel_config(args.channel)
    payload = {
        "dry_run": args.dry_run,
        "channel": config["channel_name"],
        "uses_caricatures": config["uses_caricatures"],
        "language": config["default_language"],
        "format": config["default_format"],
        "tone_preview": read_prompt(config["tone_prompt"])[:120],
        "paid_calls": [] if args.dry_run else ["would-run-live-steps"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
