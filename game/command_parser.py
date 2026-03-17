"""
Command parser — dispatches player commands to handlers.

Phase 2 commands: look, examine, status, help, quit
Phase 3 commands: talk, order, end conversation, menu

Command aliases: l=look, x=examine, ?=help, q=quit, t=talk, m=menu
Parser is case-insensitive. Uses split(maxsplit=1) to preserve multi-word examine targets.

Conversation mode: when state.active_patron is set, most commands are intercepted
and routed to the patron agent. Meta commands (status, help, quit) pass through normally.
"""
import json
import random
import re
import sys
from pathlib import Path

from agents.narrator_agent import NarratorAgent
from game.action_log import ActionLog
from game.state import GameState, PatronRecord, InventoryItem
from game.config import get_ambient_chance
from game.drunk_filter import get_tier, garble, TIER_NAMES, SPEECH_LABELS
from server import messages as msg_types


# --- Three-Stage Examine Target Resolution ---

def _keyword_score(target: str, keywords: list[str], brief: str) -> int:
    """Count how many words in target appear in keywords or brief description."""
    target_words = set(target.lower().split())
    keyword_set = set(k.lower() for k in keywords)
    brief_words = set(brief.lower().split())
    return len(target_words & (keyword_set | brief_words))


def _resolve_by_number(target_str: str, last_look_order: dict) -> dict | None:
    """Resolve a numbered reference from the last look output.

    Supports: "1", "2", "people 1", "object 2", "objects 1", "person 2"
    Plain numbers default to People section first (players more likely to examine people).
    """
    tokens = target_str.strip().lower().split()

    section = None
    number_str = None

    if len(tokens) == 1 and tokens[0].isdigit():
        # Plain number — default to people, fall back to objects
        number_str = tokens[0]
    elif len(tokens) == 2:
        prefix = tokens[0]
        if tokens[1].isdigit():
            number_str = tokens[1]
            if prefix in ("people", "person", "p"):
                section = "people"
            elif prefix in ("object", "objects", "thing", "things", "o"):
                section = "objects"

    if number_str is None:
        return None

    idx = int(number_str) - 1  # Convert to 0-based

    if section == "people":
        people = last_look_order.get("people", [])
        if 0 <= idx < len(people):
            return people[idx]
    elif section == "objects":
        objects = last_look_order.get("objects", [])
        if 0 <= idx < len(objects):
            return objects[idx]
    else:
        # Plain number — try people first, then objects
        people = last_look_order.get("people", [])
        if 0 <= idx < len(people):
            return people[idx]
        objects = last_look_order.get("objects", [])
        if 0 <= idx < len(objects):
            return objects[idx]

    return None


def resolve_examine_target(
    target_str: str,
    state: GameState,
) -> dict | None:
    """Resolve an examine target string to a matched entity.

    Returns:
        dict with keys:
          - type: "patron" | "object" | "ambiguous" | "barkeep"
          - data: PatronRecord, examinable dict, or list of candidates
        None if no match found.

    Priority:
    1. Exact patron name match (known names only)
    2. Barkeep name match
    3. Keyword overlap scoring against all examinables and patrons
    4. Numbered reference from last look output
    """
    target_lower = target_str.strip().lower()

    if not target_lower:
        return None

    # Stage 1: Exact name match (known patron names only)
    for patron in state.patrons:
        if patron.talked_to and patron.name and patron.name.lower() == target_lower:
            return {"type": "patron", "data": patron}

    # Check barkeep by name
    if state.barkeep_name and state.barkeep_name.lower() == target_lower:
        # Load barkeep profile for examination
        barkeep_path = Path("agent_profiles/barkeep.json")
        if barkeep_path.exists():
            barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))
            return {"type": "barkeep", "data": barkeep_data}

    # Also check "barkeep" / "bartender" / "barman" keywords
    if target_lower in ("barkeep", "bartender", "barman", "barkeeper", "innkeeper"):
        barkeep_path = Path("agent_profiles/barkeep.json")
        if barkeep_path.exists():
            barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))
            return {"type": "barkeep", "data": barkeep_data}

    # Stage 2: Keyword overlap scoring
    best_score = 0
    best_match = None
    candidates = []

    # Score against examinable objects
    for obj in state.examinables:
        score = _keyword_score(target_lower, obj.get("keywords", []), obj.get("brief", ""))
        if score > 0:
            match = {"type": "object", "data": obj}
            if score > best_score:
                best_score = score
                best_match = match
                candidates = [match]
            elif score == best_score:
                candidates.append(match)

    # Score against patrons
    for patron in state.patrons:
        score = _keyword_score(target_lower, patron.keywords, patron.brief_description)
        if score > 0:
            match = {"type": "patron", "data": patron}
            if score > best_score:
                best_score = score
                best_match = match
                candidates = [match]
            elif score == best_score:
                candidates.append(match)

    if len(candidates) == 1 and best_score > 0:
        return candidates[0]
    if len(candidates) > 1:
        return {"type": "ambiguous", "data": candidates}

    # Stage 3: Numbered reference from last look
    numbered_result = _resolve_by_number(target_str, state.last_look_order)
    if numbered_result is not None:
        return numbered_result

    return None


# --- Look List Assembly ---

def _build_look_list(state: GameState) -> tuple[str, dict]:
    """Build the numbered examinable list for look output.

    Returns:
        tuple of (formatted string, look_order dict for state)
        look_order: {"people": [match_dicts...], "objects": [match_dicts...]}
    """
    lines = []
    look_order = {"people": [], "objects": []}

    # People section: barkeep + patrons
    lines.append("\nPeople:")
    people_num = 1

    # Barkeep first — show name after learning it, note they're behind the bar
    barkeep_path = Path("agent_profiles/barkeep.json")
    if barkeep_path.exists():
        barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))
        if state.barkeep_talked_to and state.barkeep_name:
            barkeep_label = f"{state.barkeep_name}, behind the bar"
        else:
            barkeep_brief = barkeep_data.get("appearance", {}).get("brief", "The barkeep")
            barkeep_label = f"{barkeep_brief}, behind the bar"
        lines.append(f"  {people_num}. {barkeep_label}")
        look_order["people"].append({"type": "barkeep", "data": barkeep_data})
        people_num += 1

    # Patrons
    for patron in state.patrons:
        if patron.talked_to and patron.name:
            label = patron.name
        else:
            label = patron.brief_description or patron.description
        lines.append(f"  {people_num}. {label}")
        look_order["people"].append({"type": "patron", "data": patron})
        people_num += 1

    # Objects section
    if state.examinables:
        lines.append("\nAround the room:")
        for i, obj in enumerate(state.examinables, 1):
            lines.append(f"  {i}. {obj.get('brief', obj.get('name', 'Something'))}")
            look_order["objects"].append({"type": "object", "data": obj})

    return "\n".join(lines), look_order


# --- CommandParser ---

