"""Action log — records all player commands and narrator responses for context injection."""
import json
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path("logs")


class ActionLog:
    """Session action log. Written to logs/session_YYYYMMDD_HHMMSS.json."""

    def __init__(self):
        LOGS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = LOGS_DIR / f"session_{ts}.json"
        self._entries: list[dict] = []
        self._flush()

    def append(self, command: str, target: str = "", narrator_response: str = "") -> None:
        """Record a command and its response."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "target": target,
            "narrator_response": narrator_response,
        }
        self._entries.append(entry)
        self._flush()

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get the last N entries."""
        return self._entries[-n:]

    def get_all(self) -> list[dict]:
        """Get all entries."""
        return list(self._entries)

    def _flush(self) -> None:
        """Write current entries to disk."""
        self._path.write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
