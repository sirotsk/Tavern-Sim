"""Peasant Simulator: Tavern Edition — entry point."""
import io
import json
import os
import random
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows (box-drawing characters in TITLE_BANNER need UTF-8)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


TITLE_BANNER = """
╔══════════════════════════════════════╗
║   PEASANT SIMULATOR: TAVERN EDITION  ║
║       Every ale tells a story.       ║
╚══════════════════════════════════════╝
"""


def ensure_api_key() -> None:
    """Load API key from .env or prompt user to provide one.

    MUST be called before agents.base_agent is imported — base_agent
    creates genai.Client() at import time, which reads GEMINI_API_KEY.
    """
    from dotenv import load_dotenv
    load_dotenv()

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        print("\nNo Gemini API key found in .env")
        key = input("Paste your Gemini API key: ").strip()
        if not key:
            print("No API key provided. Exiting.")
            sys.exit(1)
        # Save to .env for future runs
        env_path = Path(".env")
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nGEMINI_API_KEY={key}\n")
        os.environ["GEMINI_API_KEY"] = key
        print("API key saved to .env\n")


def main() -> None:
    print(TITLE_BANNER)

    # 1. Ensure API key BEFORE importing base_agent (base_agent calls genai.Client() at import time)
    ensure_api_key()

    # 2. Import genai-dependent modules only after env is guaranteed
    from agents.base_agent import client
    from game.config import load_config
    from game.state import GameState
    from game.session_setup import SessionSetup

    # 3. Load config
    config = load_config()

    # Verify model name comes from config (FOUN-07: model name is not hardcoded)
    model_name = config["model"]["name"]
    # model_name is passed to session_setup and agents — never hardcode it

    # 4. Player name prompt (FOUN-02)
    player_name = input("What is your name, traveler? ").strip()
    if not player_name:
        player_name = "Stranger"

    # 5. Initialize session state
    state = GameState(player_name=player_name)

    # 6. Session setup (generates tavern, patrons, examinables, ambient pool)
    setup = SessionSetup(client, config, state, model_name=model_name)
    print("Generating your session...\n")
    setup.run()

    # 7. Load tavern data for NarratorAgent
    tavern_json_path = Path("agent_profiles/tavern.json")
    tavern_data = json.loads(tavern_json_path.read_text(encoding="utf-8"))

    # 8. Initialize NarratorAgent
    from agents.narrator_agent import NarratorAgent
    narrator = NarratorAgent(tavern_data, model_name)

    # 9. Initialize ActionLog
    from game.action_log import ActionLog
    action_log = ActionLog()

    # 10. Stream opening narration (WRLD-03)
    print()  # Blank line before opening
    patron_briefs = [p.brief_description for p in state.patrons]
    barkeep_path = Path("agent_profiles/barkeep.json")
    barkeep_data = json.loads(barkeep_path.read_text(encoding="utf-8"))
    barkeep_brief = barkeep_data.get("appearance", {}).get("brief", "The barkeep")
    opening_text = narrator.stream_opening(patron_briefs, barkeep_brief)
    action_log.append("opening", "", opening_text)

    # 11. Fixed command hint (consistent every session — not AI-generated)
    print()
    print("Type 'help' or '?' to see what you can do. Type 'look' or 'l' to survey the tavern.")
    print()

    # 12. Load patron profiles for AgentManager
    from agents.agent_manager import AgentManager
    patron_profiles = {}
    for patron_record in state.patrons:
        profile_path = Path(patron_record.profile_path)
        if profile_path.exists():
            patron_profiles[patron_record.profile_path] = json.loads(
                profile_path.read_text(encoding="utf-8")
            )

    # Inject patron_briefs into tavern_data so PatronAgents have cross-patron awareness
    tavern_data["patron_briefs"] = [p.brief_description for p in state.patrons]

    # 13. Initialize AgentManager
    agent_manager = AgentManager(
        tavern_data=tavern_data,
        patron_profiles=patron_profiles,
        barkeep_profile=barkeep_data,
        player_name=state.player_name,
        model_name=model_name,
    )

    # 14. Game loop
    from game.command_parser import CommandParser
    from game.drunk_filter import get_tier, PROMPT_INDICATORS
    parser = CommandParser(state, narrator, action_log, config, agent_manager)

    while state.session_active:
        try:
            tier = get_tier(state.drunkenness)
            tilde = PROMPT_INDICATORS[tier]
            if state.active_patron:
                # Build contextual prompt: use name if known, brief description otherwise
                display_label = state.active_patron  # Default: the active_patron string (name)
                # Check if talking to barkeep
                barkeep_name = state.barkeep_name or "Barkeep"
                if state.active_patron != barkeep_name:
                    # Find the patron record for richer display
                    for pr in state.patrons:
                        if pr.name and pr.name == state.active_patron:
                            display_label = pr.name
                            break
                        elif pr.brief_description and pr.brief_description == state.active_patron:
                            display_label = pr.brief_description
                            break
                prompt_str = f"[Talking to {display_label}] {tilde}"
            else:
                prompt_str = tilde
            raw = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nFarewell, traveler.")
            break
        if not raw:
            continue
        parser.parse(raw)


if __name__ == "__main__":
    main()
