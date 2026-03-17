"""WebSocket message type constants.

Every message crossing the WebSocket MUST carry a 'type' field matching
one of these constants. No raw strings -- use these constants everywhere.
"""

# Client -> Server
INPUT = "input"                    # Player command (Phase 6+)
PING = "ping"                      # Echo/heartbeat test (Phase 5)
SAVE = "save"                      # Save game (Phase 7)
LOAD = "load"                      # Load game (Phase 7)
NEW_GAME = "new_game"              # Start new game (Phase 6)

# Server -> Client
ECHO = "echo"                      # Echo test response (Phase 5)
CONNECTED = "connected"            # Connection acknowledged
ERROR = "error"                    # Error message
NARRATION = "narration"            # Narrator text (Phase 6+)
DIALOGUE = "dialogue"              # Patron/barkeep speech (Phase 6+)
STATUS = "status"                  # Player status update (Phase 6+)
INVENTORY = "inventory"            # Inventory contents (Phase 8+)
LOADING_START = "loading_start"    # Session generation started (Phase 6+)
LOADING_PROGRESS = "loading_progress"  # Generation progress (Phase 6+)
LOADING_COMPLETE = "loading_complete"  # Generation finished (Phase 6+)
SAVE_CONFIRM = "save_confirm"      # Save succeeded (Phase 7+)

# Server -> Client (Phase 6 additions)
PLAYER_ECHO = "player_echo"        # Echo of player's command
SYSTEM = "system"                  # System/help/status text
DIVIDER = "divider"                # Conversation start/end divider
THINKING = "thinking"              # Thinking indicator (show dots)
THINKING_DONE = "thinking_done"    # Thinking complete (hide dots, re-enable input)
GAME_OVER = "game_over"            # Session ended (quit or pass-out)
IMAGE = "image"                    # Transient image display (item examine/take)
