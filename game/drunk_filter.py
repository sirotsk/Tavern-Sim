"""
Drunkenness filter — tier classification and speech garbling.

This module is the core of the drunkenness mechanic. It maps drunkenness
integer values to tiers 0-4 and garbles player speech accordingly.

Tier 0 (0-10):   Clear-headed — no garbling
Tier 1 (11-20):  Merry — light rule-based garbling
Tier 2 (21-30):  In his cups — moderate rule-based garbling
Tier 3 (31-40):  Three sheets to the wind — Gemini AI garbling (heavy)
Tier 4 (41+):    Gone to the saints — Gemini AI garbling (near total)

Design: No class — just functions and constants. safe_generate() is
imported inside _garble_gemini() only to avoid circular imports at
module level (base_agent creates genai.Client() at import time).
"""
import random
import re


# --- Constants ---

TIER_NAMES = {
    0: "Clear-headed",
    1: "Merry",
    2: "In his cups",
    3: "Three sheets to the wind",
    4: "Gone to the saints",
}

SPEECH_LABELS = {
    0: "You say",
    1: "You slur",
    2: "You mumble",
    3: "You babble",
    4: "You... attempt",
}

PROMPT_INDICATORS = {
    0: "> ",
    1: "~ ",
    2: "~~ ",
    3: "~~~ ",
    4: "~~~~ ",
}


# --- Tier Classification ---

def get_tier(drunkenness: int) -> int:
    """Map drunkenness level to tier 0-4.

    Tier 0: 0-10   (Clear-headed)
    Tier 1: 11-20  (Merry)
    Tier 2: 21-30  (In his cups)
    Tier 3: 31-40  (Three sheets to the wind)
    Tier 4: 41+    (Gone to the saints)
    """
    if drunkenness <= 10:
        return 0
    elif drunkenness <= 20:
        return 1
    elif drunkenness <= 30:
        return 2
    elif drunkenness <= 40:
        return 3
    else:
        return 4


# --- Garbling Entry Point ---

def garble(text: str, tier: int, model_name: str) -> str:
    """Garble speech text based on drunkenness tier.

    Dispatches to the appropriate garbling function based on tier:
    - Tier 0: No garbling (text returned unchanged)
    - Tier 1: Light rule-based garbling
    - Tier 2: Moderate rule-based garbling
    - Tier 3-4: Gemini AI garbling

    Args:
        text: The player's speech text to garble.
        tier: Drunkenness tier (0-4) from get_tier().
        model_name: Gemini model name (used only for tiers 3-4).

    Returns:
        Garbled text, or original text unchanged for tier 0.
    """
    if tier == 0:
        return text
    elif tier == 1:
        return _garble_tier1(text)
    elif tier == 2:
        return _garble_tier2(text)
    else:
        return _garble_gemini(text, tier, model_name)


# --- Rule-Based Garbling ---

def _garble_tier1(text: str) -> str:
    """Light rule-based garbling for tier 1 (Merry).

    Applies each rule independently with a probability gate.
    Same input produces different output each call (randomized).

    Rules:
    - th at word start -> f or v (40% chance)
    - -ing at word end -> -in' (30% chance)
    - s at word end -> sh (20% chance)
    - Double one vowel in one random word (25% chance)
    - Append -e to one random word for medieval flavor (15% chance)
    """
    result = text

    # Rule 1: th at word start -> f or v (40%)
    if random.random() < 0.4:
        def _replace_th(m):
            replacement = random.choice(["f", "v"])
            # Preserve case
            if m.group(0)[0].isupper():
                return replacement.upper() + m.group(0)[2:]
            return replacement + m.group(0)[2:]
        result = re.sub(r'\bth', _replace_th, result, flags=re.IGNORECASE)

    # Rule 2: -ing at word end -> -in' (30%)
    if random.random() < 0.3:
        result = re.sub(r'ing\b', "in'", result, flags=re.IGNORECASE)

    # Rule 3: s at word end -> sh (20%)
    if random.random() < 0.2:
        result = re.sub(r's\b', 'sh', result, flags=re.IGNORECASE)

    # Rule 4: Double one vowel in one random word (25%)
    if random.random() < 0.25:
        words = result.split()
        if words:
            idx = random.randrange(len(words))
            word = words[idx]
            vowel_positions = [i for i, c in enumerate(word) if c.lower() in 'aeiou']
            if vowel_positions:
                pos = random.choice(vowel_positions)
                words[idx] = word[:pos] + word[pos] + word[pos:]
            result = ' '.join(words)

    # Rule 5: Append -e to one random word for medieval flavor (15%, only words > 3 chars)
    if random.random() < 0.15:
        words = result.split()
        eligible = [i for i, w in enumerate(words) if len(re.sub(r'[^a-zA-Z]', '', w)) > 3]
        if eligible:
            idx = random.choice(eligible)
            word = words[idx]
            # Append -e before any trailing punctuation
            m = re.match(r'^([a-zA-Z]+)([^a-zA-Z]*)$', word)
            if m:
                words[idx] = m.group(1) + 'e' + m.group(2)
            result = ' '.join(words)

    return result


