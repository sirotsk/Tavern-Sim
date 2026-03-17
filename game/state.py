"""Session state — single source of truth for all mutable game data."""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class InventoryItem:
    """A single item in the player's inventory."""
    name: str                          # Display name, e.g. "Silver ring"
    description: str                   # Shown on 'examine inv [item]'
    item_type: str = "trinket"         # "trinket" | "food" | "drink"
    reusable: bool = True              # False = consumed on first use
    source: str = "shop"               # "shop" | "patron_gift" | "found"


@dataclass
class PatronRecord:
    """Minimal record of a patron in the current session."""
    profile_path: str          # Path to agent_profiles/patron_XXX.json
    description: str           # Full appearance description (2-3 sentences)
    brief_description: str = ""  # Short narrator label, e.g. "A broad-shouldered man with gnarled hands"
    name: Optional[str] = None  # Revealed only when player talks to them
    talked_to: bool = False     # True after player initiates conversation
    keywords: list = field(default_factory=list)  # For examine matching
    name_shared: bool = False   # True once the player tells this patron their name
    exchange_count: int = 0     # Number of conversation turns with this patron
    gold: int = 0               # Patron's gold balance (used for wagering in bar games)
    archetype_id: str = ""      # e.g. "soldier", "bard" -- from archetype template
    gender: str = ""            # "male" or "female" -- assigned by Gemini


@dataclass
class GameState:
    """Single source of truth for all mutable session state."""
    player_name: str = ""
    drunkenness: int = 0                        # STAT-01: 0–30+ scale
    active_patron: Optional[str] = None         # STAT-02: name of patron being talked to
    tavern_name: str = ""
    patrons: List[PatronRecord] = field(default_factory=list)
    barkeep_name: str = ""
    session_active: bool = False
    look_count: int = 0                                  # Escalating look annoyance
    examined_targets: dict = field(default_factory=dict)  # target_key -> examine count
    last_look_order: dict = field(default_factory=dict)   # {"people": [...], "objects": [...]}
    examinables: list = field(default_factory=list)       # From tavern.json examinable objects
    ambient_pool: list = field(default_factory=list)      # Pre-seeded ambient lines
    command_count: int = 0                                # Total commands issued (for ambient spacing)
    last_ambient_at: int = 0                              # Command index of last ambient trigger
    order_history: list = field(default_factory=list)     # List of {item_name, drunkenness_modifier} dicts
    tab_count: int = 0                                    # Total items ordered this session
    barkeep_talked_to: bool = False                       # True once player initiates barkeep conversation
    passed_out: bool = False                              # True when player has drunk themselves unconscious
    gold: int = 0
    inventory: list = field(default_factory=list)    # list[InventoryItem]
    shop_items: list = field(default_factory=list)   # list[dict] -- tavern shop catalogue
    game_session: Optional[dict] = None              # Active bar game state (None when idle)
    picked_up_items: list = field(default_factory=list)  # Names of items picked up from examinables
