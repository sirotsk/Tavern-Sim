# IMPORTANT: Use 'from google import genai' (package: google-genai==1.64.0)
# NOT 'import google.generativeai' (google-generativeai — DEPRECATED, different API)
# Correct: from google import genai
# Wrong:   import google.generativeai as genai
# Warning signs of wrong SDK: .GenerativeModel(), .configure(api_key=...), top-level .generate_content()
from google import genai
from google.genai import types

# Single shared client — created once at module import time.
# Do NOT create genai.Client() inside agents, per-request, or per-patron — documented anti-pattern.
# ensure_api_key() in main.py MUST be called before this module is imported.
client = genai.Client()

# Safety settings tuned for tavern content — alcohol, rough speech, threats are staples of the game.
# Without this config, Gemini's defaults may block legitimate tavern narrative content.
# Applied to all content-generating calls via: config=SAFETY_CONFIG
#
# BLOCK_ONLY_HIGH: Only block content that is clearly and severely harmful.
# This allows rough tavern dialogue, alcohol references, and mild threats while blocking actual harm.
#
# SafetySetting form used: string literals (validated against google-genai==1.64.0 — SDK accepts
# string literals and coerces them to the corresponding HarmCategory/HarmBlockThreshold enums).
SAFETY_CONFIG = types.GenerateContentConfig(
    safety_settings=[
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
)


def safe_generate(model_name: str, prompt: str, extra_config: dict | None = None) -> str:
    """
    Make a content generation call with tavern-safe settings applied.

    Always use this function instead of calling client.models.generate_content() directly,
    so safety settings are consistently applied across all game content.

    Args:
        model_name: From config["model"]["name"] — never hardcode this.
        prompt: The content prompt.
        extra_config: Optional additional config fields (e.g. response_mime_type for structured outputs).
                      Merged with SAFETY_CONFIG settings.

    Returns:
        Response text, or a fallback string if the response is safety-blocked.
    """
    config_kwargs: dict = {
        "safety_settings": SAFETY_CONFIG.safety_settings,
    }
    if extra_config:
        config_kwargs.update(extra_config)

    config = types.GenerateContentConfig(**config_kwargs)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=config,
    )

    # Always check finish_reason — never let a safety block crash the game
    candidate = response.candidates[0] if response.candidates else None
    if candidate and str(candidate.finish_reason) == "FinishReason.SAFETY":
        return "[The moment passes quietly.]"

    return response.text or ""
