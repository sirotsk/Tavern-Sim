"""
BarkeepAgent — extends PatronAgent with drink/food ordering capability.

The barkeep is a dual-role NPC: fully talkable like a patron AND serves orders.
Same isolated Gemini Chat session handles both conversation and order responses.
Menu data comes from the tavern template (stored in tavern.json -> template -> menu).
"""
import random

from agents.patron_agent import PatronAgent


class BarkeepAgent(PatronAgent):
    """Extends PatronAgent with menu-aware ordering capability.

    The barkeep participates in conversation via inherited send()/greeting()/farewell()
    AND can serve orders via resolve_order() and order().

    The same Gemini Chat session handles both — a barkeep response to an order is just
    another chat.send_message() call with an in-character prompt, preserving full
    conversation context across both conversation and order interactions.
    """

    def __init__(
        self,
        profile: dict,
        tavern_data: dict,
        player_name: str,
        model_name: str,
    ) -> None:
        """Create a BarkeepAgent with menu data and order tracking.

        Args:
            profile: Barkeep profile dict (from agent_profiles/barkeep.json).
            tavern_data: Full tavern data dict (tavern.json) — includes template.menu.
            player_name: Player's name if known, empty string otherwise.
            model_name: Gemini model name from config["model"]["name"].
        """
        # PatronAgent.__init__ creates the chat session with our overridden prompt
        super().__init__(profile, tavern_data, player_name, model_name)

        # Extract menu from session-generated subset (falls back to full template menu for old saves)
        self._menu = tavern_data.get("menu_subset") or tavern_data.get("template", {}).get(
            "menu", {"drinks": [], "food": []}
        )
        self._orders: list[dict] = []   # All items ordered this session
        self._tab_total: int = 0        # Total number of items served

    def _build_system_prompt(
        self, profile: dict, tavern_data: dict, player_name: str
    ) -> str:
        """Build barkeep system prompt — base PatronAgent prompt plus barkeep role section."""
        base_prompt = super()._build_system_prompt(profile, tavern_data, player_name)

        # Extract drink and food names for in-prompt menu awareness (session subset takes priority)
        menu = tavern_data.get("menu_subset") or tavern_data.get("template", {}).get("menu", {"drinks": [], "food": []})
        drink_names = ", ".join(
            item["name"] for item in menu.get("drinks", [])
        ) or "various ales"
        food_names = ", ".join(
            item["name"] for item in menu.get("food", [])
        ) or "bread and stew"

        barkeep_section = f"""
BARKEEP ROLE:
- You are the barkeep of this tavern. You serve drinks and food as part of your role.
- You know the menu by heart. Drinks available: {drink_names}. Food available: {food_names}.
- You keep a running tab on what patrons order. Comment on a growing tab if it gets large.
- You remember what each patron has ordered: "Another ale? That's your third tonight."
- When someone orders something not on the menu, suggest an alternative from what you do have.
- You are occasionally busy — you might be wiping the bar or attending to something when approached.
- Serve orders without breaking stride. A brief in-character comment accompanies each order.
- Do not break 1350s fiction even when serving — use period-appropriate language for drinks and food.
"""
        return base_prompt + barkeep_section

    def resolve_order(self, item_request: str) -> tuple:
        """Attempt to match an order request to a menu item.

        Uses a three-tier matching strategy:
        1. Exact bidirectional substring (original behavior — handles 'order ale')
        2. Word-token overlap (handles 'red wine' matching 'Red wine' and
           'fish stew' matching 'Fish stew' even in longer phrases)
        3. Single significant word match (handles 'mead' in 'give me some mead please')

        Args:
            item_request: The player's raw order string (e.g. "an ale", "some red wine").

        Returns:
            Tuple of (matched_item_dict | None, matched_name: str).
            If no match: (None, "").
        """
        request_lower = item_request.strip().lower()
        all_items = self._menu.get("drinks", []) + self._menu.get("food", [])

        # Common filler words to ignore when tokenizing natural language
        stop_words = frozenset({
            "a", "an", "the", "some", "of", "me", "i", "my",
            "please", "one", "have", "get", "give", "bring",
            "pour", "ill", "i'll", "i'd", "id", "like", "want",
            "can", "could", "would", "more", "another",
        })

        request_tokens = set(request_lower.split()) - stop_words

        # Tier 1: Exact bidirectional substring (backward compatible)
        for item in all_items:
            item_name_lower = item["name"].lower()
            if item_name_lower in request_lower or request_lower in item_name_lower:
                return (item, item["name"])

        # Tier 2: All item-name tokens appear in the request
        # e.g., "Red wine" tokens {"red", "wine"} both in "I'll have some red wine please"
        best_match = None
        best_token_count = 0
        for item in all_items:
            item_name_lower = item["name"].lower()
            item_tokens = set(item_name_lower.split()) - stop_words
            if item_tokens and item_tokens.issubset(request_tokens):
                # Prefer the match with the most tokens (more specific match wins)
                if len(item_tokens) > best_token_count:
                    best_match = item
                    best_token_count = len(item_tokens)

        if best_match is not None:
            return (best_match, best_match["name"])

        # Tier 3: Single significant word match (for short item names like 'Ale', 'Mead')
        # Only matches if exactly one menu item shares a significant word with the request
        single_matches = []
        for item in all_items:
            item_name_lower = item["name"].lower()
            item_tokens = set(item_name_lower.split()) - stop_words
            if item_tokens & request_tokens:
                single_matches.append(item)

        if len(single_matches) == 1:
            return (single_matches[0], single_matches[0]["name"])

        return (None, "")

    def order(self, item_request: str, in_conversation: bool = False) -> tuple:
        """Process an order request and generate an in-character serving response.

        Resolves the request against the menu, tracks the tab, and generates a
        contextual in-character response via the shared chat session.

        Args:
            item_request: The player's order string.
            in_conversation: Unused — reserved for future context hints.

        Returns:
            Tuple of (response_text: str, drunkenness_delta: int).
            drunkenness_delta is positive for drinks, negative for food, 0 for unknown items.
        """
        item, matched_name = self.resolve_order(item_request)

        if item is None:
            # Item not on menu — ask barkeep to suggest an alternative in character
            drink_names = ", ".join(
                i["name"] for i in self._menu.get("drinks", [])
            ) or "nothing special"
            food_names = ", ".join(
                i["name"] for i in self._menu.get("food", [])
            ) or "nothing special"
            prompt = (
                f"[A patron asked for '{item_request}'. That is not on your menu. "
                f"Suggest an alternative in character. "
                f"Your available drinks: {drink_names}. "
                f"Your available food: {food_names}.]"
            )
            return (self._safe_send(prompt), 0)

        # Item found — track in orders and tab
        self._orders.append(item)
        self._tab_total += 1
        drunkenness_delta = item.get("drunkenness_modifier", 0)

        # Count how many times this specific item was ordered
        order_count_for_item = sum(
            1 for o in self._orders if o["name"] == matched_name
        )

        # Build contextual order prompt
        prompt = f"[A patron ordered: {matched_name}. Serve it in character.]"

        if self._tab_total >= 5:
            prompt += (
                f" [Tab note: this is their {self._tab_total}th order total "
                f"— comment briefly on the growing tab.]"
            )

        if order_count_for_item > 1:
            prompt += (
                f" [Note: this is their {order_count_for_item}th {matched_name} "
                f"— acknowledge this.]"
            )

        # ~15% chance of a busy-barkeep flavor delay
        if random.random() < 0.15:
            prompt += (
                " [You're briefly occupied — add a sentence of flavor delay "
                "before serving.]"
            )

        return (self._safe_send(prompt), drunkenness_delta)

    def refuse_order_insufficient_funds(self, item_request: str, cost: int, current_gold: int) -> str:
        """Generate in-character refusal when player can't afford an item.

        Args:
            item_request: The item the player tried to order.
            cost: The cost of the item in gold.
            current_gold: How much gold the player currently has.

        Returns:
            An in-character refusal response string.
        """
        prompt = (
            f"[A patron tried to order '{item_request}' which costs {cost} gold, "
            f"but they only have {current_gold} gold. Refuse the order in character "
            f"— you might be sympathetic, blunt, or amused depending on your mood. "
            f"1-2 sentences.]"
        )
        return self._safe_send(prompt)

    def get_shop_text(self, shop_items: list) -> str:
        """Format the tavern's shop trinkets for display with prices."""
        if not shop_items:
            return "The barkeep shakes their head. 'Nothing left to sell, I'm afraid.'"
        lines = ["Wares for sale:"]
        for item in shop_items:
            price = item.get("price", 0)
            lines.append(f"  {item['name']} — {price} gold")
        lines.append("\nType 'buy [item]' to purchase.")
        return "\n".join(lines)

    def buy_item(self, item_name: str, cost: int) -> str:
        """Generate in-character sale acknowledgment when player buys a shop item."""
        prompt = (
            f"[A patron just purchased '{item_name}' for {cost} gold. "
            f"Acknowledge the sale in character — hand them the item with a brief comment. "
            f"1-2 sentences.]"
        )
        return self._safe_send(prompt)

    def get_menu_text(self) -> str:
        """Format the tavern menu for display with prices.

        Returns:
            A formatted string with Drinks and Fare sections, one item per line,
            each item showing its gold cost.
        """
        lines = []

        drinks = self._menu.get("drinks", [])
        if drinks:
            lines.append("Drinks:")
            for item in drinks:
                cost = item.get("cost", 0)
                price_str = f" — {cost} gold" if cost > 0 else ""
                desc = item.get("description", "")
                if desc:
                    lines.append(f"  {item['name']}{price_str} - {desc}")
                else:
                    lines.append(f"  {item['name']}{price_str}")

        food = self._menu.get("food", [])
        if food:
            lines.append("Fare:")
            for item in food:
                cost = item.get("cost", 0)
                price_str = f" — {cost} gold" if cost > 0 else ""
                desc = item.get("description", "")
                if desc:
                    lines.append(f"  {item['name']}{price_str} - {desc}")
                else:
                    lines.append(f"  {item['name']}{price_str}")

        return "\n".join(lines) if lines else "The barkeep has nothing to offer."
