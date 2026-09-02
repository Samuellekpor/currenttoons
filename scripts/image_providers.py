"""Shared image generation (Replicate / fal.ai). Preview first; upscale later."""

from __future__ import annotations

import hashlib
import os
from typing import Any
from urllib.parse import quote

from scripts.costs import estimate_cost

CARICATURE_PROMPT = (
    "Transform this photo into a realistic 3D caricature. Keep the face recognizable "
    "while exaggerating expression and head size. Preserve skin texture, pores, wrinkles, "
    "hairstyle, clothing, and posture with a high-end animated film look and detailed, "
    "lifelike surfaces."
)

REPLICATE_IMG2IMG_DEFAULT = "black-forest-labs/flux-kontext-pro"
REPLICATE_TXT2IMG_DEFAULT = "black-forest-labs/flux-schnell"
FAL_IMG2IMG_DEFAULT = "fal-ai/flux-pro/kontext"
FAL_TXT2IMG_DEFAULT = "fal-ai/flux/schnell"


def _provider() -> str:
    explicit = (os.environ.get("IMAGE_PROVIDER") or "").strip().lower()
    if explicit in {"replicate", "fal"}:
        return explicit
    if os.environ.get("REPLICATE_API_TOKEN"):
        return "replicate"
    if os.environ.get("FAL_KEY"):
        return "fal"
    raise RuntimeError("Set REPLICATE_API_TOKEN or FAL_KEY (or IMAGE_PROVIDER)")


def _output_url(output: Any) -> str:
    if output is None:
        raise RuntimeError("Image API returned an empty result")
    if isinstance(output, (list, tuple)):
        return _output_url(output[0])
    if isinstance(output, dict):
        for key in ("url", "image", "images"):
            if key in output:
                return _output_url(output[key])
    return str(getattr(output, "url", output))


def _replicate_run(model: str, payload: dict[str, Any]) -> str:
    import replicate

    token = os.environ.get("REPLICATE_API_TOKEN")
    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is not set")
    return _output_url(replicate.run(model, input=payload))


def _fal_run(model: str, payload: dict[str, Any]) -> str:
    import requests

    key = os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("FAL_KEY is not set")
    url = f"https://fal.run/{model.lstrip('/')}"
    response = requests.post(
        url,
        json=payload,
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"fal.ai error {response.status_code}: {response.text[:300]}")
    data = response.json()
    if data.get("images"):
        return _output_url(data["images"])
    if data.get("image"):
        return _output_url(data["image"])
    return _output_url(data)


def generate_image(
    prompt: str,
    aspect_ratio: str,
    reference_image_url: str | None = None,
    *,
    quality: str = "preview",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate one image. quality=preview for review; quality=final for upscale/montage."""
    slug = hashlib.sha1(f"{prompt}|{aspect_ratio}|{reference_image_url}|{quality}".encode()).hexdigest()[:12]
    if dry_run:
        return {
            "url": f"https://dry-run.local/images/{quote(slug)}.png",
            "quality": quality,
            "aspect_ratio": aspect_ratio,
            "reference_image_url": reference_image_url,
            "cost_eur": 0.0,
            "dry_run": True,
            "provider": "dry-run",
        }

    provider = _provider()
    cost_step = "image_preview" if quality == "preview" else "image_generation"
    if quality == "final" and reference_image_url:
        cost_step = "image_upscale" if "upscale" in prompt.lower() else "image_generation"

    if provider == "replicate":
        if reference_image_url:
            model = os.environ.get("REPLICATE_IMG2IMG_MODEL") or REPLICATE_IMG2IMG_DEFAULT
            payload = {
                "prompt": prompt,
                "input_image": reference_image_url,
                "aspect_ratio": aspect_ratio,
            }
        else:
            model = os.environ.get("REPLICATE_TXT2IMG_MODEL") or REPLICATE_TXT2IMG_DEFAULT
            payload = {"prompt": prompt, "aspect_ratio": aspect_ratio}
            if quality == "preview":
                payload["go_fast"] = True
        url = _replicate_run(model, payload)
    else:
        if reference_image_url:
            model = os.environ.get("FAL_IMG2IMG_MODEL") or FAL_IMG2IMG_DEFAULT
            payload = {"prompt": prompt, "image_url": reference_image_url, "aspect_ratio": aspect_ratio}
        else:
            model = os.environ.get("FAL_TXT2IMG_MODEL") or FAL_TXT2IMG_DEFAULT
            payload = {"prompt": prompt, "image_size": "portrait_16_9" if aspect_ratio == "9:16" else "landscape_16_9"}
            if aspect_ratio == "1:1":
                payload["image_size"] = "square"
        url = _fal_run(model, payload)

    return {
        "url": url,
        "quality": quality,
        "aspect_ratio": aspect_ratio,
        "reference_image_url": reference_image_url,
        "cost_eur": estimate_cost(cost_step),
        "dry_run": False,
        "provider": provider,
    }


def upscale_image(image_url: str, *, dry_run: bool = False) -> dict[str, Any]:
    """High-res pass for retained previews, just before montage."""
    prompt = "Upscale this image, keep identity, composition, and details. Do not restyle."
    return generate_image(
        prompt,
        "match_input_image",
        reference_image_url=image_url,
        quality="final",
        dry_run=dry_run,
    )
