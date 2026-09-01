"""gpt-4o-mini JSON helper. No paid call in dry-run."""

from __future__ import annotations

import json
import os
from typing import Any

from scripts.costs import estimate_cost


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    dry_run: bool = False,
    model: str = "gpt-4o-mini",
    dry_run_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    if dry_run:
        payload = dry_run_payload or {
            "angle": "Angle factice (dry-run)",
            "suggested_video_title": "Titre factice dry-run",
            "public_figures": [],
            "mentions_public_figures": False,
        }
        return payload, 0.0

    from openai import OpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    usage = response.usage
    if usage and (usage.prompt_tokens or usage.completion_tokens):
        from scripts.costs import load_pricing

        rates = load_pricing().get("openai", {}).get(model, {})
        cost = (
            (usage.prompt_tokens or 0) / 1000 * float(rates.get("input_per_1k_tokens", 0.00014))
            + (usage.completion_tokens or 0) / 1000 * float(rates.get("output_per_1k_tokens", 0.00055))
        )
        return data, round(cost, 4)
    return data, estimate_cost("topic_analysis")
