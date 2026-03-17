"""
Image generator for tavern interiors and examinable items.

Produces pixel art PNGs via the Gemini native image generation API.
Two subject types:
  - Tavern interior (1024x576, 16:9 widescreen)
  - Item image (512x512 square, dark wood background)

Usage:
    from game.image_generator import generate_tavern_image, generate_item_image

Failure handling: All public functions return Path | None.
    - None = generation failed (API error, safety filter, timeout, disabled)
    - Calling code continues without crashing
    - Failures are logged via the standard logging module

Configuration: Reads [images] section from settings.toml via config dict.
    - enabled = false: all functions return None immediately (zero API calls)
    - model: Gemini model ID for image generation
"""

import logging
from pathlib import Path

from game.config import get_images_config
from game.gemini_image_utils import generate_image_from_prompt, resize_and_save

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Style constants — pixel art aesthetic shared across all generated images
# ---------------------------------------------------------------------------

PIXEL_ART_STYLE = (
    "2D pixel art, limited warm color palette (ambers, browns, earthy reds), "
    "visible pixellation, hand-crafted sprite aesthetic, "
    "no anti-aliasing, no photo-realism, no 3D rendering, no text or lettering."
)

TAVERN_STYLE = (
    f"Wide establishing shot showing the full room — an interior diorama view. "
    f"Warm candlelit amber and orange tones, wooden beams, medieval tavern. "
    f"{PIXEL_ART_STYLE}"
)

ITEM_STYLE = (
    f"Single item centered on a dark oak wood tavern table surface. "
    f"Natural item colors — greens, reds, golds, browns as appropriate for the object. "
    f"{PIXEL_ART_STYLE}"
)

# ---------------------------------------------------------------------------
# Target dimensions
# ---------------------------------------------------------------------------

TAVERN_WIDTH, TAVERN_HEIGHT = 1024, 576   # 16:9 widescreen
ITEM_WIDTH, ITEM_HEIGHT = 512, 512        # Square


def generate_tavern_image(
    tavern_template: dict,
    output_path: Path,
    config: dict,
) -> Path | None:
    """Generate a pixel art tavern interior image from a tavern template.

    Args:
        tavern_template: Parsed tavern template dict (e.g. from rustic_inn.json)
            with 'atmosphere' and 'layout' keys.
        output_path: Where to save the resulting PNG (1024x576).
        config: Full settings.toml config dict (passed to get_images_config).

    Returns:
        Path to the saved PNG on success, or None if generation is disabled,
        fails, or is blocked by safety filters.
    """
    try:
        images_cfg = get_images_config(config)
        if not images_cfg["enabled"]:
            return None

        model = images_cfg["model"]

        # Build prompt from template atmosphere and layout
        atmosphere = tavern_template.get("atmosphere", {})
        mood = atmosphere.get("mood", "")
        lighting = atmosphere.get("lighting", "")
        layout = tavern_template.get("layout", "")

        prompt = (
            f"A medieval tavern interior. {layout} "
            f"The atmosphere: {mood}. Lighting: {lighting}. "
            f"{TAVERN_STYLE}"
        )

        image_bytes = generate_image_from_prompt(prompt, model)
        if image_bytes is None:
            logger.warning(
                "Tavern image generation returned no image for template %s",
                tavern_template.get("id", "unknown"),
            )
            return None

        result = resize_and_save(image_bytes, output_path, TAVERN_WIDTH, TAVERN_HEIGHT)
        logger.info("Tavern image saved: %s (%dx%d)", result, TAVERN_WIDTH, TAVERN_HEIGHT)
        return result

    except Exception:
        logger.warning("Tavern image generation failed unexpectedly", exc_info=True)
        return None


def generate_item_image(
    item_name: str,
    item_description: str,
    output_path: Path,
    config: dict,
) -> Path | None:
    """Generate a pixel art item image for an examinable object.

    Args:
        item_name: Short name of the item (e.g. "cracked lute").
        item_description: Longer description from the narrator's output.
        output_path: Where to save the resulting PNG (512x512).
        config: Full settings.toml config dict (passed to get_images_config).

    Returns:
        Path to the saved PNG on success, or None if generation is disabled,
        fails, or is blocked by safety filters.
    """
    try:
        images_cfg = get_images_config(config)
        if not images_cfg["enabled"]:
            return None

        model = images_cfg["model"]

        prompt = f"A {item_name}: {item_description}. {ITEM_STYLE}"

        image_bytes = generate_image_from_prompt(prompt, model)
        if image_bytes is None:
            logger.warning("Item image generation returned no image for %r", item_name)
            return None

        result = resize_and_save(image_bytes, output_path, ITEM_WIDTH, ITEM_HEIGHT)
        logger.info("Item image saved: %s (%dx%d)", result, ITEM_WIDTH, ITEM_HEIGHT)
        return result

    except Exception:
        logger.warning("Item image generation failed unexpectedly", exc_info=True)
        return None
