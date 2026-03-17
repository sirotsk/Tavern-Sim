"""
Session setup — generates a fresh tavern + patron set every launch.

Flow:
1. Load all tavern templates and pick one (random or config-specified)
2. Generate tavern name using Faker + template theme
3. Load patron archetypes, apply tavern weights, pick N unique archetypes
4. For each patron: call Gemini structured output to expand archetype -> full profile
5. Generate barkeep profile from the tavern's barkeep template
6. Write all profiles to agent_profiles/ (cleared fresh each run)
7. Populate GameState with tavern name, patron records, barkeep name
8. Generate examinable objects and ambient text pool (written to tavern.json)
9. Generate tavern + item images in parallel (skipped when [images] enabled = false)
"""
import concurrent.futures
import json
import logging
import re
import random
import shutil
from pathlib import Path

from pydantic import BaseModel, Field
from typing import List

from game.state import GameState, PatronRecord
from game.names import generate_patron_name, generate_tavern_name
from agents.base_agent import safe_generate
from game.image_generator import generate_tavern_image, generate_item_image
from game.config import get_images_config

logger = logging.getLogger(__name__)


def _sanitize_name(name: str) -> str:
    """Convert item name to a safe filename slug.

    Apostrophes and similar punctuation are removed entirely (not replaced
    with underscores) so "hunter's knife" -> "hunters_knife" not "hunter_s_knife".

    Examples:
        "cracked lute"     -> "cracked_lute"
        "hunter's knife"   -> "hunters_knife"
        "Carved Bone Dice" -> "carved_bone_dice"
        ""                 -> "item"
        "---"              -> "item"
    """
    # Remove apostrophes and similar "joining" punctuation before general slugify
    stripped = re.sub(r"[''`]", "", name.lower())
    slug = re.sub(r"[^a-z0-9]+", "_", stripped).strip("_")
    return slug or "item"


# --- Pydantic schemas for Gemini structured outputs ---

class PatronIdentity(BaseModel):
    name: str = Field(description="Full medieval name (first and last). Use a name fitting the medieval period.")
    role: str = Field(description="Occupation or social role, e.g. 'traveling merchant'.")
    age: int = Field(description="Approximate age in years, between 18 and 70.")
    gender: str = Field(description="'male' or 'female'. Choose based on the name and character you create.")


class PatronPersonality(BaseModel):
    traits: List[str] = Field(description="2-4 personality traits, e.g. ['suspicious', 'talkative'].")
    speaking_style: str = Field(description="1-2 sentences describing how this character speaks.")
    mood: str = Field(description="Current emotional state at the start of the session (single word or brief phrase).")
    quirks: List[str] = Field(description="1-2 memorable behavioral quirks.")
    likes: List[str] = Field(description="3-5 topics, activities, or things this character genuinely enjoys discussing or doing. Period-appropriate for 1350s England. Examples: 'tales of distant lands', 'strong ale', 'honest craftsmanship'.")
    dislikes: List[str] = Field(description="3-5 topics, activities, or things this character actively dislikes or resents. Period-appropriate for 1350s England. Examples: 'tax collectors', 'braggarts', 'nobility'.")


class PatronAppearance(BaseModel):
    brief: str = Field(description="A short 5-10 word label for the narrator to refer to this patron before the player knows their name. Example: 'A broad-shouldered man with gnarled hands'. Do NOT include the character's name.")
    description: str = Field(description="2-3 sentence physical description. Be specific and vivid. Humans only — no fantasy races.")
    keywords: list[str] = Field(description="2-4 words a player might type to examine this patron, derived from their physical appearance (e.g. ['tall', 'bearded', 'scarred'])")


class PatronBackstory(BaseModel):
    history: str = Field(description="Brief personal history in 1-2 sentences.")
    reason_at_tavern: str = Field(description="Why this specific patron is in the tavern tonight.")


class PatronProfile(BaseModel):
    identity: PatronIdentity
    personality: PatronPersonality
    appearance: PatronAppearance
    backstory: PatronBackstory


class BarkeepProfile(BaseModel):
    identity: PatronIdentity
    personality: PatronPersonality
    appearance: PatronAppearance
    backstory: PatronBackstory
    # Same structure as patron; dual_role_context is baked into the prompt


