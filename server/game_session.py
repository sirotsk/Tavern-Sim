"""Per-connection GameSession -- owns the full engine stack for one player.

Each WebSocket connection creates one GameSession. The session bridges the
synchronous CLI game engine (CommandParser, SessionSetup, NarratorAgent) into
async-compatible WebSocket output by:

1. Running blocking engine code in threads via asyncio.to_thread()
2. Collecting typed message dicts through an emit callback (instead of print)
3. Flushing collected messages to the WebSocket after each thread completes

Thread safety: CPython's GIL protects list.append, so _emit() is safe to call
from the game engine thread while the event loop waits on to_thread().
"""
import asyncio
import json
import logging
from pathlib import Path

from server import messages
from game.drunk_filter import get_tier, TIER_NAMES

logger = logging.getLogger(__name__)


def _build_drunk_meter(drunkenness: int) -> str:
    """Build an ASCII drunkenness meter string.

    Format: [###-------] TIER_NAME
    Uses 10 slots with a visual max of 40 (tier 4 cap).

    Args:
        drunkenness: Current drunkenness level (0+).

    Returns:
        Meter string like '[####------] Merry'.
    """
    clamped = min(drunkenness, 40)
    filled = min(10, round((clamped / 40) * 10))
    empty = 10 - filled
    tier = get_tier(drunkenness)
    tier_name = TIER_NAMES[tier].upper()
    return f"[{'#' * filled}{'-' * empty}] {tier_name}"


