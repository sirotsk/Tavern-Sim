"""
Validation script for game/image_generator.py.

Tests:
1. Tavern interior generation (1024x576) using rustic_inn template
2. Tavern interior generation (1024x576) using monastery_guesthouse template
3. Item image generation (512x512) using sample item data (cracked lute)
4. Item image generation (512x512) using sample item data (hunting trophy)
5. Disabled mode -- verifies None return when [images] enabled = false
6. Failure handling -- verifies None return + log on deliberate bad model

Usage:
    py tools/test_image_generator.py

Requires GOOGLE_API_KEY in environment (or .env file).
Creates output in tools/test_output/ (gitignored).
"""

import json
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so `game.*` imports work when invoked as
# `py tools/test_image_generator.py` from the project root directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

from game.image_generator import generate_tavern_image, generate_item_image

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("tools/test_output")
TEMPLATE_DIR = Path("templates/taverns")

# Rate limit courtesy -- free tier is 10 RPM, sleep 6s between API calls
API_SLEEP = 6

# Logging setup -- show WARNING+ from game modules to verify failure handling
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Config helpers (construct internally, do NOT read settings.toml)
# ---------------------------------------------------------------------------


def _enabled_config() -> dict:
    """Config dict with images enabled and the correct model."""
    return {
        "images": {
            "enabled": True,
            "model": "gemini-2.0-flash-exp-image-generation",
        }
    }


def _disabled_config() -> dict:
    """Config dict with images disabled."""
    return {
        "images": {
            "enabled": False,
            "model": "gemini-2.0-flash-exp-image-generation",
        }
    }


def _bad_model_config() -> dict:
    """Config dict with a deliberately nonexistent model."""
    return {
        "images": {
            "enabled": True,
            "model": "nonexistent-model-12345",
        }
    }


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------


def test_1_tavern_rustic_inn() -> bool:
    """Test 1: Generate tavern interior from rustic_inn template."""
    print("\n--- Test 1: Tavern interior (rustic_inn) ---")
    template_path = TEMPLATE_DIR / "rustic_inn.json"
    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    output_path = OUTPUT_DIR / "test_tavern_rustic_inn.png"
    config = _enabled_config()

    result = generate_tavern_image(template, output_path, config)
    if result is None:
        print("FAIL: generate_tavern_image returned None")
        return False

    if not result.exists():
        print(f"FAIL: Output file not found at {result}")
        return False

    # Verify dimensions with Pillow
    from PIL import Image as PILImage
    img = PILImage.open(result)
    w, h = img.size
    if (w, h) != (1024, 576):
        print(f"FAIL: Expected 1024x576, got {w}x{h}")
        return False

    print(f"PASS: Tavern image saved ({w}x{h}) -> {result}")
    return True


def test_2_tavern_monastery() -> bool:
    """Test 2: Generate tavern interior from monastery_guesthouse template."""
    print("\n--- Test 2: Tavern interior (monastery_guesthouse) ---")
    print(f"Sleeping {API_SLEEP}s (rate limit)...")
    time.sleep(API_SLEEP)

    template_path = TEMPLATE_DIR / "monastery_guesthouse.json"
    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    output_path = OUTPUT_DIR / "test_tavern_monastery.png"
    config = _enabled_config()

    result = generate_tavern_image(template, output_path, config)
    if result is None:
        print("FAIL: generate_tavern_image returned None")
        return False

    if not result.exists():
        print(f"FAIL: Output file not found at {result}")
        return False

    from PIL import Image as PILImage
    img = PILImage.open(result)
    w, h = img.size
    if (w, h) != (1024, 576):
        print(f"FAIL: Expected 1024x576, got {w}x{h}")
        return False

    print(f"PASS: Tavern image saved ({w}x{h}) -> {result}")
    return True


def test_3_item_lute() -> bool:
    """Test 3: Generate item image (cracked lute)."""
    print("\n--- Test 3: Item image (cracked lute) ---")
    print(f"Sleeping {API_SLEEP}s (rate limit)...")
    time.sleep(API_SLEEP)

    output_path = OUTPUT_DIR / "test_item_lute.png"
    config = _enabled_config()

    result = generate_item_image(
        "Cracked lute",
        "A cracked lute hanging crookedly on the wall, missing two strings",
        output_path,
        config,
    )
    if result is None:
        print("FAIL: generate_item_image returned None")
        return False

    if not result.exists():
        print(f"FAIL: Output file not found at {result}")
        return False

    from PIL import Image as PILImage
    img = PILImage.open(result)
    w, h = img.size
    if (w, h) != (512, 512):
        print(f"FAIL: Expected 512x512, got {w}x{h}")
        return False

    print(f"PASS: Item image saved ({w}x{h}) -> {result}")
    return True


