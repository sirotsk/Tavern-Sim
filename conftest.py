"""
Root conftest.py — loads .env before test collection.

agents/base_agent.py creates genai.Client() at module import time, which reads
GEMINI_API_KEY from the environment. Without this file, pytest collection fails
when any test imports from game.session_setup (which imports agents.base_agent).

This mirrors the ensure_api_key() call in main.py — it must happen before any
module-level genai.Client() instantiation.
"""
import os
from pathlib import Path


def pytest_configure(config):
    """Load .env before test collection begins."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            # dotenv not installed: try manual parse
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())
