"""Bar game mechanics for Peasant Simulator: Tavern Edition.

Each game function takes a session dict and player input string,
resolves the mechanic using stdlib random, and returns:
    (session, display_text, outcome)

Outcomes: "player_wins" | "patron_wins" | "tie" | "continue"
"continue" means invalid input -- prompt the player to try again.

No imports from the game engine. Pure Python + stdlib only.
"""

import random
import re

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

SUITS = ["Hearts", "Diamonds", "Clubs", "Spades"]


def _card_name(rank: int) -> str:
    """Return display name for a card rank (2-14)."""
    if 2 <= rank <= 10:
        return str(rank)
    names = {11: "Jack", 12: "Queen", 13: "King", 14: "Ace"}
    return names[rank]


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

GAME_DISPLAY_NAMES = {
    "high_roll": "High Roll",
    "over_under": "Over/Under",
    "high_card": "High Card Draw",
    "sword_shield_arrow": "Sword-Shield-Arrow",
    "morra": "Morra",
    "coin_toss": "Coin Toss",
    "cup_and_ball": "Cup & Ball",
    "odds_and_evens": "Odds & Evens",
    "three_card": "Three-Card Guess",
    "knucklebones": "Knucklebones",
    "arm_wrestle": "Arm Wrestle",
    "merchants_gambit": "Merchant's Gambit",
    "beggars_bluff": "Beggar's Bluff",
}

# ---------------------------------------------------------------------------
# Game 1: High Roll
# ---------------------------------------------------------------------------

def high_roll(session: dict, player_input: str) -> tuple[dict, str, str]:
    """High Roll: both roll a d6, higher wins. Any input triggers the roll.

    Ties are a valid outcome -- no re-roll. The tie outcome signals the
    challenge flow to handle the tie (e.g. no gold changes hands).
    """
    player_roll = random.randint(1, 6)
    patron_roll = random.randint(1, 6)
    display = (
        f"You roll a {player_roll}. Your opponent rolls a {patron_roll}."
    )
    if player_roll > patron_roll:
        return session, display, "player_wins"
    elif patron_roll > player_roll:
        return session, display, "patron_wins"
    else:
        return session, display, "tie"


# ---------------------------------------------------------------------------
# Game 2: Over/Under
# ---------------------------------------------------------------------------