class ExaminableObject(BaseModel):
    name: str = Field(description="Short object name (1-3 words), e.g. 'cracked lute', 'hunting trophies'")
    brief: str = Field(description="5-10 word label shown in the look list, e.g. 'A cracked lute hanging crookedly on the wall'")
    detailed: str = Field(description="2-3 sentence description shown when player examines this object. Include sensory detail — sight, touch, smell.")
    keywords: list[str] = Field(description="2-4 keywords a player might type to examine this object, e.g. ['lute', 'instrument', 'music']")
    pickable: bool = Field(default=False, description="True if player can pick up this item and add it to their inventory. Only 1-2 items per tavern should be pickable. Items like loose coins, a forgotten knife, or a small trinket left behind.")
    usable_in_place: bool = Field(default=False, description="True if player can interact with this item without picking it up. Items like a fireplace, a dartboard, a noticeboard. 1-2 items per tavern.")
    use_text: str = Field(default="", description="Response shown when player uses this item in place (1-2 sentences). Required if usable_in_place is True. Describe what happens when the player interacts.")


class ExaminablesResponse(BaseModel):
    objects: list[ExaminableObject]


class AmbientPoolResponse(BaseModel):
    lines: list[str] = Field(description="Each line is one sentence of ambient flavor text, 10-20 words. Mix patron activity and environmental observations.")


class ShopItem(BaseModel):
    name: str = Field(description="Short item name (2-4 words), e.g. 'Lucky rabbit foot', 'Silver ring', 'Carved bone dice'")
    description: str = Field(description="2-3 sentence description shown on 'examine inv'. Include sensory detail and hints about origin.")
    price: int = Field(description="Cost in gold coins (integer, between 5 and 20)")


class ShopInventoryResponse(BaseModel):
    items: list[ShopItem]


AGENT_PROFILES_DIR = Path("agent_profiles")
TAVERN_TEMPLATES_DIR = Path("templates/taverns")
PATRON_TEMPLATES_DIR = Path("templates/patrons")
BARKEEP_TEMPLATES_DIR = Path("templates/barkeeps")

SIZE_DESCRIPTORS = {
    "small": "cramped and intimate, with only a handful of souls present",
    "medium": "moderately busy, neither packed nor empty",
    "large": "sprawling and loud, a proper crowd filling the room",
}


