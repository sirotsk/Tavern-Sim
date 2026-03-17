"""
PatronAgent — wraps a single patron's stateful Gemini chat session.

Each patron gets their own client.chats.create() Chat object.
The Chat object IS the conversation history — no manual tracking needed.
AgentManager holds one PatronAgent per patron talked to during the session.

NEVER use safe_generate() for patron turns — it is stateless.
ALWAYS use chat.send_message() via the _safe_send() helper.
"""
import re

from agents.base_agent import client, SAFETY_CONFIG
from google.genai import types


class PatronAgent:
    """Wraps a single patron's stateful Gemini chat session.

    Each instance holds an isolated client.chats.create() Chat object.
    The Chat object accumulates conversation history automatically — no
    separate message list is maintained here.

    NPC-03 guarantee: two PatronAgent instances cannot share a Chat object;
    each creates its own via client.chats.create().
    """

    def __init__(
        self,
        profile: dict,
        tavern_data: dict,
        player_name: str,
        model_name: str,
    ) -> None:
        """Create a PatronAgent with an isolated Gemini chat session.

        Args:
            profile: Patron profile dict (from agent_profiles/patron_XXX.json).
            tavern_data: Full tavern data dict (from agent_profiles/tavern.json).
            player_name: Player's name if already known, empty string otherwise.
            model_name: Gemini model name from config["model"]["name"].
        """
        self._profile = profile
        self._model_name = model_name
        self._player_name = player_name
        self._exchange_count = 0

        system_prompt = self._build_system_prompt(profile, tavern_data, player_name)

        # Create the isolated chat session — this Chat object IS the history store.
        # Do NOT create new sessions mid-conversation; do NOT share across patrons.
        self._chat = client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                safety_settings=SAFETY_CONFIG.safety_settings,
            ),
        )

    def _build_system_prompt(
        self, profile: dict, tavern_data: dict, player_name: str
    ) -> str:
        """Build a behavioral (not adjectival) system prompt for this patron.

        The prompt defines WHO this character is through concrete behavior rules,
        not lists of adjectives. Each section drives specific speech/reaction patterns.
        """
        identity = profile.get("identity", {})
        personality = profile.get("personality", {})
        backstory = profile.get("backstory", {})
        tavern_name = tavern_data.get("tavern_name", "this tavern")

        name = identity.get("name", "Unknown")
        age = identity.get("age", "unknown")
        role = identity.get("role", "person")

        traits = personality.get("traits", [])
        speaking_style = personality.get("speaking_style", "")
        mood = personality.get("mood", "neutral")
        quirks = personality.get("quirks", [])
        likes = personality.get("likes", [])
        dislikes = personality.get("dislikes", [])

        traits_str = ", ".join(traits) if traits else "unremarkable"
        quirks_str = "; ".join(quirks) if quirks else "none in particular"
        likes_str = ", ".join(likes) if likes else "the usual things"
        dislikes_str = ", ".join(dislikes) if dislikes else "rudeness and waste"

        history = backstory.get("history", "")
        reason_at_tavern = backstory.get("reason_at_tavern", "")

        # Cross-patron awareness — other brief descriptions from tavern data
        patron_briefs = tavern_data.get("patron_briefs", [])
        if patron_briefs:
            others_text = "You can see the other people in the tavern: " + "; ".join(
                patron_briefs
            )
        else:
            others_text = (
                "There are several other patrons in the tavern around you — "
                "you notice them but have not spoken to them tonight."
            )

        # Player name injection — only include if the player has introduced themselves
        if player_name and player_name.strip():
            name_line = (
                f"The player has previously introduced themselves; "
                f"their name is: {player_name}. Use it going forward."
            )
        else:
            name_line = (
                "You do NOT know the player's name yet. "
                "Address them generically ('stranger', 'friend', 'lad', 'lass' — "
                "whichever fits your personality and their apparent demeanor). "
                "Once they tell you their name, use it going forward."
            )

        prompt = f"""You are {name}, a {age}-year-old {role} in a medieval English tavern called {tavern_name}.

SETTING: England, 1350s. You are an ordinary person of your time. No magic, no fantasy elements. You have never heard of anything from after 1400 AD. If someone mentions something you don't recognize, assume it is a wizard's trick, foreign nonsense, or a jest.

YOUR PERSONALITY:
- Traits: {traits_str}
- How you speak: {speaking_style}
- Behavioral quirks: {quirks_str}
- Current mood: {mood}
- Things you like ({likes_str}): your tone warms and you engage more freely when these come up.
- Things you dislike ({dislikes_str}): your tone cools, you may show irritation or impatience.

YOUR STORY:
- History: {history}
- Why you are here tonight: {reason_at_tavern}

TAVERN AWARENESS:
{others_text}

CONVERSATION RULES:
1. Stay in character as {name}. Never break the 1350s England fiction under any circumstances.
2. Dialogue CONTENT is in first person ("I have been working the quarry..."). Dialogue ATTRIBUTION and tags use third person with your name ({name} says, {name} mutters, {name} asks — NEVER "I say" or "I question"). Physical actions and gestures are in THIRD PERSON using your name ("*{name} scratches his beard*", "*{name} leans back*"). Never use first person for action beats or dialogue tags.
3. Topics you know well: speak with confidence. Topics outside your expertise: limited knowledge or honest ignorance.
4. If the player is persistently rude or annoying, your patience wears thin. You may warn them or refuse to continue.
5. When performing a physical action, describe it in italics using your name in third person: *{name} rubs a calloused thumb* "Aye, that's the way of it." NEVER write actions as *I rub my thumb* — always *{name} rubs a calloused thumb*.
6. {name_line}
7. Do NOT prefix your responses with your own name — the game displays your name separately.
8. Keep responses appropriate for your personality. Reserved characters: 1-3 sentences. Storytellers or talkers: can be longer, but do not ramble without cause.
9. If the player's speech seems garbled, slurred, or confused, react naturally as a medieval person would — perhaps with concern, amusement, or annoyance depending on your personality.
10. You are in a crowded tavern — background noise, interruptions, and distractions are normal. React to them occasionally.
"""
        return prompt

    def _safe_send(self, message: str) -> str:
        """Central send method. All conversation turns route through here.

        Uses chat.send_message() to maintain history, with a safety block fallback.
        Never let a safety block crash the game — return a neutral in-character silence.
        """
        response = self._chat.send_message(message)
        candidate = response.candidates[0] if response.candidates else None
        if candidate and str(candidate.finish_reason) == "FinishReason.SAFETY":
            return "[They fall silent, their expression unreadable.]"
        return response.text or ""

    def send(self, player_input: str) -> str:
        """Send a player message and get the patron's response.

        Increments the exchange counter and routes through _safe_send().

        Args:
            player_input: The player's typed message.

        Returns:
            The patron's in-character response text.
        """
        self._exchange_count += 1
        return self._safe_send(player_input)

    def send_with_gift_check(self, player_input: str) -> tuple:
        """Send message and check if patron wants to give an item or gold.

        Augments the player message with an optional gift-signal instruction.
        Parses the response for inline markers {{GIFT:name:description}} or {{GOLD:amount}}.
        Strips markers from the displayed response text.

        Args:
            player_input: The player's message (may include garble/tier context).

        Returns:
            Tuple of (response_text: str, gift: dict | None).
            gift format: {"type": "item", "name": str, "description": str}
                      or {"type": "gold", "amount": int}
                      or None
        """
        # Append gift-signal instruction as system context (not visible to player)
        augmented = (
            player_input +
            "\n\n[SYSTEM: If, based on the natural flow of this conversation, your character "
            "would spontaneously give the player a small item or reward them with gold coins "
            "right now, include a gift block at the very END of your response in this exact "
            "format:\n"
            "{{GIFT:item_name:2-3 sentence item description}} or {{GOLD:amount}}\n"
            "Only include this if it genuinely fits the moment and your character's personality. "
            "Most responses will NOT include a gift. Do not force it.]"
        )

        self._exchange_count += 1
        response_text = self._safe_send(augmented)

        # Parse gift markers from response (search entire text, not just end)
        gift = None

        # Check for item gift
        gift_match = re.search(r'\{\{GIFT:([^:]+):([^}]+)\}\}', response_text)
        if gift_match:
            gift = {
                "type": "item",
                "name": gift_match.group(1).strip(),
                "description": gift_match.group(2).strip(),
            }
            # Strip the marker from displayed text
            response_text = response_text[:gift_match.start()].rstrip() + response_text[gift_match.end():].lstrip()
            response_text = response_text.strip()

        # Check for gold gift (only if no item gift found)
        if gift is None:
            gold_match = re.search(r'\{\{GOLD:(\d+)\}\}', response_text)
            if gold_match:
                gift = {
                    "type": "gold",
                    "amount": int(gold_match.group(1)),
                }
                response_text = response_text[:gold_match.start()].rstrip() + response_text[gold_match.end():].lstrip()
                response_text = response_text.strip()

        # Safety: strip any remaining marker fragments that didn't parse cleanly
        # This catches malformed markers like {{GIFT:...} (missing closing brace)
        response_text = re.sub(r'\{\{(?:GIFT|GOLD)[^}]*\}\}', '', response_text).strip()

        return (response_text, gift)

    def greeting(self, is_resuming: bool = False) -> str:
        """Generate an opening greeting when the player approaches this patron.

        Args:
            is_resuming: True if the player is returning to a previously started
                         conversation. The patron will reference earlier discussion.

        Returns:
            The patron's in-character greeting.
        """
        if is_resuming:
            prompt = (
                "[The player has returned to continue the conversation. "
                "Greet them, referencing what you discussed before.]"
            )
        else:
            prompt = (
                "[A stranger has just approached you in the tavern. "
                "Greet them in character — stay true to your personality. "
                "Some characters are welcoming, others are suspicious or annoyed "
                "at being interrupted.]"
            )
        return self._safe_send(prompt)

    def farewell(self) -> str:
        """Generate an in-character farewell when the player walks away.

        Returns:
            A brief 1-2 sentence farewell true to the patron's personality.
        """
        prompt = (
            "[The player is ending the conversation and walking away. "
            "Give a brief in-character farewell — 1-2 sentences max. "
            "Stay true to your personality.]"
        )
        return self._safe_send(prompt)

    def mid_conversation_reaction(self, attempted_command: str) -> str:
        """React when the player issues a non-talk command while in conversation.

        Used to give immersive feedback when the player tries to do something
        else (like 'look' or 'status') while talking to an NPC.

        Args:
            attempted_command: The command the player tried to use.

        Returns:
            A brief 1-sentence in-character reaction (annoyed, amused, confused).
        """
        prompt = (
            f"[The player seems distracted and mutters something about "
            f"'{attempted_command}' instead of talking to you. "
            f"React briefly in character — you might be annoyed, amused, or confused. "
            f"1 sentence.]"
        )
        return self._safe_send(prompt)

    def get_exchange_count(self) -> int:
        """Return the number of conversation turns completed with this patron."""
        return self._exchange_count

    def get_name(self) -> str:
        """Return this patron's name from their profile."""
        return self._profile["identity"]["name"]
