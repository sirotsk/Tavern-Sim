"""
AgentManager — registry of per-patron chat sessions.

Single instance per game session. Holds all active PatronAgent and BarkeepAgent instances.
get_or_create_patron() ensures conversation history persists on re-approach:
if the patron was already talked to, the same Chat session is returned.
Each patron's Chat object is fully isolated — no cross-patron state (NPC-03).
"""
from agents.patron_agent import PatronAgent
from agents.barkeep_agent import BarkeepAgent


class AgentManager:
    """Registry that creates and retrieves NPC agent instances.

    One instance lives for the full game session. On first approach the agent
    is created (creating its Gemini Chat session). On re-approach the existing
    agent is returned, preserving full conversation history.

    NPC-03 isolation: each patron gets its own PatronAgent with its own Chat
    object. No two patrons ever share a Chat session.
    """

    def __init__(
        self,
        tavern_data: dict,
        patron_profiles: dict,
        barkeep_profile: dict,
        player_name: str,
        model_name: str,
    ) -> None:
        """Initialize the AgentManager with session-level data.

        Args:
            tavern_data: Full tavern data dict (agent_profiles/tavern.json).
            patron_profiles: Dict mapping patron_id -> profile dict.
                             e.g. {"patron_001": {...}, "patron_002": {...}}
            barkeep_profile: The barkeep profile dict (agent_profiles/barkeep.json).
            player_name: Player's name if known, empty string otherwise.
            model_name: Gemini model name from config["model"]["name"].
        """
        self._tavern_data = tavern_data
        self._patron_profiles = patron_profiles
        self._barkeep_profile = barkeep_profile
        self._player_name = player_name
        self._model_name = model_name

        self._patron_agents: dict[str, PatronAgent] = {}  # patron_id -> PatronAgent
        self._barkeep_agent: BarkeepAgent | None = None

    def get_or_create_patron(self, patron_id: str) -> PatronAgent:
        """Return the PatronAgent for this patron, creating one if needed.

        On first approach: creates a new PatronAgent (creates Gemini Chat session).
        On re-approach: returns the existing agent with its accumulated history intact.

        This is the NPC-03 re-approach guarantee — conversation context persists.

        Args:
            patron_id: Patron identifier string (e.g. "patron_001").

        Returns:
            The PatronAgent for this patron.

        Raises:
            KeyError: If patron_id is not found in patron_profiles.
        """
        if patron_id in self._patron_agents:
            # CRITICAL: return existing agent — preserves Chat session and history
            return self._patron_agents[patron_id]

        # First approach — create agent and store
        profile = self._patron_profiles[patron_id]
        agent = PatronAgent(
            profile=profile,
            tavern_data=self._tavern_data,
            player_name=self._player_name,
            model_name=self._model_name,
        )
        self._patron_agents[patron_id] = agent
        return agent

    def get_or_create_barkeep(self) -> BarkeepAgent:
        """Return the BarkeepAgent, creating one if this is the first barkeep interaction.

        On first approach: creates a new BarkeepAgent (creates Gemini Chat session).
        On re-approach: returns the existing agent with its accumulated history intact.

        Returns:
            The single BarkeepAgent for this session.
        """
        if self._barkeep_agent is not None:
            return self._barkeep_agent

        self._barkeep_agent = BarkeepAgent(
            profile=self._barkeep_profile,
            tavern_data=self._tavern_data,
            player_name=self._player_name,
            model_name=self._model_name,
        )
        return self._barkeep_agent

    def has_patron(self, patron_id: str) -> bool:
        """Return whether this patron has been talked to (Chat session exists).

        Args:
            patron_id: Patron identifier string.

        Returns:
            True if a PatronAgent exists for this patron_id.
        """
        return patron_id in self._patron_agents

    def has_barkeep(self) -> bool:
        """Return whether the barkeep has been talked to (Chat session exists).

        Returns:
            True if the BarkeepAgent has been created.
        """
        return self._barkeep_agent is not None
