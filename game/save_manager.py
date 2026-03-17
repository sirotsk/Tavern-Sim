"""
Save/load manager for game state persistence.

Implements PERS-01 (save game state to file) and PERS-04 (schema versioning).

Design decisions:
- Single save slot: saves/savegame.json
- Atomic write via temp file + os.replace() -- safe against power loss/crashes
- Schema versioning: any schema_version mismatch silently returns None (new game)
- Chat history truncated to last HISTORY_TURNS_LIMIT turns per patron/barkeep
- Fields NOT saved: examinables, ambient_pool, last_look_order, examined_targets,
  passed_out, active_patron, last_ambient_at -- all regenerated or reset on load
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from game.state import GameState, InventoryItem

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 4
SAVE_PATH = Path("saves/savegame.json")

# Each "turn" is one user message + one model response = 2 Content entries
HISTORY_TURNS_LIMIT = 10
_HISTORY_ENTRIES_LIMIT = HISTORY_TURNS_LIMIT * 2


def save_game(state: GameState, agent_manager) -> None:
    """Serialize full game state to JSON and write atomically.

    Args:
        state: Current GameState to persist.
        agent_manager: AgentManager instance holding active chat sessions.
    """
    # Serialize patrons, including chat history for those that have been talked to
    patrons_data = []
    for patron in state.patrons:
        patron_dict = {
            "profile_path": patron.profile_path,
            "description": patron.description,
            "brief_description": patron.brief_description,
            "name": patron.name,
            "talked_to": patron.talked_to,
            "keywords": patron.keywords,
            "name_shared": patron.name_shared,
            "exchange_count": patron.exchange_count,
            "gold": patron.gold,
            "archetype_id": patron.archetype_id,
            "gender": patron.gender,
            "chat_history": [],
        }

        # Only serialize chat history for patrons that have been talked to
        # and whose agent exists in the manager
        if patron.talked_to and agent_manager.has_patron(patron.profile_path):
            agent = agent_manager.get_or_create_patron(patron.profile_path)
            history = _serialize_chat_history(agent._chat)
            patron_dict["chat_history"] = history

        patrons_data.append(patron_dict)

    # Serialize barkeep chat history if it exists
    barkeep_chat_history = []
    if agent_manager.has_barkeep():
        barkeep_agent = agent_manager.get_or_create_barkeep()
        barkeep_chat_history = _serialize_chat_history(barkeep_agent._chat)

    data = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "player_name": state.player_name,
        "drunkenness": state.drunkenness,
        "tavern_name": state.tavern_name,
        "barkeep_name": state.barkeep_name,
        "barkeep_talked_to": state.barkeep_talked_to,
        "session_active": state.session_active,
        "look_count": state.look_count,
        "command_count": state.command_count,
        "tab_count": state.tab_count,
        "order_history": state.order_history,
        "gold": state.gold,
        "inventory": [
            {"name": i.name, "description": i.description,
             "item_type": i.item_type, "reusable": i.reusable, "source": i.source}
            for i in state.inventory
        ],
        "shop_items": state.shop_items,
        "game_session": state.game_session,
        "picked_up_items": state.picked_up_items,
        "patrons": patrons_data,
        "barkeep_chat_history": barkeep_chat_history,
    }

    _write_atomic(data, SAVE_PATH)
    logger.info("Game saved to %s", SAVE_PATH)


def _serialize_chat_history(chat) -> list:
    """Serialize a Gemini chat history to a JSON-safe list.

    Uses get_history(curated=True) to get valid turns only, then truncates
    to HISTORY_ENTRIES_LIMIT entries (last HISTORY_TURNS_LIMIT turns).

    Args:
        chat: A google-genai Chat object with a get_history() method.

    Returns:
        List of JSON-safe dicts representing Content objects.
    """
    try:
        history = chat.get_history(curated=True)
        # Truncate to last N entries (keep the most recent turns)
        if len(history) > _HISTORY_ENTRIES_LIMIT:
            history = history[-_HISTORY_ENTRIES_LIMIT:]
        # model_dump with mode='json' is CRITICAL -- without it, enums serialize as
        # Python objects (not JSON-safe strings). exclude_none keeps output clean.
        return [content.model_dump(mode='json', exclude_none=True) for content in history]
    except Exception as exc:
        logger.warning("Failed to serialize chat history: %s", exc)
        return []


def load_game(save_path: Path = SAVE_PATH) -> Optional[dict]:
    """Load and validate a save file.

    Returns None (silently) if:
    - The file does not exist
    - JSON decode fails (corrupted file)
    - schema_version field is missing or does not match SCHEMA_VERSION
    - Any other exception

    Per user decision: all failures silently fall back to New Game.
    Version mismatches are logged as warnings for debugging.

    Args:
        save_path: Path to the save file. Defaults to SAVE_PATH.

    Returns:
        The parsed save data dict, or None if load failed.
    """
    if not save_path.exists():
        return None

    try:
        text = save_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Save file at %s is corrupted (JSON decode error): %s", save_path, exc)
        return None
    except Exception as exc:
        logger.warning("Failed to read save file at %s: %s", save_path, exc)
        return None

    # Validate schema version
    schema_version = data.get("schema_version")
    if schema_version is None:
        logger.warning("Save file at %s has no schema_version field -- ignoring", save_path)
        return None
    if schema_version != SCHEMA_VERSION:
        logger.warning(
            "Save file schema_version %s does not match expected %s -- ignoring",
            schema_version,
            SCHEMA_VERSION,
        )
        return None

    return data


def has_save(save_path: Path = SAVE_PATH) -> bool:
    """Return True if a valid save file exists.

    Delegates to load_game() -- if load_game() returns a dict, the save is valid.

    Args:
        save_path: Path to check. Defaults to SAVE_PATH.

    Returns:
        True if a valid save exists, False otherwise.
    """
    return load_game(save_path) is not None


def delete_save(save_path: Path = SAVE_PATH) -> None:
    """Delete the save file if it exists.

    Used when NEW_GAME overwrites an existing save. Safe to call even if no
    save file exists.

    Args:
        save_path: Path to delete. Defaults to SAVE_PATH.
    """
    save_path.unlink(missing_ok=True)
    logger.info("Save file deleted: %s", save_path)


def _write_atomic(data: dict, path: Path) -> None:
    """Write JSON atomically using a temp file + os.replace().

    Guarantees that the destination file is either fully written or unchanged --
    a crash mid-write leaves the temp file, not a half-written save file.

    Temp file is created in the same directory as the destination to ensure
    both are on the same filesystem (required for atomic os.replace()).

    Args:
        data: The dict to serialize as JSON.
        path: The destination path to write to.
    """
    # Ensure the saves/ directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd = None
    tmp_path = None
    try:
        # Create temp file in same directory as destination (same filesystem required)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=".savegame_tmp_",
            suffix=".json",
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            tmp_fd = None  # fdopen takes ownership -- don't double-close
            json.dump(data, f, indent=2, ensure_ascii=False)
        # Atomic rename -- on POSIX this is guaranteed atomic; on Windows it
        # replaces atomically on NTFS (os.replace is available on both platforms)
        os.replace(tmp_path, path)
        tmp_path = None  # Rename succeeded -- don't try to unlink
    except Exception:
        # Clean up the orphaned temp file, then re-raise to caller
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
