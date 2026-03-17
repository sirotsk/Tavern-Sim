"""WebSocket connection handler.

Phase 5: Echo test -- confirms the WebSocket connection is live.
Phase 6: Full game session lifecycle -- new game, command processing, status updates.
"""
import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from server import messages
from server.game_session import GameSession

# In-memory session store -- tracks active WebSocket connections by session ID.
_sessions: dict[str, WebSocket] = {}

# Game session store -- tracks GameSession objects per connection.
_game_sessions: dict[str, GameSession] = {}


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Handle a single WebSocket connection.

    Dispatches incoming messages to the appropriate handler:
    - NEW_GAME: Creates a GameSession, runs setup, sends loading progress,
      paced opening narration, and initial status.
    - INPUT: Sends thinking indicator, processes command via GameSession,
      sends status update.
    - PING: Echo test (kept from Phase 5 for debugging).

    Args:
        websocket: The WebSocket connection object.
        session_id: Client-generated UUID for session persistence across reconnects.
    """
    await websocket.accept()
    _sessions[session_id] = websocket

    # Send connection acknowledgement
    await websocket.send_json({
        "type": messages.CONNECTED,
        "session_id": session_id,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == messages.NEW_GAME:
                player_name = data.get("player_name", "Stranger")
                session = GameSession(session_id, websocket)
                _game_sessions[session_id] = session

                # Delete any existing save -- fresh game starts clean
                from game.save_manager import delete_save
                delete_save()

                # Send loading_start
                await websocket.send_json({
                    "type": messages.LOADING_START,
                    "message": "Generating your tavern...",
                })

                # Run session setup in thread (15-30s Gemini calls)
                await session.start(player_name)
                # Progress messages were collected by _emit during setup;
                # flush_messages was called at end of start()

                # Send loading_complete
                await websocket.send_json({
                    "type": messages.LOADING_COMPLETE,
                })

                # Brief pause before welcome splash
                await asyncio.sleep(0.3)

                # Send welcome splash with tavern name
                await websocket.send_json({
                    "type": messages.NARRATION,
                    "text": f"Welcome to {session.state.tavern_name}",
                    "subtype": "welcome",
                })

                await asyncio.sleep(1.0)

                # Send opening narration section-by-section
                sections = await asyncio.to_thread(session.get_opening_sections)
                for section in sections:
                    if section:
                        await websocket.send_json({
                            "type": messages.NARRATION,
                            "text": section,
                        })
                        await asyncio.sleep(0.5)

                # Send command hint
                await websocket.send_json({
                    "type": messages.SYSTEM,
                    "text": "Type 'help' or '?' to see what you can do. Type 'look' or 'l' to survey the tavern.",
                })

                # Send initial status
                await websocket.send_json(session.build_status_msg())

            elif msg_type == messages.INPUT:
                session = _game_sessions.get(session_id)
                if session and session.parser:
                    text = data.get("text", "").strip()
                    if text:
                        # Send thinking indicator
                        await websocket.send_json({"type": messages.THINKING})

                        # Process command (blocking Gemini calls in thread)
                        await session.handle_command(text)

                        # Send thinking_done to re-enable input
                        await websocket.send_json({"type": messages.THINKING_DONE})

                        # Send updated status after every command
                        await websocket.send_json(session.build_status_msg())

                        # Check if session ended (quit or pass-out game over)
                        if session.state and not session.state.session_active:
                            # Game over -- client handles this via game_over message
                            # (already emitted by CommandParser)
                            pass
                else:
                    await websocket.send_json({
                        "type": messages.ERROR,
                        "text": "No active game session. Start a new game first.",
                    })

            elif msg_type == messages.LOAD:
                from game.save_manager import load_game
                save_data = load_game()
                if save_data is None:
                    await websocket.send_json({
                        "type": messages.ERROR,
                        "text": "No valid save file found. Starting new game.",
                    })
                    continue

                session = GameSession(session_id, websocket)
                _game_sessions[session_id] = session

                # Load reconstructs engine stack from save (near-instant, no Gemini)
                await session.load(save_data)

                # Send recap narration
                from server.game_session import build_load_recap
                recap = build_load_recap(save_data)
                await websocket.send_json({
                    "type": messages.NARRATION,
                    "text": recap,
                })

                # Send command hint
                await websocket.send_json({
                    "type": messages.SYSTEM,
                    "text": "Type 'help' or '?' to see what you can do. Type 'look' or 'l' to survey the tavern.",
                })

                # Send initial status
                await websocket.send_json(session.build_status_msg())

            elif msg_type == messages.PING:
                # Keep echo test for debugging
                await websocket.send_json({
                    "type": messages.ECHO,
                    "original": data,
                })

            else:
                await websocket.send_json({
                    "type": messages.ERROR,
                    "text": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        # Clean up session on disconnect -- prevents stale entries and memory growth
        _sessions.pop(session_id, None)
        _game_sessions.pop(session_id, None)