class SessionSetup:
    """Orchestrates fresh session generation each launch."""

    def __init__(self, client, config: dict, state: GameState, model_name: str = "", progress_callback=None):
        self.client = client
        self.config = config
        self.state = state
        # model_name comes from config["model"]["name"] — never hardcoded
        self.model_name: str = model_name or config.get("model", {}).get("name", "")
        self.progress_callback = progress_callback

    def _report_progress(self, step: str, percent: int) -> None:
        """Report a progress step via the callback, if one was provided.

        Args:
            step: Human-readable description of the current setup step.
            percent: Progress percentage (0-100).
        """
        if self.progress_callback:
            self.progress_callback(step, percent)

    def run(self) -> None:
        """Run full session setup. Populates self.state in place."""
        # 1. Clear and recreate agent_profiles/ — fresh session, no stale files
        if AGENT_PROFILES_DIR.exists():
            shutil.rmtree(AGENT_PROFILES_DIR)
        AGENT_PROFILES_DIR.mkdir()
        # Restore .gitkeep so git continues to track the directory
        (AGENT_PROFILES_DIR / ".gitkeep").touch()
        self._report_progress("Generating your tavern...", 10)

        # 2. Pick tavern template
        tavern_template = self._pick_tavern_template()

        # 2b. Determine tavern size
        self._tavern_size = self._determine_size(tavern_template)

        # 3. Generate tavern name
        self.state.tavern_name = generate_tavern_name(tavern_template["name_theme"])
        self._report_progress("Naming the tavern...", 20)

        # 4. Save tavern data to agent_profiles/tavern.json
        tavern_data = {
            "tavern_name": self.state.tavern_name,
            "template": tavern_template,
        }
        # Add size, menu subset, and game subset to tavern data before writing
        tavern_data["tavern_size"] = self._tavern_size
        tavern_data["menu_subset"] = self._select_menu_subset(tavern_template, self._tavern_size)
        tavern_data["available_games"] = self._select_game_subset(tavern_template)
        (AGENT_PROFILES_DIR / "tavern.json").write_text(
            json.dumps(tavern_data, indent=2), encoding="utf-8"
        )

        # 5. Pick patron archetypes (unique, weighted by tavern preference)
        patron_count = self._get_patron_count(self._tavern_size)
        archetypes = self._load_all_archetypes()
        weights = tavern_template.get("patron_archetype_weights", {})
        selected_archetypes = self._weighted_unique_selection(archetypes, weights, patron_count)

        # 6. Generate patron profiles
        self._report_progress("Creating patrons...", 30)
        for i, archetype in enumerate(selected_archetypes):
            profile = self._generate_patron_profile(archetype, tavern_template)
            profile_path = AGENT_PROFILES_DIR / f"patron_{i+1:03d}.json"
            profile_path.write_text(
                json.dumps(profile, indent=2), encoding="utf-8"
            )
            # Add patron record to state (name hidden — revealed on first talk)
            appearance = profile.get("appearance", {})
            # Normalize gender from Gemini response
            raw_gender = profile.get("identity", {}).get("gender", "male")
            gender = raw_gender.lower().strip()
            if gender == "man":
                gender = "male"
            elif gender == "woman":
                gender = "female"
            if gender not in ("male", "female"):
                gender = "male"
            record = PatronRecord(
                profile_path=str(profile_path),
                description=appearance.get("description", "A figure sits nearby."),
                brief_description=appearance.get("brief", "A mysterious figure"),
                name=None,  # Not revealed until player talks to them
                keywords=appearance.get("keywords", []),
                archetype_id=archetype["id"],
                gender=gender,
            )
            self.state.patrons.append(record)

        # 6b. Assign patron gold from template ranges
        patron_gold_ranges = tavern_template.get("patron_gold_ranges", {})
        for i, patron_record in enumerate(self.state.patrons):
            archetype_id = selected_archetypes[i].get("id", "") if i < len(selected_archetypes) else ""
            gold_range = patron_gold_ranges.get(archetype_id, [5, 15])
            patron_record.gold = random.randint(gold_range[0], gold_range[1])

        # 7. Generate barkeep profile
        self._report_progress("Generating barkeep...", 55)
        barkeep_weights = tavern_template.get("barkeep_archetype_weights", {})
        barkeep_template = self._load_barkeep_template(barkeep_weights)
        barkeep_profile = self._generate_barkeep_profile(barkeep_template, tavern_template)
        barkeep_profile["archetype_id"] = barkeep_template["id"]
        barkeep_path = AGENT_PROFILES_DIR / "barkeep.json"
        barkeep_path.write_text(
            json.dumps(barkeep_profile, indent=2), encoding="utf-8"
        )
        self.state.barkeep_name = barkeep_profile.get("identity", {}).get("name", "the barkeep")
        self._report_progress("Populating the room...", 70)

        # 8 & 9 & 10. Generate examinable objects, ambient pool, and shop items concurrently
        self._report_progress("Setting the atmosphere...", 85)
        if not self.progress_callback:
            print("Generating tavern objects, atmosphere, and shop items...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            objects_future = executor.submit(self._generate_examinable_objects, tavern_template)
            ambient_future = executor.submit(self._generate_ambient_pool, tavern_template)
            shop_future = executor.submit(self._generate_shop_items, tavern_template)
            examinables = objects_future.result()
            ambient_pool = ambient_future.result()
            shop_items = shop_future.result()

        # Update tavern.json with all new data
        tavern_data["examinables"] = examinables
        tavern_data["ambient_pool"] = ambient_pool
        tavern_data["shop_items"] = shop_items
        (AGENT_PROFILES_DIR / "tavern.json").write_text(
            json.dumps(tavern_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Populate GameState with seeded data
        self.state.examinables = examinables
        self.state.ambient_pool = ambient_pool
        self.state.shop_items = shop_items

        # 9. Generate images concurrently -- skipped when [images] enabled = false
        images_cfg = get_images_config(self.config)
        if images_cfg["enabled"]:
            self._report_progress("Painting the tavern walls...", 87)
            images_dir = AGENT_PROFILES_DIR / "images"
            images_dir.mkdir(exist_ok=True)

            tavern_out = images_dir / "tavern.png"
            item_paths = [
                (obj, images_dir / f"item_{_sanitize_name(obj['name'])}.png")
                for obj in examinables
            ]

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                tavern_fut = executor.submit(
                    generate_tavern_image, tavern_template, tavern_out, self.config
                )
                item_futs = [
                    (obj, executor.submit(
                        generate_item_image,
                        obj["name"], obj.get("detailed", ""), path, self.config
                    ))
                    for obj, path in item_paths
                ]
                self._report_progress("Illuminating the scene by candlelight...", 92)

                try:
                    tavern_result = tavern_fut.result(timeout=120)
                except concurrent.futures.TimeoutError:
                    logger.warning("Tavern image generation timed out")
                    tavern_result = None

                tavern_data["tavern_image_path"] = (
                    "/session-images/tavern.png" if tavern_result else None
                )

                for obj, fut in item_futs:
                    try:
                        item_result = fut.result(timeout=120)
                    except concurrent.futures.TimeoutError:
                        logger.warning(
                            "Item image generation timed out: %s", obj["name"]
                        )
                        item_result = None
                    obj["image_path"] = (
                        f"/session-images/item_{_sanitize_name(obj['name'])}.png"
                        if item_result else None
                    )

            # Re-write tavern.json with image paths included
            (AGENT_PROFILES_DIR / "tavern.json").write_text(
                json.dumps(tavern_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self.state.examinables = tavern_data["examinables"]
            self._report_progress("The tavern comes to life...", 94)

        self._report_progress("Opening the doors...", 95)
        self.state.session_active = True

    def _pick_tavern_template(self) -> dict:
        """Load and select a tavern template based on settings.toml."""
        all_templates = list(TAVERN_TEMPLATES_DIR.glob("*.json"))
        if not all_templates:
            raise FileNotFoundError(f"No tavern templates found in {TAVERN_TEMPLATES_DIR}")

        selection = self.config.get("tavern", {}).get("selection", "random")
        if selection == "random":
            template_path = random.choice(all_templates)
        else:
            # Try to find template by id slug
            template_path = TAVERN_TEMPLATES_DIR / f"{selection}.json"
            if not template_path.exists():
                template_path = random.choice(all_templates)

        return json.loads(template_path.read_text(encoding="utf-8"))

    def _determine_size(self, tavern_template: dict) -> str:
        """Pick tavern size using template-defined weights.

        Falls back to equal weights if template has no size_weights.
        """
        size_weights = tavern_template.get("size_weights", {"small": 1, "medium": 2, "large": 1})
        sizes = list(size_weights.keys())
        weights = [size_weights[s] for s in sizes]
        return random.choices(sizes, weights=weights, k=1)[0]

    def _select_menu_subset(self, tavern_template: dict, size: str) -> dict:
        """Randomly select a size-appropriate menu subset.

        Water is always included and does NOT consume a drink slot.
        Drink/food counts come from get_size_ranges().
        """
        from game.config import get_size_ranges
        ranges = get_size_ranges(self.config, size)
        drink_slots = ranges["menu_drinks"]
        food_slots = ranges["menu_food"]

        all_drinks = tavern_template.get("menu", {}).get("drinks", [])
        all_food = tavern_template.get("menu", {}).get("food", [])

        # Separate water — always present, never counts against slots
        water_items = [d for d in all_drinks if d["name"].lower() == "water"]
        non_water_drinks = [d for d in all_drinks if d["name"].lower() != "water"]

        selected_drinks = random.sample(
            non_water_drinks, min(drink_slots, len(non_water_drinks))
        )
        selected_food = random.sample(all_food, min(food_slots, len(all_food)))

        return {
            "drinks": water_items + selected_drinks,
            "food": selected_food,
        }

    def _select_game_subset(self, tavern_template: dict) -> list[str]:
        """Pick 2-3 games using template-defined weights.

        Reuses _weighted_unique_selection() with game dicts.
        Only selects from games that exist in GAME_REGISTRY.
        """
        from game.bar_games import GAME_REGISTRY
        game_weights = tavern_template.get("game_weights", {})
        all_game_ids = list(GAME_REGISTRY.keys())

        # Build pseudo-archetype dicts for _weighted_unique_selection reuse
        game_dicts = [{"id": gid} for gid in all_game_ids]
        game_count = random.randint(2, 3)
        selected = self._weighted_unique_selection(game_dicts, game_weights, game_count)
        return [g["id"] for g in selected]

    def _get_patron_count(self, size: str = "medium") -> int:
        """Get random patron count for the given size."""
        from game.config import get_size_ranges
        ranges = get_size_ranges(self.config, size)
        return random.randint(ranges["patron_min"], ranges["patron_max"])

    def _load_all_archetypes(self) -> list[dict]:
        """Load all patron archetype templates."""
        return [
            json.loads(f.read_text(encoding="utf-8"))
            for f in PATRON_TEMPLATES_DIR.glob("*.json")
        ]

    def _load_barkeep_template(self, weights: dict[str, int]) -> dict:
        """Load a barkeep template via weighted random selection from pool.

        Args:
            weights: barkeep_archetype_weights dict from tavern template.
        Returns:
            Barkeep archetype dict.
        """
        all_barkeeps = [
            json.loads(f.read_text(encoding="utf-8"))
            for f in BARKEEP_TEMPLATES_DIR.glob("*.json")
        ]
        if not all_barkeeps:
            return {"id": "default_barkeep", "role": "barkeep", "personality_traits": [],
                    "speaking_style": "", "backstory_seeds": [],
                    "allowed_genders": ["male", "female"], "dual_role_context": ""}

        # Reuse existing weighted selection, selecting 1
        selected = self._weighted_unique_selection(all_barkeeps, weights, 1)
        return selected[0] if selected else all_barkeeps[0]

    def _weighted_unique_selection(
        self, archetypes: list[dict], weights: dict[str, int], count: int
    ) -> list[dict]:
        """Select `count` unique archetypes using tavern-specific weights.

        Uses random.choices with weights for probability, then deduplicates.
        """
        if count >= len(archetypes):
            return archetypes[:]

        archetype_ids = [a["id"] for a in archetypes]
        archetype_weights = [max(weights.get(aid, 1), 1) for aid in archetype_ids]
        archetype_map = {a["id"]: a for a in archetypes}

        selected_ids: set[str] = set()
        selected: list[dict] = []
        max_attempts = count * 20  # Prevent infinite loop
        attempts = 0

        while len(selected) < count and attempts < max_attempts:
            pick = random.choices(archetype_ids, weights=archetype_weights, k=1)[0]
            if pick not in selected_ids:
                selected_ids.add(pick)
                selected.append(archetype_map[pick])
            attempts += 1

        return selected

    def _generate_patron_profile(self, archetype: dict, tavern: dict) -> dict:
        """Call Gemini to expand an archetype into a full patron profile.

        Uses safe_generate() with structured output config (JSON mode).
        Returns the profile as a plain dict (for JSON serialization).
        """
        fixed_name = archetype.get("fixed_name")
        name_instruction = (
            f'- The character\'s name MUST be exactly "{fixed_name}". Do not deviate from this name.'
            if fixed_name
            else "- The name must feel authentically medieval (no modern names)"
        )

        allowed_genders = archetype.get("allowed_genders")
        if allowed_genders and len(allowed_genders) == 1:
            gender_instruction = f"- The character MUST be {allowed_genders[0]}. This is mandatory."
        else:
            gender_instruction = "- You MUST assign a gender ('male' or 'female') in the identity section. Choose based on the name and character you create."

        prompt = f"""
You are generating a character for a medieval tavern text adventure game.
Create a realistic medieval patron based on this archetype template.

Archetype: {json.dumps(archetype, indent=2)}

Tavern context:
- Atmosphere: {tavern.get('atmosphere', {}).get('mood', 'A typical tavern')}
- Setting: {tavern.get('layout', 'A common room')}

Rules:
- Humans only — absolutely no fantasy races, magic abilities, or supernatural elements
{name_instruction}
- The character should feel like they naturally belong in this specific tavern
- Keep personality consistent with the archetype's traits and speaking style
- Make the appearance vivid and memorable — this is how the player will identify them
- IMPORTANT: Do NOT include the character's name in the appearance description. The appearance must describe ONLY physical features, clothing, and mannerisms — never mention the name. The player has not met this person yet.
- Setting: England, 1350s. The character lives in a medieval English world. No anachronisms, no modern concepts, no fantasy elements.
- Likes and dislikes must be period-appropriate — things a real person in 1350s England would care about
- Generate 3-5 likes and 3-5 dislikes that reflect the character's archetype, personality, and social station
- The character should be the kind of person who would react naturally to someone speaking strangely or slurring their words
{gender_instruction}

Generate a complete character profile.
"""
        extra_config = {
            "response_mime_type": "application/json",
            "response_json_schema": PatronProfile.model_json_schema(),
        }
        response_text = safe_generate(self.model_name, prompt, extra_config=extra_config)

        # Validate and return as dict
        profile = PatronProfile.model_validate_json(response_text)
        return profile.model_dump()

    def _generate_barkeep_profile(self, barkeep_template: dict, tavern: dict) -> dict:
        """Call Gemini to generate a barkeep profile from the barkeep template."""
        allowed_genders = barkeep_template.get("allowed_genders", ["male", "female"])
        if len(allowed_genders) == 1:
            gender_instruction = f"- The character MUST be {allowed_genders[0]}. This is mandatory."
        else:
            gender_instruction = "- You MUST assign a gender ('male' or 'female') in the identity section. Choose based on the name and character you create."

        prompt = f"""
You are generating a barkeep character for a medieval tavern text adventure game.
This character serves drinks and food AND can have conversations with the player.

Barkeep template: {json.dumps(barkeep_template, indent=2)}

Tavern context:
- Tavern name: {self.state.tavern_name}
- Atmosphere: {tavern.get('atmosphere', {}).get('mood', 'A typical tavern')}
- Dual role: {barkeep_template.get('dual_role_context', 'Serves drinks and food in addition to conversation.')}

Rules:
- Humans only — no fantasy races or magic
- Medieval name appropriate to the tavern's atmosphere
- Make the barkeep feel like they belong behind THIS specific bar
- The appearance should convey the dual role — someone who works hard and watches everything
- Setting: England, 1350s. The barkeep lives in a medieval English world. No anachronisms, no modern concepts.
- Generate 3-5 likes and 3-5 dislikes reflecting the barkeep's personality and role — what topics warm them up or cool them down in conversation
- The character should be the kind of person who would react naturally to someone speaking strangely or slurring their words
{gender_instruction}

Generate a complete barkeep profile.
"""
        extra_config = {
            "response_mime_type": "application/json",
            "response_json_schema": BarkeepProfile.model_json_schema(),
        }
        response_text = safe_generate(self.model_name, prompt, extra_config=extra_config)

        profile = BarkeepProfile.model_validate_json(response_text)
        return profile.model_dump()

    def _get_object_count(self, size: str = "medium") -> int:
        """Get random object count for the given size."""
        from game.config import get_size_ranges
        ranges = get_size_ranges(self.config, size)
        return random.randint(ranges["object_min"], ranges["object_max"])

    def _generate_examinable_objects(self, tavern_template: dict) -> list[dict]:
        """Generate examinable objects for the tavern using Gemini structured output."""
        object_count = self._get_object_count(getattr(self, "_tavern_size", "medium"))
        patron_briefs = [p.brief_description for p in self.state.patrons]
        size_desc = SIZE_DESCRIPTORS.get(getattr(self, "_tavern_size", "medium"), SIZE_DESCRIPTORS["medium"])
        prompt = f"""Generate {object_count} examinable objects for a medieval tavern.

Tavern layout: {tavern_template['layout']}
Atmosphere: {json.dumps(tavern_template.get('atmosphere', {}), indent=2)}
Patrons present (for context, do NOT generate objects about them): {patron_briefs}
The tavern feels {size_desc}.

Rules:
- Objects must feel natural to this specific tavern's atmosphere and layout — not generic
- Humans only — no magical or fantastical objects
- Real medieval tavern items: furniture, decorations, tools, food/drink related, personal effects left by patrons
- Each object should be visually interesting and worth examining
- Objects should be spread across the tavern — bar area, walls, tables, fireplace area, corners
- Brief descriptions should paint a quick picture in 5-10 words
- Detailed descriptions should reward curiosity with specific, sensory detail (2-3 sentences)
- Keywords should be words a player would naturally type to refer to each object
- Mark 1-2 items as pickable (small, portable items a patron might pocket — a loose coin, a forgotten knife, a trinket). Mark 1-2 different items as usable_in_place (stationary items the player can interact with — a fireplace, a dartboard, a noticeboard). Most items should be examine-only (both flags False). If usable_in_place is True, provide a use_text describing the interaction result."""

        extra_config = {
            "response_mime_type": "application/json",
            "response_json_schema": ExaminablesResponse.model_json_schema(),
        }
        response_text = safe_generate(self.model_name, prompt, extra_config=extra_config)
        result = ExaminablesResponse.model_validate_json(response_text)
        return [obj.model_dump() for obj in result.objects]

    def _generate_ambient_pool(self, tavern_template: dict) -> list[str]:
        """Generate a pool of ambient flavor text lines using Gemini structured output."""
        patron_briefs = [p.brief_description for p in self.state.patrons]
        size_desc = SIZE_DESCRIPTORS.get(getattr(self, "_tavern_size", "medium"), SIZE_DESCRIPTORS["medium"])
        prompt = f"""Generate 12 ambient flavor text lines for a medieval tavern.

Tavern: {self.state.tavern_name}
Layout: {tavern_template['layout']}
Atmosphere: {json.dumps(tavern_template.get('atmosphere', {}), indent=2)}
Patrons present (refer to them by appearance only, never by name): {patron_briefs}
The tavern feels {size_desc}.

Rules:
- Each line is ONE sentence, 10-20 words — a quick sensory impression
- Mix patron activity ("A man at the corner table mutters into his ale") and environmental detail ("The fire pops, sending sparks up the chimney")
- Match the tavern's mood — dark moods get darker observations, warm moods get cozier ones
- Never name patrons — refer only by appearance ("the broad-shouldered man", "a figure by the window")
- No dialogue — only observations of activity and environment
- Each line should stand alone — no continuations or sequences
- Write in third person present tense"""

        extra_config = {
            "response_mime_type": "application/json",
            "response_json_schema": AmbientPoolResponse.model_json_schema(),
        }
        response_text = safe_generate(self.model_name, prompt, extra_config=extra_config)
        result = AmbientPoolResponse.model_validate_json(response_text)
        return result.lines

    def _generate_shop_items(self, tavern_template: dict) -> list[dict]:
        """Generate size-appropriate unique shop trinkets for this tavern using Gemini structured output."""
        from game.config import get_size_ranges
        ranges = get_size_ranges(self.config, getattr(self, "_tavern_size", "medium"))
        shop_count = ranges["shop_count"]
        prompt = f"""Generate {shop_count} unique trinkets and gifts for sale at a medieval tavern.

Tavern: {self.state.tavern_name}
Atmosphere: {json.dumps(tavern_template.get('atmosphere', {}), indent=2)}
Layout: {tavern_template['layout']}

Rules:
- Each item is a trinket, curio, or small gift — NOT food or drink
- Items should feel unique to THIS specific tavern's character and location
- Mix useful-seeming items (dice, candle, flask) with sentimental ones (carved figure, dried flower, old coin)
- Prices between 5 and 20 gold — more interesting or rare items cost more
- Descriptions should be vivid and reward curiosity — the kind of thing you'd examine in a shop
- All items must be period-appropriate for 1350s England — no fantasy or anachronistic objects
- Names should be 2-4 words, evocative but clear
"""

        extra_config = {
            "response_mime_type": "application/json",
            "response_json_schema": ShopInventoryResponse.model_json_schema(),
        }
        response_text = safe_generate(self.model_name, prompt, extra_config=extra_config)
        result = ShopInventoryResponse.model_validate_json(response_text)
        return [{"name": item.name, "description": item.description, "price": item.price, "item_type": "trinket"} for item in result.items]