def test_4_item_trophy() -> bool:
    """Test 4: Generate item image (hunting trophy)."""
    print("\n--- Test 4: Item image (hunting trophy) ---")
    print(f"Sleeping {API_SLEEP}s (rate limit)...")
    time.sleep(API_SLEEP)

    output_path = OUTPUT_DIR / "test_item_trophy.png"
    config = _enabled_config()

    result = generate_item_image(
        "Hunting trophy",
        "A mounted stag's head above the fireplace, glass eyes catching the firelight",
        output_path,
        config,
    )
    if result is None:
        print("FAIL: generate_item_image returned None")
        return False

    if not result.exists():
        print(f"FAIL: Output file not found at {result}")
        return False

    from PIL import Image as PILImage
    img = PILImage.open(result)
    w, h = img.size
    if (w, h) != (512, 512):
        print(f"FAIL: Expected 512x512, got {w}x{h}")
        return False

    print(f"PASS: Item image saved ({w}x{h}) -> {result}")
    return True


def test_5_disabled_mode() -> bool:
    """Test 5: Disabled mode returns None without API calls."""
    print("\n--- Test 5: Disabled mode ---")
    template_path = TEMPLATE_DIR / "rustic_inn.json"
    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    output_path = OUTPUT_DIR / "test_disabled_should_not_exist.png"
    # Clean up any stale file from a previous run
    if output_path.exists():
        output_path.unlink()

    config = _disabled_config()
    result = generate_tavern_image(template, output_path, config)

    if result is not None:
        print(f"FAIL: Expected None, got {result}")
        return False

    if output_path.exists():
        print("FAIL: File was created despite images being disabled")
        return False

    print("PASS: Disabled mode returns None (no file created)")
    return True


def test_6_bad_model() -> bool:
    """Test 6: Bad model returns None without raising exception."""
    print("\n--- Test 6: Failure handling (bad model) ---")
    template_path = TEMPLATE_DIR / "rustic_inn.json"
    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    output_path = OUTPUT_DIR / "test_bad_model_should_not_exist.png"
    if output_path.exists():
        output_path.unlink()

    config = _bad_model_config()

    try:
        result = generate_tavern_image(template, output_path, config)
    except Exception as exc:
        print(f"FAIL: Exception raised instead of returning None: {exc}")
        return False

    if result is not None:
        print(f"FAIL: Expected None from bad model, got {result}")
        return False

    print("PASS: Bad model returns None (no crash)")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    load_dotenv()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Image Generator Validation Script")
    print("=" * 60)

    # Critical tests (image generation must succeed)
    critical_tests = [
        ("Test 1: Tavern rustic_inn", test_1_tavern_rustic_inn),
        ("Test 2: Tavern monastery", test_2_tavern_monastery),
        ("Test 3: Item lute", test_3_item_lute),
        ("Test 4: Item trophy", test_4_item_trophy),
    ]

    # Non-critical tests (defense/edge cases)
    defense_tests = [
        ("Test 5: Disabled mode", test_5_disabled_mode),
        ("Test 6: Bad model", test_6_bad_model),
    ]

    results: dict[str, bool] = {}

    for name, test_fn in critical_tests:
        results[name] = test_fn()

    for name, test_fn in defense_tests:
        results[name] = test_fn()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\n{passed}/{total} tests passed")

    # List generated files
    generated = list(OUTPUT_DIR.glob("test_*.png"))
    if generated:
        print(f"\nGenerated files for visual review:")
        for f in sorted(generated):
            print(f"  {f}")

    # Exit code: 0 if all critical tests pass, 1 otherwise
    critical_passed = all(
        results.get(name, False) for name, _ in critical_tests
    )
    if not critical_passed:
        print("\nCRITICAL: One or more generation tests failed.")
        sys.exit(1)

    print("\nAll critical tests passed. Review generated images visually.")
    sys.exit(0)


if __name__ == "__main__":
    main()
