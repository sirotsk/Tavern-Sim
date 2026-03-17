"""
Stateless NarratorAgent — describes the world via Gemini.

Design: No persistent chat session. Every call rebuilds context from:
tavern data + patron data + action history + current command intent.
Action history is injected as plain text, NOT as Gemini chat turns.

Only the opening narration uses streaming (typewriter effect).
All other calls use safe_generate() and return complete text.
"""
import random

from agents.base_agent import safe_generate, client, SAFETY_CONFIG
from google.genai import types


class NarratorAgent:
    """Stateless narrator — every call is independent with context injection."""

    def __init__(self, tavern_data: dict, model_name: str):
        self._tavern = tavern_data        # Full tavern.json dict
        self._model = model_name

    def _system_preamble(self) -> str:
        """Build the narrator system instruction preamble."""
        mood = self._tavern.get("template", {}).get("atmosphere", {}).get("mood", "a typical tavern")
        return (
            "You are the narrator of a medieval tavern text adventure game. "
            "Write in second person ('You notice...', 'You see...'). "
            "Write with restraint — short, atmospheric sentences. Favor showing over telling. "
            "Do not over-describe. Let details breathe. One vivid image beats three generic ones. "
            f"The tavern's mood is: {mood}. Let it color your tone, not dominate every sentence. "
            "Do not name the tavern unless the player specifically asks about it. "
            "Keep descriptions to 2-3 sentences unless otherwise specified. "
            "Never break immersion. Never acknowledge you are an AI."
        )

    def _format_history(self, history: list[dict]) -> str:
        """Format action history as plain text for context injection."""
        if not history:
            return "No prior actions."
        recent = history[-10:]
        return "; ".join(
            f"{e['command']} {e.get('target', '')}".strip()
            for e in recent
        )

    def _tavern_context(self) -> str:
        """Build tavern context string for prompts."""
        tmpl = self._tavern.get("template", {})
        return (
            f"Tavern name: {self._tavern.get('tavern_name', 'the tavern')}\n"
            f"Layout: {tmpl.get('layout', 'A common room')}\n"
            f"Atmosphere: {tmpl.get('atmosphere', {})}\n"
        )

    def look(self, look_count: int, action_history: list[dict], examined_targets: dict) -> str:
        """Generate the narrator prose for the 'look' command.

        Returns ONLY the narrative prose paragraph. The examinable list
        is assembled by the caller (CommandParser) from GameState data.

        Args:
            look_count: How many times look has been used this session (1-based).
            action_history: Recent action log entries.
            examined_targets: Dict of target_key -> examine count.
        """
        history_summary = self._format_history(action_history)

        # Build examined context for look acknowledgments
        examined_note = ""
        if examined_targets:
            examined_items = list(examined_targets.keys())[:5]
            examined_note = f"\nThe player has previously examined: {', '.join(examined_items)}. Acknowledge 1-2 of these naturally in the scene description."

        escalation = ""
        if look_count == 1:
            escalation = "This is the player's first look around. Describe the scene fully."
        elif look_count == 2:
            escalation = "The player is looking around again. Describe from a slightly different angle or notice a new detail."
        else:
            escalation = (
                f"The player has looked around {look_count} times now. "
                "Show mild narrator irritation or humor — 'You survey the room AGAIN...' "
                "while still providing a fresh angle."
            )

        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"Player action history: {history_summary}\n"
            f"{examined_note}\n\n"
            f"{escalation}\n"
            "Write a 2-3 sentence description of the tavern scene. "
            "Do NOT list specific people or objects — just describe the overall atmosphere and scene."
        )
        return safe_generate(self._model, prompt)

    def examine(self, target_type: str, target_data: dict, examine_count: int, action_history: list[dict], talked_to: bool = True) -> str:
        """Generate narrator description for examining a target.

        Args:
            target_type: "patron" or "object"
            target_data: The full data dict for the target (patron profile or examinable object)
            examine_count: How many times this specific target has been examined (1-based)
            action_history: Recent action log entries.
            talked_to: Whether the player has spoken to this person. When False, the
                       narrator hides the person's name and refers to them by appearance only.
                       Defaults to True for backward compatibility and for object targets.
        """
        history_summary = self._format_history(action_history)

        if target_type == "patron":
            # Name-hiding instruction when player hasn't spoken to this person
            name_instruction = ""
            if not talked_to:
                name_instruction = (
                    "\nIMPORTANT: The player has NOT spoken to this person yet. "
                    "Do NOT reveal their name under any circumstances — refer to them "
                    "ONLY by their appearance (e.g., 'the broad-shouldered man', 'the figure'). "
                    "If the data below contains a name, ignore it completely."
                )

            base_desc = target_data.get("description", target_data.get("appearance", {}).get("description", "A figure sits nearby."))
            escalation = ""
            if examine_count == 1:
                escalation = f"Base description to build on: {base_desc}\nProvide the full description and add one embellishment sentence based on what they might be doing right now."
            elif examine_count == 2:
                escalation = f"Base description: {base_desc}\nThe player is examining this patron again. Start with 'You look again...' and add a new detail not mentioned before."
            else:
                escalation = f"Base description: {base_desc}\nThe player has examined this patron {examine_count} times. Show narrator personality — mild annoyance or humor about the player's fixation."

            prompt = (
                f"{self._system_preamble()}\n\n"
                f"{self._tavern_context()}\n"
                f"Player action history: {history_summary}\n\n"
                f"The player examines a patron.\n"
                f"{name_instruction}\n"
                f"{escalation}\n"
                "Write 2-4 sentences."
            )
        else:
            # Object examination
            obj_name = target_data.get("name", "something")
            obj_detailed = target_data.get("detailed", "You see nothing remarkable.")

            escalation = ""
            if examine_count == 1:
                escalation = f"Detailed description to elaborate on: {obj_detailed}\nExpand on this with atmospheric detail."
            elif examine_count == 2:
                escalation = f"Object description: {obj_detailed}\nThe player examines this again. Start with 'You look more closely...' and add a new sensory detail."
            else:
                escalation = f"Object description: {obj_detailed}\nThe player has examined '{obj_name}' {examine_count} times. Show narrator personality — gentle exasperation or sardonic humor."

            prompt = (
                f"{self._system_preamble()}\n\n"
                f"{self._tavern_context()}\n"
                f"Player action history: {history_summary}\n\n"
                f"The player examines: {obj_name}\n"
                f"{escalation}\n"
                "Write 2-3 sentences."
            )

        return safe_generate(self._model, prompt)

    def invalid_examine(self, target_str: str) -> str:
        """Generate an in-world response for an invalid examine target."""
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"The player tried to examine '{target_str}' but nothing matching that description exists in the tavern.\n"
            "Write a brief in-world response (1-2 sentences). Example tone: 'You squint around the tavern, but nothing matching that description catches your eye...'"
        )
        return safe_generate(self._model, prompt)

    def ambiguous_examine(self, target_str: str, candidates: list[str]) -> str:
        """Generate narrator clarification when examine target is ambiguous."""
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"The player tried to examine '{target_str}' but it could match several things: {', '.join(candidates)}.\n"
            "Write a brief in-world response asking for clarification (1-2 sentences). "
            "Example tone: 'Your gaze drifts between several things. Which do you mean?'"
        )
        return safe_generate(self._model, prompt)

    def stream_opening(self, patron_briefs: list[str], barkeep_brief: str) -> str:
        """Stream the opening narration to terminal. Returns the full text for logging.

        Uses generate_content_stream() for typewriter effect.
        Only the opening narration streams — all other narrator output is instant.
        """
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"Patrons present (describe by appearance only, never by name): {patron_briefs}\n"
            f"Barkeep appearance: {barkeep_brief}\n\n"
            "Write the opening narration: one flowing paragraph describing the tavern "
            "and its occupants as seen through the player's eyes upon entry. "
            "Mention each patron briefly by their appearance. The barkeep is part of "
            "the scenery, not called out by name. "
            "Describe the atmosphere using the tavern's mood. "
            "End with a sense of invitation — the player is here, now what?"
        )

        config = types.GenerateContentConfig(
            safety_settings=SAFETY_CONFIG.safety_settings,
        )

        full_text = []
        output_produced = False
        try:
            for chunk in client.models.generate_content_stream(
                model=self._model,
                contents=prompt,
                config=config,
            ):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    full_text.append(chunk.text)
                    output_produced = True
        except Exception:
            pass  # Stream interrupted — fall through to fallback

        print()  # Final newline

        if not output_produced:
            fallback = "You step through the door into a haze of smoke and warm light. The tavern stretches before you, alive with murmur and movement."
            print(fallback)
            return fallback

        return "".join(full_text)

    def get_opening_sections(self, patron_briefs: list[str], barkeep_brief: str) -> list[str]:
        """Return opening narration as a list of sections for paced web display.

        Unlike stream_opening(), this method does NOT print anything.
        Returns 3 sections: [tavern_description, patron_descriptions, invitation].

        Args:
            patron_briefs: List of patron brief appearance descriptions.
            barkeep_brief: Barkeep brief appearance description.

        Returns:
            List of 3 strings, one per section.
        """
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"Patrons present (describe by appearance only, never by name): {patron_briefs}\n"
            f"Barkeep appearance: {barkeep_brief}\n\n"
            "Write the opening narration in EXACTLY 3 paragraphs separated by blank lines:\n"
            "1. The tavern itself — what the player sees and feels upon entry (atmosphere, layout, lighting)\n"
            "2. The people — brief mentions of each patron by appearance and the barkeep\n"
            "3. The invitation — a sense that the player is here, now what? End with an inviting line.\n\n"
            "Keep each paragraph 2-3 sentences. Do not name any patrons."
        )
        result = safe_generate(self._model, prompt)
        if not result:
            return [
                "You step through the door into a haze of smoke and warm light.",
                "Several figures populate the room, each absorbed in their own business.",
                "The tavern stretches before you, alive with murmur and movement.",
            ]

        # Split on double-newline to get sections
        sections = [s.strip() for s in result.split("\n\n") if s.strip()]
        # Ensure exactly 3 sections (pad or join extras)
        if len(sections) < 3:
            while len(sections) < 3:
                sections.append("")
        elif len(sections) > 3:
            # Join extras into the last section
            sections = sections[:2] + ["\n\n".join(sections[2:])]
        return sections

    def invalid_command(self, raw_input: str) -> str:
        """Generate an in-world response for an unrecognized command."""
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"The player typed: '{raw_input}'\n"
            "This is not a recognized command. Write a brief in-world response (1 sentence). "
            "The narrator should gently acknowledge the player is confused or mumbling. "
            "Example tones: 'You mumble something unintelligible...', 'The words die on your lips...', "
            "'You think better of it and say nothing.'"
        )
        return safe_generate(self._model, prompt)

    def farewell(self) -> str:
        """Generate a narrator farewell line for the quit command."""
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            "The player is leaving the tavern. Write a brief farewell (1-2 sentences). "
            "Atmospheric and final — the narrator bids the traveler goodbye."
        )
        return safe_generate(self._model, prompt)

    def save_confirmation(self) -> str:
        """Return a random in-world flavor line for /save confirmation.

        Static pool -- no Gemini call. Save must be near-instant.
        """
        lines = [
            "The barkeep nods knowingly, as if this moment is worth remembering.",
            "A quiet stillness settles over the tavern, as though time itself pauses to take note.",
            "The candle on your table flickers and holds steady -- a small anchor in the evening.",
            "Somewhere in the back, a quill scratches across parchment. Your story is being written.",
            "The old clock on the wall ticks once, deliberately, as if marking this moment.",
            "A draft catches the tavern door, holding it open for just a breath longer than usual.",
            "The barkeep polishes a glass slowly, watching you with an expression that says: I'll remember.",
            "The fire crackles and settles, banking its embers for later.",
        ]
        return random.choice(lines)

    def approach_patron(self, patron_record, is_resuming: bool, action_history: list[dict]) -> str:
        """Generate narrator text for the player approaching a patron.

        Args:
            patron_record: The PatronRecord for the patron being approached.
            is_resuming: True if the player has spoken to this patron before.
            action_history: Recent action log entries (last 10).

        Returns:
            1-2 sentence narrator description of the approach.
        """
        history_summary = self._format_history(action_history)

        if is_resuming:
            prompt = (
                f"{self._system_preamble()}\n\n"
                f"{self._tavern_context()}\n"
                f"Player action history: {history_summary}\n\n"
                f"The player walks back over to {patron_record.name}. "
                "Write 1-2 sentences describing the player's approach — they've spoken before. "
                "Tone: casual return, not a first meeting."
            )
        else:
            prompt = (
                f"{self._system_preamble()}\n\n"
                f"{self._tavern_context()}\n"
                f"Player action history: {history_summary}\n\n"
                f"The player approaches {patron_record.brief_description}. "
                "Write 1-2 sentences describing the player walking up to this person for the first time. "
                "Build brief anticipation."
            )

        return safe_generate(self._model, prompt)

    def stepping_away(self, patron_name: str) -> str:
        """Generate narrator text for the player stepping away after ending a conversation.

        Args:
            patron_name: The name of the patron the player just finished talking to.

        Returns:
            1 sentence narrator description of stepping away.
        """
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"The player steps away from {patron_name}. "
            "Write 1 sentence describing this in the narrator's voice."
        )
        return safe_generate(self._model, prompt)

    def invalid_talk_target(self, target_str: str) -> str:
        """Generate an in-world response when the player tries to talk to a non-existent person.

        Args:
            target_str: What the player tried to talk to.

        Returns:
            1-2 sentence in-world narrator response.
        """
        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"The player tried to talk to '{target_str}' but no one matching that description "
            "is in the tavern. Write 1-2 sentences — in-world response. "
            "Example tone: 'You look around but see no one by that description.'"
        )
        return safe_generate(self._model, prompt)

    def generate_live_ambient(self, action_history: list[dict]) -> str:
        """Generate a context-aware ambient text line based on the full session history.

        Used occasionally instead of the pre-seeded pool, for ambient text
        that references the player's specific actions.
        """
        if not action_history:
            return ""

        history_text = "; ".join(
            f"{e['command']} {e.get('target', '')}".strip()
            for e in action_history
        )

        prompt = (
            f"{self._system_preamble()}\n\n"
            f"{self._tavern_context()}\n"
            f"Full session action history: {history_text}\n\n"
            "Write ONE ambient flavor text sentence (10-20 words) that subtly references "
            "the player's recent actions or patterns. The text should feel like a natural "
            "observation in the tavern — not addressed to the player directly. "
            "Examples of referencing patterns: if the player has been examining one patron "
            "repeatedly, a nearby patron might glance nervously; if the player keeps looking "
            "around, the barkeep might raise an eyebrow."
        )
        return safe_generate(self._model, prompt)

    # --- Phase 4: Drunkenness tier transition and pass-out methods ---

    # Hardcoded transition lines to avoid an API call on every drink order.
    _TIER_UP_LINES = {
        1: [
            "A warm glow settles behind your eyes.",
            "The ale takes hold — a pleasant warmth spreads through you.",
            "You feel pleasantly light-headed.",
        ],
        2: [
            "The room seems to tilt agreeably.",
            "The edges of the world have gone soft and golden.",
            "Everything feels a touch... loose.",
        ],
        3: [
            "The floor lurches beneath you — or was that you?",
            "The world has taken on a decidedly unsteady quality.",
            "Your thoughts scatter like startled pigeons.",
        ],
        4: [
            "The tavern dissolves into a whirl of noise and firelight.",
            "You can barely feel your face. The saints themselves seem to spin.",
            "Reality has become a distant suggestion.",
        ],
    }

    _TIER_DOWN_LINES = {
        0: [
            "The room steadies. Your head clears.",
            "Sobriety returns like cold water.",
            "The world snaps back into sharp focus.",
        ],
        1: [
            "The fog lifts a little. You can feel your fingers again.",
            "The food settles your stomach. Things are less... wavy.",
            "A measure of clarity returns.",
        ],
        2: [
            "The worst of it passes, though the room still sways.",
            "You feel slightly less like the floor is moving.",
            "The food helps. A bit.",
        ],
        3: [
            "The room is still spinning, but perhaps a touch slower.",
            "You feel a fraction more present. Not much, but some.",
            "The haze thins — just barely.",
        ],
    }

    def tier_transition(self, old_tier: int, new_tier: int) -> str:
        """Return a hardcoded narrative line for a drunkenness tier change.

        Uses hardcoded line pools (no API call) to avoid latency on every
        drink order. Returns a random line from the appropriate pool.

        Args:
            old_tier: The previous drunkenness tier (0-4).
            new_tier: The new drunkenness tier (0-4).

        Returns:
            A narrative line describing the transition, or empty string if
            no transition (same tier or tier change not in dict).
        """
        if new_tier == old_tier:
            return ""

        if new_tier > old_tier:
            lines = self._TIER_UP_LINES.get(new_tier)
        else:
            lines = self._TIER_DOWN_LINES.get(new_tier)

        if not lines:
            return ""

        return random.choice(lines)

    def pass_out_and_wake(self) -> str:
        """Generate a Gemini narrative for the player passing out and waking up.

        Used when the player hits the pass-out threshold mid-session — they
        collapse dramatically, then wake moments later on the tavern floor.
        The session continues after this event.

        Returns:
            2-3 sentence description of the pass-out and wake-up.
        """
        prompt = (
            "The player has drunk themselves unconscious in a 1350s English tavern. "
            "Write 2-3 sentences: first describe them collapsing dramatically and comedically "
            "(this is a payoff moment — make it memorable), then describe them waking up on "
            "the tavern floor moments later. End with them groggily getting up. "
            "The tone is medieval pub comedy, not grim. "
            "Example ending: 'You peel yourself off the floor, tasting sawdust and regret.'"
        )
        return safe_generate(self._model, prompt)

    def pass_out_finale(self) -> str:
        """Generate a Gemini narrative for the player's final drunken collapse (game over).

        Used when the player reaches maximum drunkenness — this ends the session.
        This is the game over screen — make it memorable.

        Returns:
            3-4 sentence dramatic and comedic description of the final collapse.
        """
        prompt = (
            "The player has drunk themselves into complete oblivion in a 1350s English tavern. "
            "This is the end of the game. Write 3-4 sentences: a dramatic, comedic description "
            "of the player's final collapse. The narrator bids farewell with dark humor. "
            "This is the game over screen — make it memorable. "
            "End with something like the world going dark or the player being carried out."
        )
        return safe_generate(self._model, prompt)