def over_under(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Over/Under: guess whether 2d6 total is over 7, under 7, or exactly seven.

    Valid input: "over", "under", "seven" (case-insensitive).
    If sum is exactly 7 and player guessed over/under, player loses.
    """
    choice = player_input.strip().lower()
    if choice not in ("over", "under", "seven"):
        return session, "Guess: over, under, or seven.", "continue"

    die_a = random.randint(1, 6)
    die_b = random.randint(1, 6)
    total = die_a + die_b

    display = (
        f"The dice show {die_a} and {die_b} (total: {total}). "
        f"You called {choice}."
    )

    if total == 7:
        if choice == "seven":
            return session, display, "player_wins"
        else:
            return session, display, "patron_wins"
    elif total > 7:
        outcome = "player_wins" if choice == "over" else "patron_wins"
    else:  # total < 7
        outcome = "player_wins" if choice == "under" else "patron_wins"

    return session, display, outcome


# ---------------------------------------------------------------------------
# Game 3: High Card Draw
# ---------------------------------------------------------------------------

def high_card(session: dict, player_input: str) -> tuple[dict, str, str]:
    """High Card Draw: both draw a card (rank 2-14), higher wins. Any input draws.

    Random suit added for flavour. Tie is a valid outcome.
    """
    player_rank = random.randint(2, 14)
    patron_rank = random.randint(2, 14)
    player_suit = random.choice(SUITS)
    patron_suit = random.choice(SUITS)

    display = (
        f"You draw the {_card_name(player_rank)} of {player_suit}. "
        f"Your opponent draws the {_card_name(patron_rank)} of {patron_suit}."
    )

    if player_rank > patron_rank:
        return session, display, "player_wins"
    elif patron_rank > player_rank:
        return session, display, "patron_wins"
    else:
        return session, display, "tie"


# ---------------------------------------------------------------------------
# Game 4: Sword-Shield-Arrow (medieval rock-paper-scissors)
# ---------------------------------------------------------------------------

_SSA_BEATS = {"sword": "arrow", "arrow": "shield", "shield": "sword"}
_SSA_VALID = {"sword", "arrow", "shield"}


def sword_shield_arrow(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Sword-Shield-Arrow: medieval RPS. Sword beats Arrow, Arrow beats Shield, Shield beats Sword.

    Valid input: "sword", "shield", or "arrow" (case-insensitive).
    """
    player_choice = player_input.strip().lower()
    if player_choice not in _SSA_VALID:
        return (
            session,
            f"Choose: sword, shield, or arrow. (You typed: '{player_input.strip()}')",
            "continue",
        )

    patron_choice = random.choice(list(_SSA_VALID))
    display = (
        f"You choose {player_choice}! Your opponent shows {patron_choice}."
    )

    if _SSA_BEATS[player_choice] == patron_choice:
        return session, display, "player_wins"
    elif _SSA_BEATS[patron_choice] == player_choice:
        return session, display, "patron_wins"
    else:
        return session, display, "tie"


# ---------------------------------------------------------------------------
# Game 5: Morra
# ---------------------------------------------------------------------------

_MORRA_PATTERN = re.compile(r"show\s+([1-5])\s+guess\s+([2-9]|10)", re.IGNORECASE)


def morra(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Morra: both show 1-5 fingers and guess the total (2-10). Correct guesser wins.

    Valid input: "show N guess M" where N is 1-5 and M is 2-10
    e.g. "show 3 guess 7".
    Both correct or neither correct = tie.
    """
    m = _MORRA_PATTERN.match(player_input.strip())
    if not m:
        return (
            session,
            "Type: show [1-5] guess [2-10]  (e.g. 'show 3 guess 7')",
            "continue",
        )

    player_show = int(m.group(1))
    player_guess = int(m.group(2))
    patron_show = random.randint(1, 5)
    patron_guess = random.randint(2, 10)
    total = player_show + patron_show

    display = (
        f"You show {player_show} fingers and guess {player_guess}. "
        f"Your opponent shows {patron_show} fingers and guesses {patron_guess}. "
        f"Total: {total}."
    )

    player_correct = player_guess == total
    patron_correct = patron_guess == total

    if player_correct and not patron_correct:
        return session, display, "player_wins"
    elif patron_correct and not player_correct:
        return session, display, "patron_wins"
    else:
        return session, display, "tie"


# ---------------------------------------------------------------------------
# Game 6: Coin Toss
# ---------------------------------------------------------------------------

def coin_toss(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Coin Toss: call heads or tails. Random flip.

    Valid input: "heads" or "tails" (case-insensitive).
    """
    choice = player_input.strip().lower()
    if choice not in ("heads", "tails"):
        return session, "Call it: heads or tails.", "continue"

    result = random.choice(("heads", "tails"))
    display = (
        f"The coin spins through the air... {result}! You called {choice}."
    )

    if result == choice:
        return session, display, "player_wins"
    else:
        return session, display, "patron_wins"


# ---------------------------------------------------------------------------
# Game 7: Cup & Ball
# ---------------------------------------------------------------------------

def cup_and_ball(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Cup & Ball: ball hidden under one of 3 cups. Player picks 1, 2, or 3.

    Valid input: "1", "2", or "3".
    Correct = player_wins. Incorrect = patron_wins. No tie possible.
    """
    choice = player_input.strip()
    if choice not in ("1", "2", "3"):
        return session, "Pick a cup: 1, 2, or 3.", "continue"

    ball_cup = random.randint(1, 3)
    display = (
        f"The cups are shuffled... You tap cup {choice}. "
        f"The ball is under cup {ball_cup}!"
    )

    if int(choice) == ball_cup:
        return session, display, "player_wins"
    else:
        return session, display, "patron_wins"


# ---------------------------------------------------------------------------
# Game 8: Odds & Evens
# ---------------------------------------------------------------------------

def odds_and_evens(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Odds & Evens: pick odds or evens. Both show 1-5 fingers. Sum checked.

    Valid input: "odds" or "evens" (case-insensitive).
    If sum matches player's call, player wins; otherwise patron wins.
    """
    choice = player_input.strip().lower()
    if choice not in ("odds", "evens"):
        return session, "Pick: odds or evens.", "continue"

    player_fingers = random.randint(1, 5)
    patron_fingers = random.randint(1, 5)
    total = player_fingers + patron_fingers
    parity = "odd" if total % 2 != 0 else "even"

    display = (
        f"You show {player_fingers} fingers. "
        f"Your opponent shows {patron_fingers} fingers. "
        f"Total: {total} -- that's {parity}!"
    )

    player_wins = (choice == "odds" and total % 2 != 0) or (
        choice == "evens" and total % 2 == 0
    )

    if player_wins:
        return session, display, "player_wins"
    else:
        return session, display, "patron_wins"


# ---------------------------------------------------------------------------
# Game 9: Three-Card Guess  (single-turn)
# ---------------------------------------------------------------------------

def three_card(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Three-Card Guess: three cards are laid face-down. Pick the highest.

    Valid input: "1", "2", or "3".
    Correct = player_wins. Incorrect = patron_wins. No tie possible.
    """
    choice = player_input.strip()
    if choice not in ("1", "2", "3"):
        return session, "Pick a card: 1, 2, or 3.", "continue"

    cards = random.sample(range(2, 15), 3)  # 3 unique ranks
    chosen_idx = int(choice) - 1
    highest_idx = cards.index(max(cards))
    card_displays = [f"{_card_name(r)} of {random.choice(SUITS)}" for r in cards]
    display = (
        f"The cards are turned over: {', '.join(card_displays)}. "
        f"You chose card {choice} -- the {card_displays[chosen_idx]}."
    )

    if chosen_idx == highest_idx:
        return session, display + " The highest card -- well picked!", "player_wins"
    else:
        return session, display + f" The highest was the {card_displays[highest_idx]}. Ill luck.", "patron_wins"


# ---------------------------------------------------------------------------
# Game 10: Knucklebones  (single-turn)
# ---------------------------------------------------------------------------

def knucklebones(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Knucklebones: both roll 2d6. Closest to 7 wins.

    Any input triggers the roll.
    Tiebreaker: under-7 beats over-7. If same side, tie.
    """
    player_total = random.randint(1, 6) + random.randint(1, 6)
    patron_total = random.randint(1, 6) + random.randint(1, 6)
    display = f"You toss the bones and roll {player_total}. Your opponent rolls {patron_total}."

    p_dist = abs(player_total - 7)
    o_dist = abs(patron_total - 7)

    if p_dist < o_dist:
        return session, display + " Closer to seven -- the pot is yours!", "player_wins"
    elif o_dist < p_dist:
        return session, display + " Closer to seven -- your opponent takes it!", "patron_wins"
    else:
        # Equidistant: under beats over
        if player_total <= 7 and patron_total > 7:
            return session, display + " Equidistant, but under beats over -- you win!", "player_wins"
        elif patron_total <= 7 and player_total > 7:
            return session, display + " Equidistant, but under beats over -- you lose!", "patron_wins"
        else:
            return session, display + " Dead even -- no gold changes hands.", "tie"


# ---------------------------------------------------------------------------
# Game 11: Arm Wrestle  (best 2 of 3)
# ---------------------------------------------------------------------------

def arm_wrestle(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Arm Wrestle: best 2 of 3 rounds. Each round both roll 2d6 -- higher wins.

    First move: choose "left" or "right" arm (flavour only -- both are fair rolls).
    Subsequent moves: type anything to continue the next round.
    Session keys used: arm_choice, player_wins, patron_wins, rounds_played.
    """
    # First call -- choose arm
    if "arm_choice" not in session:
        choice = player_input.strip().lower()
        if choice not in ("left", "right"):
            return session, "Which arm? Choose: left or right.", "continue"
        session = dict(session)  # shallow copy to avoid mutating caller's dict
        session["arm_choice"] = choice
        session["player_wins"] = 0
        session["patron_wins"] = 0
        session["rounds_played"] = 0
        return (
            session,
            f"You plant your {choice} arm on the table. The match begins -- best of three!",
            "continue",
        )

    # Subsequent calls -- play next round
    session = dict(session)
    player_roll = random.randint(1, 6) + random.randint(1, 6)
    patron_roll = random.randint(1, 6) + random.randint(1, 6)
    session["rounds_played"] += 1
    rnd = session["rounds_played"]

    if player_roll > patron_roll:
        session["player_wins"] += 1
        result_line = f"Round {rnd}: you surge ahead ({player_roll} vs {patron_roll})!"
    elif patron_roll > player_roll:
        session["patron_wins"] += 1
        result_line = f"Round {rnd}: your opponent forces your arm down ({patron_roll} vs {player_roll})!"
    else:
        result_line = f"Round {rnd}: a dead heat ({player_roll} all) -- no point awarded!"

    score_line = f" [{session['player_wins']}-{session['patron_wins']} in rounds]"

    # Check for match winner (first to 2 wins, or after 3 rounds)
    if session["player_wins"] >= 2:
        return session, result_line + score_line + " You win the match!", "player_wins"
    if session["patron_wins"] >= 2:
        return session, result_line + score_line + " Your opponent wins the match!", "patron_wins"
    if session["rounds_played"] >= 3:
        # 3 rounds, nobody reached 2 -- whoever has more wins wins; otherwise tie
        if session["player_wins"] > session["patron_wins"]:
            return session, result_line + score_line + " Three rounds done -- you take it!", "player_wins"
        elif session["patron_wins"] > session["player_wins"]:
            return session, result_line + score_line + " Three rounds done -- your opponent takes it!", "patron_wins"
        else:
            return session, result_line + score_line + " Three rounds, dead even -- a draw!", "tie"

    # Match continues
    remaining = 3 - session["rounds_played"]
    return session, result_line + score_line + f" {remaining} round(s) left -- type anything for the next.", "continue"


# ---------------------------------------------------------------------------
# Game 12: Merchant's Gambit  (best 2 of 3)
# ---------------------------------------------------------------------------

def merchants_gambit(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Merchant's Gambit: best 2 of 3 rounds of blind bidding.

    Each round: bid 1, 2, or 3. Highest unique bid wins the round.
    Tied bids -- neither player scores the round (house rule: patron gets the point).
    Session keys: player_wins, patron_wins, rounds_played.
    """
    choice = player_input.strip()
    if choice not in ("1", "2", "3"):
        return session, "Place your bid: 1, 2, or 3.", "continue"

    session = dict(session)
    if "player_wins" not in session:
        session["player_wins"] = 0
        session["patron_wins"] = 0
        session["rounds_played"] = 0

    session["rounds_played"] += 1
    rnd = session["rounds_played"]
    player_bid = int(choice)
    patron_bid = random.randint(1, 3)

    if player_bid == patron_bid:
        session["patron_wins"] += 1
        result_line = f"Round {rnd}: you both bid {player_bid} -- tied bids favour the house!"
    elif player_bid > patron_bid:
        session["player_wins"] += 1
        result_line = f"Round {rnd}: your bid of {player_bid} beats {patron_bid} -- you take the round!"
    else:
        session["patron_wins"] += 1
        result_line = f"Round {rnd}: your bid of {player_bid} falls short of {patron_bid} -- opponent takes it!"

    score_line = f" [{session['player_wins']}-{session['patron_wins']} in rounds]"

    if session["player_wins"] >= 2:
        return session, result_line + score_line + " You win the match!", "player_wins"
    if session["patron_wins"] >= 2:
        return session, result_line + score_line + " Your opponent wins the match!", "patron_wins"
    if session["rounds_played"] >= 3:
        if session["player_wins"] > session["patron_wins"]:
            return session, result_line + score_line + " Three rounds done -- you take it!", "player_wins"
        elif session["patron_wins"] > session["player_wins"]:
            return session, result_line + score_line + " Three rounds done -- your opponent takes it!", "patron_wins"
        else:
            return session, result_line + score_line + " Three rounds, dead even -- a draw!", "tie"

    remaining = 3 - session["rounds_played"]
    return session, result_line + score_line + f" {remaining} round(s) left -- bid again (1, 2, or 3).", "continue"


# ---------------------------------------------------------------------------
# Game 13: Beggar's Bluff  (best 2 of 3)
# ---------------------------------------------------------------------------

def beggars_bluff(session: dict, player_input: str) -> tuple[dict, str, str]:
    """Beggar's Bluff: best 2 of 3 rounds of bluffing.

    Each round: claim "rich" or "poor". Patron independently calls "truth" or "bluff".
    Patron's actual hand is random. If patron reads the bluff correctly, patron wins the round.
    Session keys: player_wins, patron_wins, rounds_played.
    """
    choice = player_input.strip().lower()
    if choice not in ("rich", "poor"):
        return session, "Make your claim: rich or poor.", "continue"

    session = dict(session)
    if "player_wins" not in session:
        session["player_wins"] = 0
        session["patron_wins"] = 0
        session["rounds_played"] = 0

    session["rounds_played"] += 1
    rnd = session["rounds_played"]

    patron_call = random.choice(("truth", "bluff"))
    actual = random.choice(("rich", "poor"))
    player_honest = (choice == actual)
    patron_correct = (patron_call == "truth" and player_honest) or (
        patron_call == "bluff" and not player_honest
    )

    reveal = (
        f"Round {rnd}: you claim {choice}. "
        f"Your hand is actually {actual}. "
        f"Your opponent calls {patron_call}!"
    )

    if patron_correct:
        session["patron_wins"] += 1
        result_line = reveal + " Read like a book -- round to your opponent!"
    else:
        session["player_wins"] += 1
        result_line = reveal + " Fooled them -- round to you!"

    score_line = f" [{session['player_wins']}-{session['patron_wins']} in rounds]"

    if session["player_wins"] >= 2:
        return session, result_line + score_line + " You win the match!", "player_wins"
    if session["patron_wins"] >= 2:
        return session, result_line + score_line + " Your opponent wins the match!", "patron_wins"
    if session["rounds_played"] >= 3:
        if session["player_wins"] > session["patron_wins"]:
            return session, result_line + score_line + " Three rounds done -- you take it!", "player_wins"
        elif session["patron_wins"] > session["player_wins"]:
            return session, result_line + score_line + " Three rounds done -- your opponent takes it!", "patron_wins"
        else:
            return session, result_line + score_line + " Three rounds, dead even -- a draw!", "tie"

    remaining = 3 - session["rounds_played"]
    return session, result_line + score_line + f" {remaining} round(s) left -- make your claim (rich or poor).", "continue"


# ---------------------------------------------------------------------------
# Registry -- defined after all functions
# ---------------------------------------------------------------------------

GAME_REGISTRY: dict[str, callable] = {
    "high_roll": high_roll,
    "over_under": over_under,
    "high_card": high_card,
    "sword_shield_arrow": sword_shield_arrow,
    "morra": morra,
    "coin_toss": coin_toss,
    "cup_and_ball": cup_and_ball,
    "odds_and_evens": odds_and_evens,
    "three_card": three_card,
    "knucklebones": knucklebones,
    "arm_wrestle": arm_wrestle,
    "merchants_gambit": merchants_gambit,
    "beggars_bluff": beggars_bluff,
}
