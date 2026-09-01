"""Estimate and persist per-video API costs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.cli import PROJECT_ROOT

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"
VIDEO_COST_COLUMN = "Coût Estimé (€)"


def load_pricing() -> dict[str, Any]:
    with PRICING_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def estimate_cost(step: str, *, units: float = 1.0, pricing: dict[str, Any] | None = None) -> float:
    pricing = pricing or load_pricing()
    defaults: dict[str, float] = pricing.get("defaults", {})
    unit_price = float(defaults.get(step, defaults.get("unknown", 0.01)))
    return round(unit_price * units, 4)


def fake_cost_row(step: str, amount_eur: float) -> dict[str, Any]:
    return {"step": step, "amount_eur": amount_eur, "dry_run": True}


def add_video_cost(
    sheet_id: str,
    video_row_key: str,
    amount_eur: float,
    *,
    dry_run: bool = False,
    credentials_path: str | None = None,
) -> dict[str, Any]:
    """Increment the Coût Estimé (€) column for a video row.

    In dry-run, no Google API call is made.
    """
    payload = {
        "sheet_id": sheet_id,
        "row_key": video_row_key,
        "column": VIDEO_COST_COLUMN,
        "increment_eur": amount_eur,
    }
    if dry_run:
        return {**payload, "applied": False, "dry_run": True}

    from scripts.sheets import increment_numeric_cell

    increment_numeric_cell(
        sheet_id,
        row_key=video_row_key,
        column_name=VIDEO_COST_COLUMN,
        delta=amount_eur,
        credentials_path=credentials_path,
    )
    return {**payload, "applied": True, "dry_run": False}
