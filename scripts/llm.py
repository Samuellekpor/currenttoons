"""gpt-4o-mini JSON helper. No paid call in dry-run. Light retry on API failures."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from scripts.costs import estimate_cost


def _cost_from_usage(model: str, usage: Any, fallback_step: str) -> float:
    if usage and (usage.prompt_tokens or usage.completion_tokens):
        from scripts.costs import load_pricing

        rates = load_pricing().get("openai", {}).get(model, {})
        return round(
            (usage.prompt_tokens or 0) / 1000 * float(rates.get("input_per_1k_tokens", 0.00014))
            + (usage.completion_tokens or 0) / 1000 * float(rates.get("output_per_1k_tokens", 0.00055)),
            4,
        )
    return estimate_cost(fallback_step)


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    dry_run: bool = False,
    model: str = "gpt-4o-mini",
    dry_run_payload: dict[str, Any] | None = None,
    cost_step: str = "topic_analysis",
    max_attempts: int = 3,
) -> tuple[dict[str, Any], float]:
    if dry_run:
        payload = dry_run_payload or {
            "angle": "Angle factice (dry-run)",
            "suggested_video_title": "Titre factice dry-run",
            "public_figures": [],
            "mentions_public_figures": False,
        }
        return payload, 0.0

    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI()
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
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
            return data, _cost_from_usage(model, response.usage, cost_step)
        except json.JSONDecodeError as exc:
            last_error = exc
        except (RateLimitError, APIConnectionError, APIStatusError) as exc:
            last_error = exc
            status = getattr(exc, "status_code", None)
            if isinstance(exc, APIStatusError) and status and status < 500 and status != 429:
                raise RuntimeError(f"OpenAI API error ({status}): {exc}") from exc
        time.sleep(min(1.5 * (attempt + 1), 8))
    raise RuntimeError(f"OpenAI API failed after {max_attempts} attempts: {last_error}") from last_error