class GameSession:
    """Per-connection game session owning GameState, CommandParser, and AgentManager.

    Lifecycle:
        1. __init__() -- lightweight, no engine imports
        2. start(player_name) -- runs full session setup in a thread
        3. handle_command(text) -- processes one player command in a thread
        4. get_opening_sections() -- returns narrator opening as list of strings
        5. build_status_msg() -- builds a status dict for the side panel
    """

    def __init__(self, session_id: str, websocket):
        """Initialize a game session for one WebSocket connection.

        Args:
            session_id: Client-generated UUID for this connection.
            websocket: The FastAPI WebSocket object for sending messages.
        """
        self.session_id = session_id
        self.websocket = websocket
        self.state = None
        self.parser = None
        self._narrator = None
        self._tavern_data = None
        self._barkeep_data = None
        self._pending_messages: list[dict] = []

    def _emit(self, msg: dict) -> None:
        """Collect a message dict for later flushing to the WebSocket.

        This is the callback injected into CommandParser. It runs in the game
        engine thread -- CPython GIL protects list.append so no lock is needed.

        Args:
            msg: A typed message dict with at least a 'type' field.
        """
        self._pending_messages.append(msg)

    async def flush_messages(self) -> None:
        """Send all pending messages to the WebSocket and clear the buffer."""
        for msg in self._pending_messages:
            await self.websocket.send_json(msg)
        self._pending_messages.clear()

    async def start(self, player_name: str) -> None:
        """Create the full engine stack in a background thread.

        Loads .env for API key, runs SessionSetup, creates all agents and
        the CommandParser. After the thread returns, flushes any progress
        messages that were collected during setup.

        Args:
            player_name: The player's chosen name.
        """
        await asyncio.to_thread(self._run_setup, player_name)
        await self.flush_messages()

    def _run_setup(self, player_name: str) -> None:
        """Blocking setup -- runs in a thread via asyncio.to_thread().

        Mirrors main.py lines 52-131 but uses emit callback instead of print.
        """
        # Ensure .env is loaded (no interactive prompt -- server mode)
        from dotenv import load_dotenv
        load_dotenv()

        # Import game modules (deferred to avoid circular imports at module level)
        import random
        from agents.base_agent import client
        from game.config import load_config, get_economy_config
        from game.state import GameState
        from game.session_setup import SessionSetup
        from game.action_log import ActionLog
        from agents.narrator_agent import NarratorAgent
        from agents.agent_manager import AgentManager

        # Load config
        config = load_config()
        model_name = config["model"]["name"]

        # Initialize game state
        self.state = GameState(player_name=player_name)

        # Run session setup with progress callback
        setup = SessionSetup(
            client, config, self.state,
            model_name=model_name,
            progress_callback=self._progress_callback,
        )
        setup.run()

        # Draw starting gold from economy config
        econ = get_economy_config(config)
        self.state.gold = random.randint(econ["starting_gold_min"], econ["starting_gold_max"])

        # Load tavern and barkeep data
        tavern_json_path = Path("agent_profiles/tavern.json")
        self._tavern_data = json.loads(tavern_json_path.read_text(encoding="utf-8"))

        barkeep_path = Path("agent_profiles/barkeep.json")
        self._barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))

        # Initialize NarratorAgent
        self._narrator = NarratorAgent(self._tavern_data, model_name)

        # Initialize ActionLog
        self._action_log = ActionLog()

        # Load patron profiles for AgentManager
        patron_profiles = {}
        for patron_record in self.state.patrons:
            profile_path = Path(patron_record.profile_path)
            if profile_path.exists():
                patron_profiles[patron_record.profile_path] = json.loads(
                    profile_path.read_text(encoding="utf-8")
                )

        # Inject patron_briefs into tavern_data for cross-patron awareness
        self._tavern_data["patron_briefs"] = [
            p.brief_description for p in self.state.patrons
        ]

        # Initialize AgentManager
        agent_manager = AgentManager(
            tavern_data=self._tavern_data,
            patron_profiles=patron_profiles,
            barkeep_profile=self._barkeep_data,
            player_name=self.state.player_name,
            model_name=model_name,
        )

        # Create CommandParser with emit callback
        from game.command_parser import CommandParser
        self.parser = CommandParser(
            self.state, self._narrator, self._action_log, config,
            agent_manager=agent_manager, emit=self._emit,
        )

    async def load(self, save_data: dict) -> None:
        """Reconstruct the engine stack from a save file. No Gemini calls -- near-instant.

        Args:
            save_data: The parsed save dict from load_game().
        """
        await asyncio.to_thread(self._run_load, save_data)
        await self.flush_messages()

    def _run_load(self, save_data: dict) -> None:
        """Blocking load -- runs in a thread via asyncio.to_thread().

        Reconstructs GameState, AgentManager, and CommandParser from save data
        without calling SessionSetup (no Gemini calls -- near-instant).

        Args:
            save_data: The parsed save dict from load_game().
        """
        from dotenv import load_dotenv
        load_dotenv()

        from agents.base_agent import client, SAFETY_CONFIG
        from game.config import load_config
        from game.state import GameState, PatronRecord, InventoryItem
        from game.action_log import ActionLog
        from agents.narrator_agent import NarratorAgent
        from agents.agent_manager import AgentManager
        from google.genai import types

        config = load_config()
        model_name = config["model"]["name"]

        # Reconstruct GameState from save data
        self.state = GameState(
            player_name=save_data.get("player_name", "Stranger"),
            drunkenness=save_data.get("drunkenness", 0),
            tavern_name=save_data.get("tavern_name", ""),
            barkeep_name=save_data.get("barkeep_name", ""),
            barkeep_talked_to=save_data.get("barkeep_talked_to", False),
            session_active=True,
            look_count=save_data.get("look_count", 0),
            command_count=save_data.get("command_count", 0),
            tab_count=save_data.get("tab_count", 0),
            order_history=save_data.get("order_history", []),
            gold=save_data.get("gold", 0),
            # Reset session-only flavor fields
            active_patron=None,
            passed_out=False,
            examined_targets={},
            last_look_order={},
            last_ambient_at=0,
        )

        # Reconstruct inventory from save data
        for inv_dict in save_data.get("inventory", []):
            self.state.inventory.append(InventoryItem(
                name=inv_dict.get("name", "Unknown"),
                description=inv_dict.get("description", ""),
                item_type=inv_dict.get("item_type", "trinket"),
                reusable=inv_dict.get("reusable", True),
                source=inv_dict.get("source", "shop"),
            ))
        self.state.shop_items = save_data.get("shop_items", [])
        self.state.game_session = save_data.get("game_session", None)
        self.state.picked_up_items = save_data.get("picked_up_items", [])

        # Reconstruct PatronRecord objects from saved patron list
        for patron_dict in save_data.get("patrons", []):
            record = PatronRecord(
                profile_path=patron_dict.get("profile_path", ""),
                description=patron_dict.get("description", ""),
                brief_description=patron_dict.get("brief_description", ""),
                name=patron_dict.get("name"),
                talked_to=patron_dict.get("talked_to", False),
                keywords=patron_dict.get("keywords", []),
                name_shared=patron_dict.get("name_shared", False),
                exchange_count=patron_dict.get("exchange_count", 0),
                gold=patron_dict.get("gold", 0),
                archetype_id=patron_dict.get("archetype_id", ""),
                gender=patron_dict.get("gender", ""),
            )
            self.state.patrons.append(record)

        # Load tavern.json for examinables, ambient_pool, and shop awareness
        tavern_json_path = Path("agent_profiles/tavern.json")
        if tavern_json_path.exists():
            self._tavern_data = json.loads(tavern_json_path.read_text(encoding="utf-8"))
            self.state.examinables = self._tavern_data.get("examinables", [])
            # Filter out items the player already picked up
            if self.state.picked_up_items:
                self.state.examinables = [
                    e for e in self.state.examinables
                    if e.get("name") not in self.state.picked_up_items
                ]
            self.state.ambient_pool = list(self._tavern_data.get("ambient_pool", []))
        else:
            # Edge case: agent_profiles/ was wiped -- fall back gracefully
            logger.warning("agent_profiles/tavern.json not found -- examinables and ambient_pool will be empty")
            self._tavern_data = {}
            self.state.examinables = []
            self.state.ambient_pool = []

        # Ensure barkeep has shop awareness -- sync shop_items (restored from save) into tavern_data
        if self.state.shop_items:
            self._tavern_data["shop_items"] = self.state.shop_items

        # Load barkeep profile
        barkeep_path = Path("agent_profiles/barkeep.json")
        self._barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))

        # Initialize NarratorAgent and ActionLog
        self._narrator = NarratorAgent(self._tavern_data, model_name)
        self._action_log = ActionLog()

        # Load patron profiles for AgentManager
        patron_profiles = {}
        for patron_record in self.state.patrons:
            profile_path = Path(patron_record.profile_path)
            if profile_path.exists():
                patron_profiles[patron_record.profile_path] = json.loads(
                    profile_path.read_text(encoding="utf-8")
                )

        # Inject patron_briefs into tavern_data for cross-patron awareness
        self._tavern_data["patron_briefs"] = [p.brief_description for p in self.state.patrons]

        # Create AgentManager with loaded profiles
        agent_manager = AgentManager(
            tavern_data=self._tavern_data,
            patron_profiles=patron_profiles,
            barkeep_profile=self._barkeep_data,
            player_name=self.state.player_name,
            model_name=model_name,
        )

        # Restore patron chat histories
        patron_save_data_map = {
            p.get("profile_path", ""): p
            for p in save_data.get("patrons", [])
        }
        for patron_record in self.state.patrons:
            patron_save_data = patron_save_data_map.get(patron_record.profile_path, {})
            saved_history = patron_save_data.get("chat_history", [])
            if patron_record.talked_to and saved_history:
                agent = agent_manager.get_or_create_patron(patron_record.profile_path)
                system_prompt = agent._chat._config.system_instruction
                agent._chat = client.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        safety_settings=SAFETY_CONFIG.safety_settings,
                    ),
                    history=saved_history,
                )

        # Restore barkeep chat history
        barkeep_history = save_data.get("barkeep_chat_history", [])
        if barkeep_history:
            barkeep = agent_manager.get_or_create_barkeep()
            system_prompt = barkeep._chat._config.system_instruction
            barkeep._chat = client.chats.create(
                model=model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    safety_settings=SAFETY_CONFIG.safety_settings,
                ),
                history=barkeep_history,
            )

        # Create CommandParser with emit callback
        from game.command_parser import CommandParser
        self.parser = CommandParser(
            self.state, self._narrator, self._action_log, config,
            agent_manager=agent_manager, emit=self._emit,
        )

    def _progress_callback(self, step: str, percent: int) -> None:
        """Collect a loading progress message during session setup.

        Called from the setup thread -- collected via _emit pattern.

        Args:
            step: Human-readable progress step description.
            percent: Progress percentage (0-100).
        """
        self._pending_messages.append({
            "type": messages.LOADING_PROGRESS,
            "step": step,
            "percent": percent,
        })

    async def handle_command(self, text: str) -> None:
        """Process one player command in a background thread, then flush messages.

        Args:
            text: The raw command text from the player.
        """
        await asyncio.to_thread(self.parser.parse, text)
        await self.flush_messages()

    def get_opening_sections(self) -> list[str]:
        """Return the opening narration as a list of section strings.

        Unlike NarratorAgent.stream_opening(), this does NOT print anything.
        Returns 3 sections: [tavern_description, patron_descriptions, invitation].

        Returns:
            List of 3 strings, one per narrative section.
        """
        patron_briefs = [p.brief_description for p in self.state.patrons]
        barkeep_brief = self._barkeep_data.get("appearance", {}).get(
            "brief", "The barkeep"
        )
        return self._narrator.get_opening_sections(patron_briefs, barkeep_brief)

    def _resolve_portrait_path(self) -> str | None:
        """Resolve the portrait image path for the currently active conversation.

        Returns:
            URL path to the portrait PNG, or None if no conversation is active
            or portrait data is missing.
        """
        if not self.state.active_patron:
            return None
        # Check if talking to barkeep
        if self.state.active_patron == self.state.barkeep_name:
            barkeep_archetype_id = self._barkeep_data.get("archetype_id", "") if self._barkeep_data else ""
            gender = self._barkeep_data.get("identity", {}).get("gender", "male") if self._barkeep_data else "male"
            gender = gender.lower().strip()
            if gender not in ("male", "female"):
                gender = "male"
            return f"/static/portraits/barkeeps/{barkeep_archetype_id}_{gender}.png"
        # Find patron by name
        for patron in self.state.patrons:
            if patron.name == self.state.active_patron:
                if patron.archetype_id and patron.gender:
                    return f"/static/portraits/patrons/{patron.archetype_id}_{patron.gender}.png"
                return None
        return None

    def build_status_msg(self) -> dict:
        """Build a status message dict from the current game state.

        Used by ws_handler to send status updates to the client after
        every command, so the side panel stays in sync.

        Returns:
            A dict with type=STATUS and all status fields.
        """
        return {
            "type": messages.STATUS,
            "player_name": self.state.player_name,
            "drunkenness": self.state.drunkenness,
            "tier": get_tier(self.state.drunkenness),
            "drunk_meter": _build_drunk_meter(self.state.drunkenness),
            "money": self.state.gold,
            "inventory": [i.name for i in self.state.inventory],
            "interactions": sum(p.exchange_count for p in self.state.patrons),
            "active_patron": self.state.active_patron,
            "tavern_name": self.state.tavern_name,
            "portrait_path": self._resolve_portrait_path(),
            "tavern_image_path": self._tavern_data.get("tavern_image_path") if self._tavern_data else None,
            "template_id": self._tavern_data.get("template", {}).get("id", "") if self._tavern_data else "",
        }


def build_load_recap(save_data: dict) -> str:
    """Build a brief recap summary from save data. No Gemini call -- pure Python.

    Called by ws_handler after a successful load to show the player a quick
    summary of where they left off.

    Args:
        save_data: The parsed save dict from load_game().

    Returns:
        A multiline string summarizing the saved game state.
    """
    tavern = save_data.get("tavern_name", "the tavern")
    drunk = save_data.get("drunkenness", 0)
    patrons_known = [
        p["name"] for p in save_data.get("patrons", [])
        if p.get("talked_to") and p.get("name")
    ]
    barkeep = save_data.get("barkeep_name", "")

    lines = [f"Returning to {tavern}..."]
    if barkeep and save_data.get("barkeep_talked_to"):
        lines.append(f"You remember the barkeep -- {barkeep}.")
    if patrons_known:
        names_str = ", ".join(patrons_known)
        lines.append(f"Familiar faces: {names_str}.")
    if drunk > 0:
        lines.append("Your head is still swimming a little.")
    return "\n".join(lines)