def _garble_tier2(text: str) -> str:
    """Moderate rule-based garbling for tier 2 (In his cups).

    Applies tier 1 rules at higher probabilities (x1.5, capped at 0.9),
    then adds word-level distortions.

    Additional rules:
    - Word repetition: 25% chance to repeat one random word
    - Trailing off: 15% chance to replace last word with "..."
    - Word swap: 15% chance to swap two adjacent words (if > 3 words)
    - Medieval interjection: 10% chance to insert *hic* or "aye"
    """
    result = text

    # Apply tier 1 rules at 1.5x probability, capped at 0.9

    # Rule 1: th at word start -> f or v (60%)
    if random.random() < min(0.4 * 1.5, 0.9):
        def _replace_th(m):
            replacement = random.choice(["f", "v"])
            if m.group(0)[0].isupper():
                return replacement.upper() + m.group(0)[2:]
            return replacement + m.group(0)[2:]
        result = re.sub(r'\bth', _replace_th, result, flags=re.IGNORECASE)

    # Rule 2: -ing at word end -> -in' (45%)
    if random.random() < min(0.3 * 1.5, 0.9):
        result = re.sub(r'ing\b', "in'", result, flags=re.IGNORECASE)

    # Rule 3: s at word end -> sh (30%)
    if random.random() < min(0.2 * 1.5, 0.9):
        result = re.sub(r's\b', 'sh', result, flags=re.IGNORECASE)

    # Rule 4: Double one vowel in one random word (37.5%)
    if random.random() < min(0.25 * 1.5, 0.9):
        words = result.split()
        if words:
            idx = random.randrange(len(words))
            word = words[idx]
            vowel_positions = [i for i, c in enumerate(word) if c.lower() in 'aeiou']
            if vowel_positions:
                pos = random.choice(vowel_positions)
                words[idx] = word[:pos] + word[pos] + word[pos:]
            result = ' '.join(words)

    # Rule 5: Append -e to one random word (22.5%)
    if random.random() < min(0.15 * 1.5, 0.9):
        words = result.split()
        eligible = [i for i, w in enumerate(words) if len(re.sub(r'[^a-zA-Z]', '', w)) > 3]
        if eligible:
            idx = random.choice(eligible)
            word = words[idx]
            m = re.match(r'^([a-zA-Z]+)([^a-zA-Z]*)$', word)
            if m:
                words[idx] = m.group(1) + 'e' + m.group(2)
            result = ' '.join(words)

    # Word-level distortions (tier 2 only)

    words = result.split()

    # Rule 6: Word repetition (25%)
    if words and random.random() < 0.25:
        idx = random.randrange(len(words))
        words.insert(idx + 1, words[idx])
        result = ' '.join(words)
        words = result.split()

    # Rule 7: Trailing off (15%) — replace last word with "..."
    if words and random.random() < 0.15:
        words[-1] = "..."
        result = ' '.join(words)
        words = result.split()

    # Rule 8: Word swap (15%) — swap two adjacent words if > 3 words
    if len(words) > 3 and random.random() < 0.15:
        idx = random.randrange(len(words) - 1)
        words[idx], words[idx + 1] = words[idx + 1], words[idx]
        result = ' '.join(words)
        words = result.split()

    # Rule 9: Medieval interjection (10%)
    if words and random.random() < 0.1:
        interjection = random.choice(["*hic*", "aye"])
        idx = random.randint(0, len(words))
        words.insert(idx, interjection)
        result = ' '.join(words)

    return result


# --- Gemini AI Garbling ---

def _garble_gemini(text: str, tier: int, model_name: str) -> str:
    """AI garbling for tiers 3-4 using safe_generate().

    Import is done inside this function (not at module level) to avoid
    circular imports — base_agent.py creates genai.Client() at import
    time, which requires GEMINI_API_KEY to be set.

    Tier 3: Heavy slurring, ~50% meaning preserved.
    Tier 4: Near-total babbling, ~10-20% meaning survives.

    Args:
        text: The player's speech text to garble.
        tier: 3 or 4.
        model_name: Gemini model name from config.

    Returns:
        Garbled text from Gemini, or original text as fallback.
    """
    # Import inside function to avoid circular imports at module level
    from agents.base_agent import safe_generate  # noqa: PLC0415

    if tier == 3:
        prompt = (
            f"You are garbling a medieval tavern-goer's speech. They are very drunk — "
            f"Three sheets to the wind. Garble this speech with heavy slurring:\n"
            f'Original: "{text}"\n\n'
            "Apply these transformations: replace s with sh, replace th with f, "
            "insert *hic* 1-2 times, include a slurred medieval oath (e.g., 'by the shaintsh...'), "
            "swap or drop one word, trail off at the end. "
            "About 50% of the meaning should survive. "
            "Output ONLY the garbled speech. No explanation, no quotes, no preamble."
        )
    else:
        # Tier 4
        prompt = (
            f"You are garbling a medieval tavern-goer's speech. They are completely obliterated — "
            f"Gone to the saints. Near-total babbling:\n"
            f'Original: "{text}"\n\n'
            "Near-total incoherence: repeat words, insert medieval exclamations (*hic*, "
            "'shainsh preserve ush', 'blesshed be'), trail into gibberish. "
            "About 10-20% of the meaning should survive. Maximum slurring. "
            "Output ONLY the garbled speech. No explanation, no quotes, no preamble."
        )

    result = safe_generate(model_name, prompt)

    if not result:
        return text

    # Strip common Gemini preamble patterns
    for prefix in ("Here is", "Garbled:", "Output:", '"'):
        if result.startswith(prefix):
            # Strip the prefix and any leading whitespace/colon
            result = result[len(prefix):].lstrip(': \n"')
            break

    # If result is empty after stripping, fall back to original
    return result if result.strip() else text
