"""Shared CLI flags for every pipeline script."""

from __future__ import annotations

import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Aucun appel payant : données factices uniquement.",
    )
    parser.add_argument(
        "--channel",
        default="currenttoons",
        help="Slug du fichier channels/<slug>.config.json",
    )
    return parser


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    return add_common_args(parser)
