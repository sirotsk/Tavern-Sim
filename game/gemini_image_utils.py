"""Shared Gemini image generation utilities.

Used by:
- tools/generate_portrait.py (portrait production CLI)
- game/image_generator.py (runtime tavern/item image generation)

Provides the common API call pattern and Pillow post-processing
so both consumers share identical error handling and image processing.
"""

import io
import logging
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image as PILImage

logger = logging.getLogger(__name__)

# Safety settings for image generation — identical values to agents/base_agent.py
# but defined here to avoid importing from agents/ (layer boundary: game/ never imports agents/).
# BLOCK_ONLY_HIGH: Only block clearly and severely harmful content.
_SAFETY_SETTINGS = [
    types.SafetySetting(
        category="HARM_CATEGORY_HARASSMENT",
        threshold="BLOCK_ONLY_HIGH",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="BLOCK_ONLY_HIGH",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
        threshold="BLOCK_ONLY_HIGH",
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_ONLY_HIGH",
    ),
]


def generate_image_from_prompt(prompt: str, model: str, client=None) -> bytes | None:
    """Call Gemini to generate an image from a text prompt.

    Args:
        prompt: The text prompt describing the image to generate.
        model: Gemini model ID (must support response_modalities=["TEXT", "IMAGE"]).
        client: Optional genai.Client instance. If None, creates a new one
                (suitable for standalone CLI tools that manage their own .env loading).

    Returns:
        Raw image bytes on success, or None on any failure.
        Failures are logged at WARNING level (image generation is non-critical).
    """
    if client is None:
        client = genai.Client()

    try:
        config = types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            safety_settings=_SAFETY_SETTINGS,
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        # Check for empty or safety-blocked response
        if not response.candidates:
            logger.warning("Image generation returned no candidates (prompt may have been blocked)")
            return None

        candidate = response.candidates[0]
        if str(candidate.finish_reason) == "FinishReason.SAFETY":
            logger.warning("Image generation blocked by safety filter")
            return None

        # Look for image data in response parts
        for part in candidate.content.parts:
            if part.inline_data is not None:
                img_obj = part.as_image()
                return img_obj.image_bytes

        # No image parts found — log any text parts for diagnosis
        text_parts = [
            p.text for p in candidate.content.parts
            if hasattr(p, "text") and p.text
        ]
        logger.warning("No image data in response. Text parts: %s", text_parts)
        return None

    except Exception:
        logger.warning("Image generation failed", exc_info=True)
        return None


def resize_and_save(image_bytes: bytes, output_path: Path, width: int, height: int) -> Path:
    """Resize raw image bytes and save as a PNG file.

    Args:
        image_bytes: Raw image bytes (from generate_image_from_prompt).
        output_path: Where to save the resulting PNG.
        width: Target width in pixels.
        height: Target height in pixels.

    Returns:
        The output_path (same as input, for chaining convenience).
    """
    pil_img = PILImage.open(io.BytesIO(image_bytes))
    pil_img = pil_img.resize((width, height), PILImage.LANCZOS)
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pil_img.save(output_path, format="PNG")
    return output_path
