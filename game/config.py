"""Load settings.toml configuration."""
import tomllib
from pathlib import Path


def load_config(path: str = "settings.toml") -> dict:
    """Read settings.toml and return config dict.

    Note: tomllib requires binary mode ("rb") — do NOT use "r" (raises TypeError).
    """
    config_path = Path(path)
    with open(config_path, "rb") as f:  # "rb" is required — not "r"
        return tomllib.load(f)


def get_model_name(config: dict) -> str:
    """Extract model name from config. Raises KeyError if not set."""
    return config["model"]["name"]


def get_patron_count(config: dict) -> int:
    """Pick a random patron count within the configured range."""
    import random
    min_count = config["session"].get("patron_min", 2)
    max_count = config["session"].get("patron_max", 5)
    return random.randint(min_count, max_count)


def get_object_count_range(config: dict) -> tuple[int, int]:
    """Get min/max examinable object count from config."""
    session = config.get("session", {})
    return session.get("object_min", 4), session.get("object_max", 7)


def get_ambient_chance(config: dict) -> float:
    """Get ambient text trigger probability from config."""
    return config.get("narrator", {}).get("ambient_chance", 0.25)


def get_economy_config(config: dict) -> dict:
    """Return economy settings with safe defaults."""
    econ = config.get("economy", {})
    return {
        "starting_gold_min": econ.get("starting_gold_min", 10),
        "starting_gold_max": econ.get("starting_gold_max", 25),
    }


def get_size_ranges(config: dict, size: str) -> dict:
    """Return count ranges for all scalable entities at the given tavern size.

    Reads from [session.sizes.{size}] in settings.toml, with hardcoded
    defaults matching the user-specified ranges:
        small:  2-3 patrons, 3-4 objects, 2 shop, 3 drinks + 2 food
        medium: 3-5 patrons, 4-6 objects, 3 shop, 4 drinks + 3 food
        large:  5-8 patrons, 6-8 objects, 4 shop, 5 drinks + 4 food
    """
    defaults = {
        "small":  {"patron_min": 2, "patron_max": 3, "object_min": 3, "object_max": 4, "shop_count": 2, "menu_drinks": 3, "menu_food": 2},
        "medium": {"patron_min": 3, "patron_max": 5, "object_min": 4, "object_max": 6, "shop_count": 3, "menu_drinks": 4, "menu_food": 3},
        "large":  {"patron_min": 5, "patron_max": 8, "object_min": 6, "object_max": 8, "shop_count": 4, "menu_drinks": 5, "menu_food": 4},
    }
    sizes_cfg = config.get("session", {}).get("sizes", {})
    size_cfg = sizes_cfg.get(size, {})
    return {**defaults.get(size, defaults["medium"]), **size_cfg}


def get_images_config(config: dict) -> dict:
    """Return image generation settings with safe defaults.

    Returns dict with keys:
        enabled (bool): Whether image generation is active
        model (str): Gemini model ID for image generation
    """
    images = config.get("images", {})
    return {
        "enabled": images.get("enabled", False),
        "model": images.get("model", "gemini-2.0-flash-exp-image-generation"),
    }