class CommandParser:
    """Dispatches player commands to handlers. Case-insensitive with aliases."""

    ALIASES = {
        "l": "look",
        "x": "examine",
        "?": "help",
        "q": "quit",
        "t": "talk",
        "m": "menu",
        "s": "shop",
        "b": "buy",
    }

    # Barkeep keyword aliases for talk target resolution
    BARKEEP_KEYWORDS = frozenset({"barkeep", "bartender", "barman", "barkeeper", "innkeeper"})

    # Keywords that suggest the player is trying to order something during barkeep conversation
    ORDER_INTENT_KEYWORDS = frozenset({
        "i'll have", "ill have", "i will have",
        "give me", "get me", "bring me", "pour me",
        "i'd like", "id like", "i would like",
        "can i get", "can i have",
        "one more", "another",
        "a round of", "a glass of", "a mug of", "a pint of", "a bowl of", "a plate of",
    })

    def __init__(
        self,
        state: GameState,
        narrator: NarratorAgent,
        action_log: ActionLog,
        config: dict,
        agent_manager=None,
        emit=None,
    ):
        self._state = state
        self._narrator = narrator
        self._action_log = action_log
        self._config = config
        self._ambient_chance = get_ambient_chance(config)
        self._agent_manager = agent_manager
        self._model_name = config.get("model", {}).get("name", "gemini-2.5-flash")
        self._emit = emit
        self._handlers = {
            "look": self._handle_look,
            "examine": self._handle_examine,
            "status": self._handle_status,
            "help": self._handle_help,
            "quit": self._handle_quit,
            "talk": self._handle_talk,
            "order": self._handle_order,
            "end": self._handle_end_conversation,
            "menu": self._handle_menu,
            "save": self._handle_save,
            "shop": self._handle_shop,
            "buy": self._handle_buy,
            "use": self._handle_use,
            "give": self._handle_give,
            "take": self._handle_take,
            "challenge": self._handle_challenge,
        }

    def _output(self, msg_dict: dict) -> None:
        """Send a typed message dict through the emit callback or print to stdout.

        When emit callback is set (web mode), appends the message dict to the
        pending messages buffer. When no callback (CLI mode), prints to stdout
        with appropriate formatting for backward compatibility.

        Args:
            msg_dict: A dict with at least 'type' and usually 'text' fields.
        """
        if self._emit:
            self._emit(msg_dict)
            return
        # CLI fallback -- preserve original print() behavior
        msg_type = msg_dict.get("type", "")
        text = msg_dict.get("text", "")
        speaker = msg_dict.get("speaker")
        if msg_type == msg_types.GAME_OVER:
            print(f"\n{text}\n")
        elif msg_type == msg_types.PLAYER_ECHO:
            pass  # CLI already shows input via input() prompt; don't double-echo
        elif speaker:
            print(f"\n{speaker}: {text}\n")
        elif text:
            print(f"\n{text}\n")

    def parse(self, raw: str) -> None:
        """Parse and dispatch a player command."""
        tokens = raw.strip().split(maxsplit=1)
        if not tokens:
            return

        verb = tokens[0].lower()

        # Detect slash prefix — indicates explicit command intent
        has_prefix = verb.startswith("/")
        if has_prefix:
            verb = verb[1:]  # Strip the leading slash

        verb = self.ALIASES.get(verb, verb)
        arg = tokens[1] if len(tokens) > 1 else ""

        # Normalize multi-word commands
        if verb == "talk" and arg.lower().startswith("to "):
            arg = arg[3:].strip()
        elif verb == "end" and arg.lower().startswith("conversation"):
            arg = ""

        self._state.command_count += 1
        self._output({"type": msg_types.PLAYER_ECHO, "text": raw.strip()})

        # --- CONVERSATION MODE INTERCEPT ---
        if self._state.active_patron:
            # Meta commands pass through normally
            if verb in ("status", "help", "quit"):
                handler = self._handlers.get(verb)
                if handler:
                    handler(arg)
                return

            # talk to different patron — switch (or re-talk same)
            if verb == "talk" and arg:
                self._handle_talk(arg)
                return

            # end conversation
            if verb == "end":
                self._handle_end_conversation(arg)
                return

            # order works mid-conversation
            if verb == "order":
                self._handle_order(arg, in_conversation=True)
                return

            # menu works mid-conversation
            if verb == "menu":
                self._handle_menu(arg)
                return

            # give works mid-conversation
            if verb == "give":
                self._handle_give(arg)
                return

            # shop, buy, use work mid-conversation
            if verb == "shop":
                self._handle_shop(arg)
                return
            if verb == "buy":
                self._handle_buy(arg)
                return
            if verb == "use":
                self._handle_use(arg)
                return
            if verb == "take":
                self._handle_take(arg)
                return

            if verb == "challenge":
                self._handle_challenge(arg)
                return

            # If a game session is active, route input to game handler instead of conversation
            if self._state.game_session is not None:
                self._handle_game_input(raw)
                return

            # Slash-prefixed input is ALWAYS a command attempt — even in conversation
            if has_prefix:
                # Try to execute as a command; if not recognized, tell the player
                handler = self._handlers.get(verb)
                if handler:
                    handler(arg)
                else:
                    self._output({"type": msg_types.SYSTEM, "text": f"Unknown command: /{verb}. Type /help to see available commands."})
            elif verb in ("look", "examine") and not has_prefix:
                # Unprefixed game command words get patron reaction
                self._handle_mid_conversation_command(raw)
            else:
                # Unprefixed free-form text — send to patron as conversation
                self._handle_conversation_input(raw)
            return

        # --- NORMAL MODE ---
        handler = self._handlers.get(verb)
        if handler:
            handler(arg)
        else:
            self._handle_unknown(raw)

        # Ambient text trigger (only after look and examine — not help/status/quit/invalid)
        if verb in ("look", "examine"):
            self._maybe_trigger_ambient()

    def _handle_look(self, arg: str) -> None:
        """Handle 'look' command — narrator prose + numbered examinable list."""
        self._state.look_count += 1

        # Get narrator prose
        history = self._action_log.get_recent(10)
        prose = self._narrator.look(
            self._state.look_count,
            history,
            self._state.examined_targets,
        )

        # Build examinable list
        list_text, look_order = _build_look_list(self._state)
        self._state.last_look_order = look_order

        # Display
        self._output({"type": msg_types.NARRATION, "text": prose})
        self._output({"type": msg_types.SYSTEM, "text": list_text})

        # Log
        self._action_log.append("look", "", prose)

    def _handle_examine(self, arg: str) -> None:
        """Handle 'examine [target]' command — three-stage matching + narrator description."""
        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Examine what? Type 'examine' followed by what you want to look at."})
            return

        # Special case: examine inv [item name]
        if arg.lower().startswith("inv ") or arg.lower() == "inv":
            inv_arg = arg[4:].strip() if len(arg) > 4 else ""
            if not inv_arg:
                if not self._state.inventory:
                    self._output({"type": msg_types.SYSTEM, "text": "Your inventory is empty."})
                else:
                    names = [i.name for i in self._state.inventory]
                    self._output({"type": msg_types.SYSTEM, "text": "Inventory: " + ", ".join(names)})
                return

            # Find matching item
            inv_lower = inv_arg.lower()
            matched = None
            for item in self._state.inventory:
                if inv_lower in item.name.lower() or item.name.lower() in inv_lower:
                    matched = item
                    break
            if matched:
                self._output({"type": msg_types.SYSTEM, "text": f"{matched.name}: {matched.description}"})
            else:
                self._output({"type": msg_types.SYSTEM, "text": f"You don't have anything called '{inv_arg}'."})
            return

        match = resolve_examine_target(arg, self._state)

        if match is None:
            # No match found
            response = self._narrator.invalid_examine(arg)
            self._output({"type": msg_types.NARRATION, "text": response})
            self._action_log.append("examine", arg, response)
            return

        if match["type"] == "ambiguous":
            # Multiple matches — ask for clarification
            candidate_names = []
            for c in match["data"]:
                if c["type"] == "patron":
                    p = c["data"]
                    candidate_names.append(p.brief_description if isinstance(p, PatronRecord) else str(p))
                elif c["type"] == "object":
                    candidate_names.append(c["data"].get("name", "something"))
                elif c["type"] == "barkeep":
                    candidate_names.append("the barkeep")
            response = self._narrator.ambiguous_examine(arg, candidate_names)
            self._output({"type": msg_types.NARRATION, "text": response})
            self._action_log.append("examine", arg, response)
            return

        # Valid match — determine target key for tracking
        target_data = match["data"]
        target_type = match["type"]

        if target_type == "patron":
            if isinstance(target_data, PatronRecord):
                target_key = target_data.profile_path
                examine_data = {
                    "description": target_data.description,
                    "brief": target_data.brief_description,
                }
                # Load full profile for richer examination
                profile_path = Path(target_data.profile_path)
                if profile_path.exists():
                    full_profile = json.loads(profile_path.read_text(encoding="utf-8"))
                    examine_data = full_profile.get("appearance", examine_data)
            else:
                target_key = str(target_data)
                examine_data = target_data
        elif target_type == "barkeep":
            target_key = "barkeep"
            examine_data = target_data.get("appearance", target_data)
        else:
            # Object
            target_key = target_data.get("name", arg)
            examine_data = target_data

        # Track examine count for escalation
        self._state.examined_targets[target_key] = self._state.examined_targets.get(target_key, 0) + 1
        examine_count = self._state.examined_targets[target_key]

        # Determine talked_to status for name-hiding
        if target_type == "patron" and isinstance(target_data, PatronRecord):
            talked_to = target_data.talked_to
        elif target_type == "barkeep":
            talked_to = False  # Barkeep name hidden until talked to (Phase 3)
        else:
            talked_to = True  # Objects don't have names to hide

        # Get narrator description
        history = self._action_log.get_recent(10)
        response = self._narrator.examine(
            target_type if target_type != "barkeep" else "patron",
            examine_data,
            examine_count,
            history,
            talked_to=talked_to,
        )
        self._output({"type": msg_types.NARRATION, "text": response})
        if target_type == "object" and examine_data.get("image_path"):
            self._output({
                "type": msg_types.IMAGE,
                "image_path": examine_data["image_path"],
            })
        self._action_log.append("examine", arg, response)

    def _handle_status(self, arg: str) -> None:
        """Handle 'status' command — pure Python, no Gemini call."""
        tier = get_tier(self._state.drunkenness)
        drunk_desc = TIER_NAMES[tier]

        location = self._state.tavern_name or "a tavern"
        target = self._state.active_patron or "No one"

        lines = [f"{self._state.player_name} | {drunk_desc} | {location} | Talking to: {target}"]

        # Conversation stats
        talked_patrons = [p for p in self._state.patrons if p.talked_to and p.name]
        if talked_patrons:
            lines.append("Conversations:")
            for p in talked_patrons:
                lines.append(f"  {p.name}: {p.exchange_count} exchanges")
        if self._state.barkeep_talked_to:
            barkeep_name = self._state.barkeep_name or "Barkeep"
            lines.append(f"  {barkeep_name} (barkeep)")
        if self._state.order_history:
            lines.append(f"Tab: {self._state.tab_count} items ordered")

        self._output({"type": msg_types.SYSTEM, "text": "\n".join(lines)})

    def _handle_help(self, arg: str) -> None:
        """Handle 'help' command — fixed in-world text, not AI-generated."""
        help_text = """
A weathered sign hangs behind the bar, its letters faded but legible:

  look (l)              - Survey the tavern and its occupants
  examine [target] (x)  - Take a closer look at someone or something
  talk to [patron] (t)  - Strike up a conversation
  end conversation      - Walk away from a conversation
  order [drink/food]    - Order from the barkeep
  menu (m)              - See what the barkeep serves
  shop (s)              - See what trinkets the barkeep has for sale
  buy [item] (b)        - Purchase a trinket from the barkeep
  use [item]            - Use an item from your inventory
  give [item]           - Give an item to whoever you're talking to
  give [amount] gold    - Give gold to whoever you're talking to
  challenge             - Challenge whoever you're talking to to a bar game
  take [item]           - Pick up an item from the tavern
  examine inv [item]    - Inspect an inventory item
  status                - Check your current state
  help (?)              - Read this sign again
  quit (q)              - Leave the tavern

  While in conversation, prefix commands with / (e.g., /look, /order ale).
  Plain text is spoken to whoever you're talking to.

The barkeep notices you reading and nods knowingly.
"""
        self._output({"type": msg_types.SYSTEM, "text": help_text.strip()})

    def _handle_quit(self, arg: str) -> None:
        """Handle 'quit' command — narrator farewell + y/n confirmation.

        Web mode: skip interactive confirmation, emit GAME_OVER directly.
        CLI mode: prompt for y/n confirmation before ending session.
        """
        farewell = self._narrator.farewell()

        if self._emit:
            # Web mode -- no interactive prompt, just end
            self._state.session_active = False
            self._output({"type": msg_types.GAME_OVER, "text": farewell})
            self._action_log.append("quit", "", farewell)
            return

        # CLI mode -- original confirmation flow
        print(f"\n{farewell}\n")

        try:
            confirm = input("Are you sure you want to leave? (y/n) ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            confirm = "y"

        if confirm in ("y", "yes"):
            self._action_log.append("quit", "", farewell)
            self._state.session_active = False
        else:
            print("\nYou settle back onto your stool.\n")

    def _handle_unknown(self, raw: str) -> None:
        """Handle unrecognized commands — in-world narrator response."""
        response = self._narrator.invalid_command(raw)
        self._output({"type": msg_types.NARRATION, "text": response})
        self._action_log.append("unknown", raw, response)

    # --- Phase 3: Conversation commands ---

    def _resolve_talk_target(self, target_str: str):
        """Resolve a talk target string to a PatronRecord or 'barkeep' sentinel.

        Resolution order:
        1. Barkeep keywords / barkeep name match
        2. Exact patron name match (known names — talked_to patrons)
        3. Keyword overlap scoring against patron keywords and brief descriptions
        4. Barkeep name fallback

        Returns:
            PatronRecord if a patron matched,
            the string "barkeep" if the barkeep matched,
            None if no match found.
        """
        target_lower = target_str.strip().lower()

        # Barkeep keywords
        if target_lower in self.BARKEEP_KEYWORDS:
            return "barkeep"

        # Barkeep name match (exact)
        if self._state.barkeep_name and self._state.barkeep_name.lower() == target_lower:
            return "barkeep"

        # Partial barkeep name match
        if self._state.barkeep_name:
            bk_lower = self._state.barkeep_name.lower()
            bk_tokens = bk_lower.split()
            if target_lower in bk_tokens or (bk_lower.startswith(target_lower) and len(target_lower) >= 3):
                return "barkeep"

        # Exact patron name match (only for names already revealed)
        for patron in self._state.patrons:
            if patron.talked_to and patron.name and patron.name.lower() == target_lower:
                return patron

        # Partial/first name match (only for names already revealed)
        for patron in self._state.patrons:
            if patron.talked_to and patron.name:
                name_lower = patron.name.lower()
                # Check if target matches any single token of the name (first name, last name)
                name_tokens = name_lower.split()
                if target_lower in name_tokens:
                    return patron
                # Check if target is a prefix of the full name (e.g., "thom" matches "thomas finch")
                if name_lower.startswith(target_lower) and len(target_lower) >= 3:
                    return patron

        # Keyword overlap scoring against patrons
        best_score = 0
        best_match = None
        for patron in self._state.patrons:
            score = _keyword_score(target_lower, patron.keywords, patron.brief_description)
            if score > best_score:
                best_score = score
                best_match = patron

        if best_match is not None and best_score > 0:
            return best_match

        # Stage 5: Numbered reference from last look
        if self._state.last_look_order:
            numbered_result = _resolve_by_number(target_str, self._state.last_look_order)
            if numbered_result is not None:
                if numbered_result.get("type") == "patron":
                    return numbered_result["data"]
                elif numbered_result.get("type") == "barkeep":
                    return "barkeep"

        return None

    def _handle_talk(self, target_str: str) -> None:
        """Handle 'talk to [target]' — resolve target, end current conversation if any, start new one."""
        if not target_str:
            self._output({"type": msg_types.SYSTEM, "text": "Talk to whom? Try 'talk to barkeep' or use a description."})
            return

        target = self._resolve_talk_target(target_str)

        if target is None:
            response = self._narrator.invalid_talk_target(target_str)
            self._output({"type": msg_types.NARRATION, "text": response})
            self._action_log.append("talk", target_str, response)
            return

        # If already in conversation with someone else, end it first
        if self._state.active_patron:
            current_name = self._state.active_patron
            if target == "barkeep" and current_name == self._state.barkeep_name:
                # Already talking to barkeep — do nothing special, just continue
                self._output({"type": msg_types.SYSTEM, "text": f"You are already talking to {current_name}."})
                return
            if isinstance(target, object) and not isinstance(target, str):
                patron_record = target
                if patron_record.name and patron_record.name == current_name:
                    # Already talking to this patron
                    self._output({"type": msg_types.SYSTEM, "text": f"You are already talking to {current_name}."})
                    return
            # Switch conversation: farewell current, then start new
            self._end_current_conversation(silent=False)

        # --- Start new conversation ---
        history = self._action_log.get_recent(10)

        if target == "barkeep":
            # Barkeep conversation — check is_resuming BEFORE get_or_create creates the agent
            is_resuming = self._state.barkeep_talked_to
            barkeep = self._agent_manager.get_or_create_barkeep()

            # Build a simple namespace for approach_patron (needs .name and .brief_description)
            class _BarkeepRecord:
                pass
            _bk = _BarkeepRecord()
            _bk.name = self._state.barkeep_name or "the barkeep"
            _bk.brief_description = "the barkeep behind the counter"
            _bk.exchange_count = 0

            approach_text = self._narrator.approach_patron(_bk, is_resuming, history)
            self._output({"type": msg_types.NARRATION, "text": approach_text})
            greeting = barkeep.greeting(is_resuming=is_resuming)
            barkeep_display_name = self._state.barkeep_name or "Barkeep"
            self._output({"type": msg_types.DIVIDER, "text": f"\u2014\u2014\u2014 Talking to {barkeep_display_name} \u2014\u2014\u2014"})
            self._output({"type": msg_types.DIALOGUE, "speaker": barkeep_display_name, "text": greeting})
            self._state.active_patron = barkeep_display_name
            self._state.barkeep_talked_to = True
            self._action_log.append("talk", barkeep_display_name, greeting)

        else:
            # Patron conversation
            patron_record = target

            # Reveal name from profile FIRST, then mark talked_to
            if patron_record.name is None:
                # Load the profile to get the name
                profile_path = Path(patron_record.profile_path)
                if profile_path.exists():
                    full_profile = json.loads(profile_path.read_text(encoding="utf-8"))
                    patron_record.name = full_profile.get("identity", {}).get("name", "Unknown")
            # Mark talked_to AFTER name is guaranteed loaded
            # (look command _build_look_list checks BOTH talked_to and name — if talked_to is True
            # but name is None, the patron shows as a generic description instead of their name)
            patron_record.talked_to = True

            is_resuming = patron_record.exchange_count > 0

            # Ensure agent exists (may need to load profile into agent_manager if not already done)
            if patron_record.profile_path not in self._agent_manager._patron_profiles:
                profile_path = Path(patron_record.profile_path)
                if profile_path.exists():
                    self._agent_manager._patron_profiles[patron_record.profile_path] = json.loads(
                        profile_path.read_text(encoding="utf-8")
                    )

            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)

            approach_text = self._narrator.approach_patron(patron_record, is_resuming, history)
            self._output({"type": msg_types.NARRATION, "text": approach_text})
            greeting = agent.greeting(is_resuming=is_resuming)
            self._output({"type": msg_types.DIVIDER, "text": f"\u2014\u2014\u2014 Talking to {patron_record.name} \u2014\u2014\u2014"})
            self._output({"type": msg_types.DIALOGUE, "speaker": patron_record.name, "text": greeting})
            self._state.active_patron = patron_record.name
            self._action_log.append("talk", patron_record.name, greeting)

    def _handle_conversation_input(self, raw: str) -> None:
        """Route free-form player input to the active patron agent during conversation.

        Garbles player speech at tier > 0 and displays the garbled version before
        NPC responds. NPCs receive garbled text with a bracket tier context note.
        Order intent detection always uses original text for reliability.
        After NPC responds, checks for pass-out at tier 4.
        """
        active_name = self._state.active_patron

        # Compute tier and garble speech
        tier = get_tier(self._state.drunkenness)
        garbled = garble(raw, tier, self._model_name)

        # Display garbled version to player BEFORE NPC responds (only at tier > 0)
        # At tier 0, player already sees what they typed — no echo needed
        if tier > 0:
            speech_label = SPEECH_LABELS[tier]
            self._output({"type": msg_types.PLAYER_ECHO, "text": f"{speech_label}: {garbled}"})

        # Build NPC message with tier context note
        npc_message = garbled
        if tier > 0:
            npc_message = f"[The player is {TIER_NAMES[tier]} — their speech is slurred.] " + garbled
        if self._state.passed_out:
            npc_message = "[This patron just watched the player pass out and wake up on the tavern floor.] " + npc_message
            self._state.passed_out = False  # Clear after first use

        # Determine if talking to barkeep or a patron
        gift = None  # Only patron branch may set this
        if active_name == self._state.barkeep_name or (
            self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
        ):
            agent = self._agent_manager.get_or_create_barkeep()

            # Order-intent detection: ALWAYS use ORIGINAL raw text for detection and resolution
            raw_lower = raw.lower()
            order_detected = any(kw in raw_lower for kw in self.ORDER_INTENT_KEYWORDS)

            if order_detected:
                # Try to resolve a menu item from the natural language — ORIGINAL text for matching
                item, matched_name = agent.resolve_order(raw)
                if item is not None:
                    # Route to the order handler with the resolved item name
                    self._handle_order(matched_name, in_conversation=True)
                    return

            # No order intent or no menu item resolved — normal conversation with garbled message
            response = agent.send(npc_message)
            # No PatronRecord for barkeep — exchange_count tracked within BarkeepAgent
        else:
            patron_record = self._find_active_patron_record()
            if patron_record is None:
                self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": "..."})
                return
            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
            response, gift = agent.send_with_gift_check(npc_message)
            patron_record.exchange_count += 1

            # Drift check (silent — logged only)
            if patron_record.exchange_count == 20:
                self._action_log.append("system", "drift_check", f"20-turn drift threshold reached for {active_name}")

        self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": response})

        # Process patron gift (if any) -- only in patron branch (not barkeep)
        if gift is not None:
            if gift["type"] == "item":
                inv_item = InventoryItem(
                    name=gift["name"],
                    description=gift["description"],
                    item_type="trinket",
                    reusable=True,
                    source="patron_gift",
                )
                self._state.inventory.append(inv_item)
                self._output({"type": msg_types.SYSTEM,
                              "text": f"[System]: You received {gift['name']} from {active_name}."})
            elif gift["type"] == "gold":
                self._state.gold += gift["amount"]
                self._output({"type": msg_types.SYSTEM,
                              "text": f"[System]: {active_name} gives you {gift['amount']} gold."})

        self._action_log.append("conversation", active_name, response)

        # Pass-out check at tier 4 (Gone to the saints)
        self._check_pass_out()

    def _handle_mid_conversation_command(self, raw: str) -> None:
        """Have the active patron react when player tries a game command during conversation."""
        active_name = self._state.active_patron

        if active_name == self._state.barkeep_name or (
            self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
        ):
            agent = self._agent_manager.get_or_create_barkeep()
        else:
            patron_record = self._find_active_patron_record()
            if patron_record is None:
                return
            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)

        response = agent.mid_conversation_reaction(raw)
        self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": response})

    def _handle_end_conversation(self, arg: str) -> None:
        """Handle 'end conversation' — patron farewell, narrator stepping away, clear active_patron."""
        if self._state.active_patron is None:
            self._output({"type": msg_types.SYSTEM, "text": "You're not talking to anyone."})
            return
        self._end_current_conversation(silent=False)

    def _end_current_conversation(self, silent: bool = False) -> None:
        """Internal helper: end the current conversation, optionally with farewell output.

        Args:
            silent: If True, skip farewell/stepping-away output (for edge cases).
        """
        active_name = self._state.active_patron
        if active_name is None:
            return

        # Clear any active game session when leaving conversation
        if self._state.game_session is not None:
            self._output({"type": msg_types.SYSTEM, "text": "The game is abandoned."})
            self._state.game_session = None

        if not silent:
            # Get farewell from patron/barkeep
            if active_name == self._state.barkeep_name or (
                self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
            ):
                agent = self._agent_manager.get_or_create_barkeep()
            else:
                patron_record = self._find_active_patron_record()
                if patron_record is not None:
                    agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
                else:
                    agent = None

            if agent is not None:
                farewell = agent.farewell()
                self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": farewell})
                stepping = self._narrator.stepping_away(active_name)
                self._output({"type": msg_types.NARRATION, "text": stepping})
                self._output({"type": msg_types.DIVIDER, "text": f"\u2014\u2014\u2014 Left conversation with {active_name} \u2014\u2014\u2014"})
                self._action_log.append("end_conversation", active_name, farewell)

        self._state.active_patron = None

    def _find_active_patron_record(self):
        """Find the PatronRecord for the currently active patron (by name match).

        Returns:
            PatronRecord if found, None otherwise.
        """
        active_name = self._state.active_patron
        if active_name is None:
            return None
        for patron in self._state.patrons:
            if patron.name and patron.name == active_name:
                return patron
        return None

    def _check_pass_out(self) -> None:
        """Roll for pass-out at tier 4 (Gone to the saints). Called after speech/order actions.

        Probabilities:
          ~5%:  Game over — dramatic narrator farewell, session ends.
          ~25%: Pass out and wake up — drunkenness resets to 0, conversation ends,
                passed_out flag set so first post-wake NPC interaction includes context note.
          ~70%: No effect — continue with extreme garbling.
        """
        if get_tier(self._state.drunkenness) < 4:
            return

        roll = random.random()
        if roll < 0.05:
            # ~5%: game over — dramatic narrator farewell
            text = self._narrator.pass_out_finale()
            self._output({"type": msg_types.GAME_OVER, "text": text})
            self._state.session_active = False
            self._state.active_patron = None
        elif roll < 0.30:
            # ~25%: pass out, wake up — drunkenness resets to 0
            text = self._narrator.pass_out_and_wake()
            self._output({"type": msg_types.NARRATION, "text": text})
            self._state.drunkenness = 0
            self._state.passed_out = True
            # Wake up ends any active conversation (player just collapsed — no farewell)
            if self._state.active_patron:
                self._state.active_patron = None
        # else: ~70% continue with extreme garbling — no action needed

    def _handle_order(self, arg: str, in_conversation: bool = False) -> None:
        """Handle 'order [item]' — barkeep serves item, updates drunkenness, tracks tab.

        Captures tier before and after drunkenness update to detect tier transitions.
        Displays garbled version of the order to the player if drunk (tier > 0).
        Announces tier transitions via narrator before barkeep response.
        Checks for pass-out at tier 4 after the order is resolved.
        """
        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Order what? Try 'order ale' or 'menu' to see what's available."})
            return

        if self._agent_manager is None:
            self._output({"type": msg_types.SYSTEM, "text": "[The barkeep is not ready yet.]"})
            return

        barkeep = self._agent_manager.get_or_create_barkeep()

        # Resolve item and check cost BEFORE calling barkeep.order()
        item, matched_name = barkeep.resolve_order(arg)
        if item is not None:
            cost = item.get("cost", 0)
            if cost > 0 and self._state.gold < cost:
                # Can't afford -- barkeep refuses in character
                response = barkeep.refuse_order_insufficient_funds(arg, cost, self._state.gold)
                barkeep_name = self._state.barkeep_name or "Barkeep"
                self._output({"type": msg_types.DIALOGUE, "speaker": barkeep_name, "text": response})
                return
            if cost > 0:
                self._state.gold -= cost  # Deduct BEFORE Gemini call

        response, drunkenness_delta = barkeep.order(arg, in_conversation=in_conversation)

        # Capture old tier BEFORE updating drunkenness (for transition detection)
        old_tier = get_tier(self._state.drunkenness)
        # Also capture tier for garbled order display (pre-drink tier — player hasn't drunk yet)
        display_tier = old_tier

        # Update state
        self._state.drunkenness += drunkenness_delta
        self._state.drunkenness = max(0, self._state.drunkenness)

        # Track successful order (non-zero drunkenness change means item was served from menu)
        if drunkenness_delta != 0:
            self._state.order_history.append({"item_name": arg, "drunkenness_modifier": drunkenness_delta})
            self._state.tab_count += 1

        # Detect tier transition and announce via narrator
        new_tier = get_tier(self._state.drunkenness)
        if new_tier != old_tier:
            transition_text = self._narrator.tier_transition(old_tier, new_tier)
            self._output({"type": msg_types.NARRATION, "text": transition_text})

        # Show garbled version of the order to the player if drunk
        if display_tier > 0 and drunkenness_delta != 0:
            order_garbled = garble(arg, display_tier, self._model_name)
            speech_label = SPEECH_LABELS[display_tier]
            self._output({"type": msg_types.PLAYER_ECHO, "text": f"{speech_label}: {order_garbled}"})

        barkeep_name = self._state.barkeep_name or "Barkeep"
        self._output({"type": msg_types.DIALOGUE, "speaker": barkeep_name, "text": response})

        # Mid-conversation: optionally get patron reaction
        if in_conversation and self._state.active_patron and self._state.active_patron != barkeep_name:
            patron_record = self._find_active_patron_record()
            if patron_record is not None:
                patron_agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
                reaction = patron_agent.send(
                    "[The barkeep just served the player a drink. React briefly in character, "
                    "1 sentence — you might comment on the drink or just acknowledge it.]"
                )
                self._output({"type": msg_types.DIALOGUE, "speaker": self._state.active_patron, "text": reaction})

        self._action_log.append("order", arg, response)

        # Pass-out check at tier 4 (Gone to the saints)
        self._check_pass_out()

    def _handle_menu(self, arg: str) -> None:
        """Handle 'menu' command — display the barkeep's menu."""
        if self._agent_manager is None:
            self._output({"type": msg_types.SYSTEM, "text": "[The barkeep has nothing to show you yet.]"})
            return
        barkeep = self._agent_manager.get_or_create_barkeep()
        self._output({"type": msg_types.SYSTEM, "text": barkeep.get_menu_text()})

    def _handle_shop(self, arg: str) -> None:
        """Handle 'shop' command -- display barkeep's trinket/gift inventory with prices."""
        if self._agent_manager is None:
            self._output({"type": msg_types.SYSTEM, "text": "[The barkeep has nothing to show you yet.]"})
            return
        barkeep = self._agent_manager.get_or_create_barkeep()
        shop_text = barkeep.get_shop_text(self._state.shop_items)
        self._output({"type": msg_types.SYSTEM, "text": shop_text})

    def _handle_buy(self, arg: str) -> None:
        """Handle 'buy [item]' -- purchase a trinket from the barkeep's shop."""
        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Buy what? Type 'shop' to see what's available."})
            return
        if self._agent_manager is None:
            self._output({"type": msg_types.SYSTEM, "text": "[The barkeep has nothing to sell you yet.]"})
            return

        # Resolve item from shop_items using fuzzy matching
        arg_lower = arg.strip().lower()
        matched_item = None
        for item in self._state.shop_items:
            item_name_lower = item["name"].lower()
            if item_name_lower in arg_lower or arg_lower in item_name_lower:
                matched_item = item
                break

        # Tier 2: token overlap if no exact match
        if matched_item is None:
            stop_words = frozenset({"a", "an", "the", "some", "that", "this"})
            arg_tokens = set(arg_lower.split()) - stop_words
            for item in self._state.shop_items:
                item_tokens = set(item["name"].lower().split()) - stop_words
                if item_tokens and item_tokens.issubset(arg_tokens):
                    matched_item = item
                    break

        if matched_item is None:
            self._output({"type": msg_types.SYSTEM, "text": f"The barkeep doesn't have anything called '{arg}'. Type 'shop' to see what's available."})
            return

        cost = matched_item.get("price", 0)
        if cost > 0 and self._state.gold < cost:
            barkeep = self._agent_manager.get_or_create_barkeep()
            response = barkeep.refuse_order_insufficient_funds(matched_item["name"], cost, self._state.gold)
            barkeep_name = self._state.barkeep_name or "Barkeep"
            self._output({"type": msg_types.DIALOGUE, "speaker": barkeep_name, "text": response})
            return

        # Deduct gold
        if cost > 0:
            self._state.gold -= cost

        # Create InventoryItem and add to inventory
        inv_item = InventoryItem(
            name=matched_item["name"],
            description=matched_item.get("description", ""),
            item_type=matched_item.get("item_type", "trinket"),
            reusable=True,
            source="shop",
        )
        self._state.inventory.append(inv_item)

        # Remove from shop (one-of-each -- item is sold)
        self._state.shop_items = [s for s in self._state.shop_items if s["name"] != matched_item["name"]]

        # Barkeep acknowledges the sale in character
        barkeep = self._agent_manager.get_or_create_barkeep()
        response = barkeep.buy_item(matched_item["name"], cost)
        barkeep_name = self._state.barkeep_name or "Barkeep"
        self._output({"type": msg_types.DIALOGUE, "speaker": barkeep_name, "text": response})
        self._action_log.append("buy", matched_item["name"], response)

    def _handle_use(self, arg: str) -> None:
        """Handle 'use [item]' -- narrate using an inventory item or interact with in-place examinable."""
        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Use what? Check your inventory in the side panel."})
            return

        # Check examinables for in-place use first
        arg_lower = arg.strip().lower()
        for obj in self._state.examinables:
            if obj.get("usable_in_place") and any(
                kw.lower() in arg_lower for kw in obj.get("keywords", [])
            ):
                use_text = obj.get("use_text", "Nothing interesting happens.")
                self._output({"type": msg_types.NARRATION, "text": use_text})
                return

        # Find item in inventory (case-insensitive partial match)
        arg_lower = arg.strip().lower()
        matched_item = None
        for item in self._state.inventory:
            if arg_lower in item.name.lower() or item.name.lower() in arg_lower:
                matched_item = item
                break

        if matched_item is None:
            self._output({"type": msg_types.SYSTEM, "text": f"You don't have '{arg}' in your inventory."})
            return

        # Generate use narration via safe_generate (flavor text, no mechanical effects)
        from agents.base_agent import safe_generate
        prompt = (
            f"[The player uses their {matched_item.name}: {matched_item.description}. "
            f"Narrate the use in 1-2 sentences — vivid, sensory, in-world. "
            f"No mechanical effects — this is pure flavor.]"
        )
        response = safe_generate(self._model_name, prompt)
        self._output({"type": msg_types.NARRATION, "text": response})
        self._action_log.append("use", matched_item.name, response)

        # Consume non-reusable items
        if not matched_item.reusable:
            self._state.inventory.remove(matched_item)
            self._output({"type": msg_types.SYSTEM, "text": f"[{matched_item.name} has been consumed.]"})

    def _handle_take(self, arg: str) -> None:
        """Handle 'take [item]' -- pick up a pickable examinable into inventory."""
        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Take what? Try: take [item name]"})
            return

        match = resolve_examine_target(arg, self._state)
        if not match:
            self._output({"type": msg_types.SYSTEM, "text": f"You don't see '{arg}' here."})
            return

        if match["type"] != "object":
            self._output({"type": msg_types.SYSTEM, "text": "You can't take that."})
            return

        obj = match["data"]
        if not obj.get("pickable", False):
            self._output({"type": msg_types.SYSTEM, "text": f"The {obj['name']} isn't something you can carry."})
            return

        # Remove from room examinables
        self._state.examinables = [e for e in self._state.examinables if e.get("name") != obj["name"]]

        # Track picked-up item name for load filtering
        self._state.picked_up_items.append(obj["name"])

        # Add to inventory
        inv_item = InventoryItem(
            name=obj["name"],
            description=obj.get("detailed", "A curious item."),
            item_type="trinket",
            reusable=True,
            source="found",
        )
        self._state.inventory.append(inv_item)
        self._output({"type": msg_types.NARRATION, "text": f"You pick up the {obj['name']} and tuck it away."})
        if obj.get("image_path"):
            self._output({
                "type": msg_types.IMAGE,
                "image_path": obj["image_path"],
            })

    def _handle_give(self, arg: str) -> None:
        """Handle 'give [item]' or 'give [amount] gold' during conversation."""
        if not self._state.active_patron:
            self._output({"type": msg_types.SYSTEM, "text": "Give what to whom? You must be talking to someone first."})
            return

        if not arg:
            self._output({"type": msg_types.SYSTEM, "text": "Give what? Try 'give [item name]' or 'give [amount] gold'."})
            return

        active_name = self._state.active_patron

        # Parse 'give N gold' pattern
        tokens = arg.strip().split()
        if len(tokens) == 2 and tokens[1].lower() == "gold" and tokens[0].isdigit():
            amount = int(tokens[0])
            if amount <= 0:
                self._output({"type": msg_types.SYSTEM, "text": "That's not a meaningful amount."})
                return
            if self._state.gold < amount:
                self._output({"type": msg_types.SYSTEM, "text": f"You only have {self._state.gold} gold."})
                return

            self._state.gold -= amount

            # Get patron/barkeep agent to react
            if active_name == self._state.barkeep_name or (
                self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
            ):
                agent = self._agent_manager.get_or_create_barkeep()
            else:
                patron_record = self._find_active_patron_record()
                if patron_record is None:
                    self._output({"type": msg_types.SYSTEM, "text": "Something went wrong."})
                    self._state.gold += amount  # Refund
                    return
                agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)

            prompt = (
                f"[The player has just handed you {amount} gold coins as a gift. "
                f"React in character — you might be grateful, suspicious, confused, "
                f"or touched depending on your personality and the conversation so far. "
                f"1-3 sentences.]"
            )
            response = agent.send(prompt)
            self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": response})
            self._action_log.append("give_gold", str(amount), response)
            return

        # Look up item in inventory (case-insensitive partial match)
        arg_lower = arg.strip().lower()
        matched_item = None
        for item in self._state.inventory:
            if arg_lower in item.name.lower() or item.name.lower() in arg_lower:
                matched_item = item
                break

        if matched_item is None:
            self._output({"type": msg_types.SYSTEM, "text": f"You don't have '{arg}' in your inventory."})
            return

        # Remove from inventory
        self._state.inventory.remove(matched_item)

        # Get patron/barkeep agent to react to the specific item
        if active_name == self._state.barkeep_name or (
            self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
        ):
            agent = self._agent_manager.get_or_create_barkeep()
        else:
            patron_record = self._find_active_patron_record()
            if patron_record is None:
                # Edge case: put item back if we can't find the patron
                self._state.inventory.append(matched_item)
                self._output({"type": msg_types.SYSTEM, "text": "Something went wrong."})
                return
            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)

        prompt = (
            f"[The player has just given you a '{matched_item.name}' "
            f"({matched_item.description}). "
            f"React to this specific item in character — consider whether it is something "
            f"your character would value, find odd, or feel moved by. "
            f"1-3 sentences.]"
        )
        response = agent.send(prompt)
        self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": response})
        self._action_log.append("give_item", matched_item.name, response)

    def _handle_save(self, arg: str) -> None:
        """Handle /save command -- serialize game state to disk."""
        from game.save_manager import save_game
        try:
            save_game(self._state, self._agent_manager)
            # Narrator in-world flavor line (per user decision: dual confirmation)
            flavor = self._narrator.save_confirmation()
            self._output({"type": msg_types.NARRATION, "text": flavor})
            self._output({"type": msg_types.SYSTEM, "text": "[System]: Game saved."})
        except Exception as e:
            self._output({"type": msg_types.SYSTEM, "text": f"[System]: Save failed -- {e}"})

    def _maybe_trigger_ambient(self) -> None:
        """Possibly display ambient flavor text after look/examine commands.

        Rules:
        - Random chance based on ambient_chance config
        - Minimum 1 command gap between ambient triggers
        - 20% chance of live-generated (context-aware) ambient; 80% from pool
        """
        # Check minimum gap
        if self._state.command_count - self._state.last_ambient_at < 2:
            return

        # Random chance
        if random.random() > self._ambient_chance:
            return

        self._state.last_ambient_at = self._state.command_count

        # Choose ambient source: 80% pool, 20% live
        if self._state.ambient_pool and random.random() > 0.2:
            # Pool ambient — pick and remove to avoid repeats
            line = random.choice(self._state.ambient_pool)
            self._state.ambient_pool.remove(line)
        else:
            # Live ambient — context-aware
            history = self._action_log.get_all()
            line = self._narrator.generate_live_ambient(history)

        if line:
            self._output({"type": msg_types.NARRATION, "text": line})
            self._action_log.append("ambient", "", line)

    # --- Phase 9: Bar game commands ---

    def _handle_challenge(self, arg: str) -> None:
        """Handle 'challenge' command -- initiate a bar game with the active patron."""
        from game.bar_games import GAME_REGISTRY, GAME_DISPLAY_NAMES

        if not self._state.active_patron:
            self._output({"type": msg_types.SYSTEM, "text": "Challenge whom? You must be talking to someone first."})
            return

        active_name = self._state.active_patron

        # Cannot challenge barkeep
        if active_name == self._state.barkeep_name or (
            self._state.barkeep_talked_to and active_name == (self._state.barkeep_name or "Barkeep")
        ):
            self._output({"type": msg_types.SYSTEM, "text": "The barkeep shakes their head. 'I've a tavern to run. Find someone else to play with.'"})
            return

        # Already in a game
        if self._state.game_session is not None:
            self._output({"type": msg_types.SYSTEM, "text": "You're already in a game. Finish it first."})
            return

        patron_record = self._find_active_patron_record()
        if patron_record is None:
            self._output({"type": msg_types.SYSTEM, "text": "Something went wrong."})
            return

        # Check patron has gold to wager
        if patron_record.gold <= 0:
            self._output({"type": msg_types.DIALOGUE, "speaker": active_name,
                          "text": "*pats empty pockets* 'I haven't a coin to my name tonight. Perhaps another time.'"})
            return

        # Check player has gold to wager
        if self._state.gold <= 0:
            self._output({"type": msg_types.SYSTEM, "text": "You have no gold to wager."})
            return

        # Get available games from tavern template
        tavern_path = Path("agent_profiles/tavern.json")
        if tavern_path.exists():
            tavern_data = json.loads(tavern_path.read_text(encoding="utf-8"))
            available_ids = tavern_data.get("available_games") or tavern_data.get("template", {}).get("available_games", [])
        else:
            available_ids = ["high_roll", "coin_toss"]  # Fallback

        available_games = [gid for gid in available_ids if gid in GAME_REGISTRY]
        if not available_games:
            available_games = ["high_roll"]  # Safe fallback

        game_names = [GAME_DISPLAY_NAMES.get(gid, gid) for gid in available_games]

        # Ask patron if they accept via Gemini (ACCEPT_GAME:YES/NO marker)
        agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
        acceptance_prompt = (
            f"[SYSTEM: The player has challenged you to a bar game. "
            f"Games available at this tavern: {', '.join(game_names)}. "
            f"Your gold: {patron_record.gold}. "
            f"Based on your personality and the conversation so far, decide whether to accept or refuse. "
            f"If accepting, mention the available games by name in your response and tell the player to pick one. "
            f"Respond in character (1-3 sentences). "
            f"At the very end of your response, include ACCEPT_GAME:YES if accepting or ACCEPT_GAME:NO if refusing.]"
        )
        response = agent._safe_send(acceptance_prompt)

        # Parse acceptance marker
        accepted = "ACCEPT_GAME:YES" in response
        # Strip marker from display text
        display_response = response.replace("ACCEPT_GAME:YES", "").replace("ACCEPT_GAME:NO", "").strip()
        self._output({"type": msg_types.DIALOGUE, "speaker": active_name, "text": display_response})

        if not accepted:
            self._action_log.append("challenge_refused", active_name, display_response)
            return

        # Show game selection menu
        game_list = "\n".join(f"  {i+1}. {GAME_DISPLAY_NAMES.get(gid, gid)}" for i, gid in enumerate(available_games))
        self._output({"type": msg_types.SYSTEM, "text": f"Choose a game:\n{game_list}\n\nType the number or name to pick."})

        # Set up game session in "awaiting_game_choice" state
        self._state.game_session = {
            "state": "awaiting_game_choice",
            "patron_name": active_name,
            "patron_profile_path": patron_record.profile_path,
            "available_games": available_games,
            "wager": 0,
            "negotiation_round": 0,
        }

    def _handle_game_input(self, raw: str) -> None:
        """Route game-related input based on the current game_session state."""
        gs = self._state.game_session
        if gs is None:
            return

        state = gs.get("state", "")

        if state == "awaiting_game_choice":
            self._handle_game_choice(raw, gs)
        elif state == "awaiting_wager_response":
            self._handle_wager_response(raw, gs)
        elif state == "playing":
            self._handle_game_turn(raw, gs)
        else:
            # Unknown state -- clear and return to conversation
            self._state.game_session = None
            self._output({"type": msg_types.SYSTEM, "text": "The game fizzles out. Something went wrong."})

    def _handle_game_choice(self, raw: str, gs: dict) -> None:
        """Handle player picking a game from the list."""
        from game.bar_games import GAME_REGISTRY, GAME_DISPLAY_NAMES

        available = gs["available_games"]
        choice = raw.strip().lower()

        # Match by number
        selected_id = None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(available):
                selected_id = available[idx]
        else:
            # Match by name (partial, case-insensitive)
            for gid in available:
                display = GAME_DISPLAY_NAMES.get(gid, gid).lower()
                if choice in display or display in choice or choice == gid:
                    selected_id = gid
                    break

        if selected_id is None:
            game_list = ", ".join(GAME_DISPLAY_NAMES.get(gid, gid) for gid in available)
            self._output({"type": msg_types.SYSTEM, "text": f"Pick a game: {game_list}. Type the number or name."})
            return

        gs["game_id"] = selected_id
        game_name = GAME_DISPLAY_NAMES.get(selected_id, selected_id)

        self._output({"type": msg_types.SYSTEM, "text": f"You choose {game_name}."})

        # Patron proposes wager via Gemini
        patron_record = self._find_active_patron_record()
        if patron_record is None:
            self._state.game_session = None
            return

        agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
        max_wager = min(patron_record.gold, self._state.gold)
        wager_prompt = (
            f"[SYSTEM: You agreed to play {game_name} with the player. "
            f"Propose a wager amount in character. Your gold: {patron_record.gold}. "
            f"Player's gold (for reference): {self._state.gold}. "
            f"Wager must be between 1 and {max_wager}. "
            f"Include the amount at the end of your response as WAGER:N (e.g., WAGER:5). "
            f"Respond in character (1-2 sentences).]"
        )
        response = agent._safe_send(wager_prompt)

        # Parse WAGER:N marker
        wager_match = re.search(r'WAGER:(\d+)', response)
        proposed_wager = int(wager_match.group(1)) if wager_match else max(1, patron_record.gold // 3)
        # Clamp to valid range
        proposed_wager = max(1, min(proposed_wager, max_wager))

        # Strip marker from display
        display_response = re.sub(r'\s*WAGER:\d+\s*', '', response).strip()
        self._output({"type": msg_types.DIALOGUE, "speaker": gs["patron_name"], "text": display_response})
        self._output({"type": msg_types.SYSTEM, "text": f"Proposed wager: {proposed_wager} gold. Type 'accept' to agree, or a number to counter."})

        gs["state"] = "awaiting_wager_response"
        gs["wager"] = proposed_wager
        gs["negotiation_round"] = 1

    def _handle_wager_response(self, raw: str, gs: dict) -> None:
        """Handle player accepting or countering a wager."""
        choice = raw.strip().lower()
        patron_record = self._find_active_patron_record()
        if patron_record is None:
            self._state.game_session = None
            return

        max_wager = min(patron_record.gold, self._state.gold)

        if choice in ("accept", "yes", "aye", "agree", "deal"):
            # Wager accepted -- start the game
            self._start_game(gs)
            return

        if choice in ("refuse", "no", "nay", "nevermind", "cancel", "quit"):
            self._output({"type": msg_types.SYSTEM, "text": "You back out of the challenge."})
            self._state.game_session = None
            return

        # Try to parse a counter-offer number
        counter = None
        tokens = choice.split()
        for token in tokens:
            if token.isdigit():
                counter = int(token)
                break

        if counter is None:
            self._output({"type": msg_types.SYSTEM, "text": "Type 'accept' to agree, a number to counter, or 'cancel' to back out."})
            return

        if counter <= 0:
            self._output({"type": msg_types.SYSTEM, "text": "The wager must be at least 1 gold."})
            return
        if counter > self._state.gold:
            self._output({"type": msg_types.SYSTEM, "text": f"You only have {self._state.gold} gold."})
            return
        if counter > patron_record.gold:
            self._output({"type": msg_types.SYSTEM, "text": f"{gs['patron_name']} only has {patron_record.gold} gold."})
            return

        gs["negotiation_round"] += 1

        if gs["negotiation_round"] > 2:
            # Max rounds exceeded -- patron walks away
            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
            walkaway = agent._safe_send(
                f"[SYSTEM: The player countered your wager twice. You've lost patience with negotiating. "
                f"Walk away from the challenge in character. 1-2 sentences.]"
            )
            self._output({"type": msg_types.DIALOGUE, "speaker": gs["patron_name"], "text": walkaway})
            self._state.game_session = None
            return

        # Patron considers the counter
        agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
        consider_prompt = (
            f"[SYSTEM: The player countered with a wager of {counter} gold. "
            f"Your gold: {patron_record.gold}. "
            f"Accept or refuse in character (1-2 sentences). "
            f"If accepting, include WAGER_ACCEPT:YES at the end. "
            f"If refusing, include WAGER_ACCEPT:NO at the end.]"
        )
        response = agent._safe_send(consider_prompt)

        accepted = "WAGER_ACCEPT:YES" in response
        display = response.replace("WAGER_ACCEPT:YES", "").replace("WAGER_ACCEPT:NO", "").strip()
        self._output({"type": msg_types.DIALOGUE, "speaker": gs["patron_name"], "text": display})

        if accepted:
            gs["wager"] = counter
            self._start_game(gs)
        else:
            self._output({"type": msg_types.SYSTEM, "text": f"Type 'accept' for {gs['wager']} gold, a new counter, or 'cancel'."})

    def _start_game(self, gs: dict) -> None:
        """Transition from wager negotiation to active gameplay."""
        from game.bar_games import GAME_DISPLAY_NAMES

        game_name = GAME_DISPLAY_NAMES.get(gs.get("game_id", ""), gs.get("game_id", "a game"))
        wager = gs["wager"]
        self._output({"type": msg_types.SYSTEM, "text": f"The game begins! {game_name} for {wager} gold."})

        # Provide input instructions based on game type
        game_id = gs.get("game_id", "")
        instructions = {
            "high_roll": "Type anything to roll the dice.",
            "over_under": "Guess: 'over', 'under', or 'seven'.",
            "high_card": "Type anything to draw a card.",
            "sword_shield_arrow": "Choose: 'sword', 'shield', or 'arrow'.",
            "morra": "Type: 'show [1-5] guess [2-10]' (e.g., 'show 3 guess 7').",
            "coin_toss": "Call: 'heads' or 'tails'.",
            "cup_and_ball": "Pick a cup: '1', '2', or '3'.",
            "odds_and_evens": "Choose: 'odds' or 'evens'.",
            "three_card": "Pick a card: '1', '2', or '3'.",
            "knucklebones": "Type anything to toss the bones.",
            "arm_wrestle": "Choose your arm: 'left' or 'right'. Best 2 of 3 rounds!",
            "merchants_gambit": "Place your bid: '1', '2', or '3'. Best 2 of 3 rounds!",
            "beggars_bluff": "Make your claim: 'rich' or 'poor'. Best 2 of 3 rounds!",
        }
        hint = instructions.get(game_id, "Make your move.")
        self._output({"type": msg_types.SYSTEM, "text": hint})

        gs["state"] = "playing"
        gs["round"] = 1
        gs["patron_score"] = None
        gs["player_score"] = None

    def _handle_game_turn(self, raw: str, gs: dict) -> None:
        """Process one round of the active game."""
        from game.bar_games import GAME_REGISTRY, GAME_DISPLAY_NAMES

        game_id = gs.get("game_id", "")
        game_func = GAME_REGISTRY.get(game_id)
        if game_func is None:
            self._output({"type": msg_types.SYSTEM, "text": "Game not found. Ending."})
            self._state.game_session = None
            return

        # Run the game mechanic
        session_data = gs.get("game_data", {})
        updated_session, display_text, outcome = game_func(session_data, raw.strip())
        gs["game_data"] = updated_session

        self._output({"type": msg_types.NARRATION, "text": display_text})

        if outcome == "continue":
            # Game needs more input (invalid input or multi-round continuation)
            return

        # Game resolved -- handle outcome
        wager = gs.get("wager", 0)
        patron_name = gs.get("patron_name", "Your opponent")
        game_name = GAME_DISPLAY_NAMES.get(game_id, game_id)

        patron_record = self._find_active_patron_record()

        if outcome == "player_wins":
            self._state.gold += wager
            if patron_record:
                patron_record.gold -= wager
            self._output({"type": msg_types.SYSTEM,
                          "text": f"You win {wager} gold! (Your gold: {self._state.gold})"})
        elif outcome == "patron_wins":
            self._state.gold -= wager
            if patron_record:
                patron_record.gold += wager
            self._output({"type": msg_types.SYSTEM,
                          "text": f"You lose {wager} gold. (Your gold: {self._state.gold})"})
        elif outcome == "tie":
            self._output({"type": msg_types.SYSTEM, "text": "It's a tie! No gold changes hands."})

        # Patron reacts to outcome via Gemini
        if patron_record:
            agent = self._agent_manager.get_or_create_patron(patron_record.profile_path)
            if outcome == "player_wins":
                result_desc = f"you lost the game and {wager} gold"
            elif outcome == "patron_wins":
                result_desc = f"you won the game and {wager} gold"
            else:
                result_desc = "the game ended in a tie -- no gold changed hands"

            reaction_prompt = (
                f"[SYSTEM: The {game_name} game just ended. Result: {result_desc}. "
                f"Your remaining gold: {patron_record.gold}. "
                f"React in character to this outcome. Win, loss, and tie should produce distinct reactions. "
                f"2-3 sentences.]"
            )
            reaction = agent._safe_send(reaction_prompt)
            self._output({"type": msg_types.DIALOGUE, "speaker": patron_name, "text": reaction})

        self._action_log.append("bar_game", f"{game_id}:{outcome}:{wager}", display_text)

        # Clear game session
        self._state.game_session = None
