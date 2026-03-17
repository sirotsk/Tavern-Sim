#!/usr/bin/env python3
"""Peasant Simulator: Tavern Edition -- Game Launcher.

Single-file launcher that handles all preflight checks and starts the game
server. Run this script to go from "I downloaded this" to "I'm playing"
with zero manual dependency management.

Usage:
    python run.py
    python3 run.py
    (or double-click run.bat on Windows)

Checks performed (in order):
    1. Python version >= 3.11
    2. Poetry detection and dependency installation
    3. .env / API key validation
    4. Server startup via `poetry run start`
"""

import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root: always relative to this script, not the cwd
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# ANSI color helpers (stdlib only -- no third-party imports)
# ---------------------------------------------------------------------------
# Enable VT100 escape processing on Windows cmd.exe (no-op on Unix)
os.system("")

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Use a simple text marker that works in every terminal
CHECKMARK = GREEN + "[ok]" + RESET
CROSS = RED + "[!!]" + RESET
WARN = YELLOW + "[??]" + RESET

# Poetry command -- starts as bare "poetry", updated to
# [sys.executable, "-m", "poetry"] after pip-installing Poetry
# (because newly pip-installed scripts aren't on PATH in the current session).
POETRY_CMD: list[str] = ["poetry"]


def _print_error(*lines: str) -> None:
    """Print each line prefixed with the error marker."""
    for line in lines:
        print(f"  {CROSS} {RED}{line}{RESET}")


def _print_warn(*lines: str) -> None:
    """Print each line prefixed with the warning marker."""
    for line in lines:
        print(f"  {WARN} {YELLOW}{line}{RESET}")


def _ask_yes_no(prompt: str) -> bool:
    """Prompt the player with a [Y/n] question. Default is yes."""
    try:
        answer = input(f"  {prompt} [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


# ---------------------------------------------------------------------------
# Check 1: Python version
# ---------------------------------------------------------------------------
def check_python_version() -> bool:
    """Verify Python >= 3.11. Return True if ok, False otherwise."""
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < (3, 11):
        print()
        _print_error(
            f"Alas, thy Python is too ancient! Found {major}.{minor}, "
            "but 3.11 or newer is required.",
        )
        print(
            f"  Download the latest Python from "
            f"https://www.python.org/downloads/"
        )
        print()
        return False
    print(f"  {CHECKMARK} Python {major}.{minor} found")
    return True


# ---------------------------------------------------------------------------
# Check 2: Poetry + dependency installation
# ---------------------------------------------------------------------------
def _poetry_available() -> bool:
    """Return True if `poetry --version` succeeds."""
    try:
        result = subprocess.run(
            POETRY_CMD + ["--version"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _dependencies_installed() -> bool:
    """Quick check: can we import fastapi inside the Poetry venv?"""
    try:
        result = subprocess.run(
            POETRY_CMD + ["run", "python", "-c", "import fastapi"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _run_poetry_install() -> bool:
    """Run `poetry install` and return True on success."""
    print(f"  Installing dependencies...")
    try:
        result = subprocess.run(
            POETRY_CMD + ["install", "--no-interaction"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
    except FileNotFoundError:
        print()
        _print_error(
            "Could not find Poetry command.",
            "Try restarting your terminal or run `pip install -r requirements.txt` manually.",
        )
        print()
        return False
    if result.returncode != 0:
        print()
        _print_error("Poetry install failed:")
        # Show last few lines of output for debugging
        output = (result.stderr or result.stdout or "").strip()
        if output:
            for line in output.splitlines()[-10:]:
                print(f"    {line}")
        print()
        return False
    print(f"  {CHECKMARK} Dependencies installed")
    return True


def _install_poetry_via_pip() -> bool:
    """Attempt to install Poetry using pip. Return True on success.

    After a successful install, switches POETRY_CMD to
    [sys.executable, "-m", "poetry"] because newly pip-installed scripts
    are not on PATH in the current shell session on Windows.
    """
    global POETRY_CMD
    print(f"  Installing Poetry...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "poetry"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Switch to module invocation -- bare "poetry" won't be on
            # PATH until the user opens a new terminal.
            POETRY_CMD = [sys.executable, "-m", "poetry"]
            print(f"  {CHECKMARK} Poetry installed")
            return True
        else:
            _print_error("Failed to install Poetry via pip.")
            output = (result.stderr or result.stdout or "").strip()
            if output:
                for line in output.splitlines()[-5:]:
                    print(f"    {line}")
            return False
    except Exception as exc:
        _print_error(f"Failed to install Poetry: {exc}")
        return False


def check_dependencies() -> bool:
    """Ensure Poetry is available and dependencies are installed.

    Returns True if everything is ready, False on failure or user refusal.
    """
    has_poetry = _poetry_available()

    if has_poetry:
        print(f"  {CHECKMARK} Poetry found")
    else:
        _print_warn("Poetry not found.")
        if _ask_yes_no("Install Poetry via pip?"):
            if not _install_poetry_via_pip():
                print()
                _print_error(
                    "Cannot start without dependencies.",
                    "Install Poetry (https://python-poetry.org) or run "
                    "`pip install -r requirements.txt` manually.",
                )
                print()
                return False
            has_poetry = True
        else:
            print()
            _print_error(
                "Cannot start without dependencies.",
                "Install Poetry (https://python-poetry.org) or run "
                "`pip install -r requirements.txt` manually.",
            )
            print()
            return False

    # Poetry is available -- check if deps are installed
    if _dependencies_installed():
        print(f"  {CHECKMARK} Dependencies installed")
        return True

    # Dependencies missing -- ask before installing
    if _ask_yes_no("Dependencies not installed. Install now?"):
        return _run_poetry_install()
    else:
        print()
        _print_error(
            "Cannot start without dependencies.",
            "Run `poetry install` manually.",
        )
        print()
        return False


# ---------------------------------------------------------------------------
# Check 3: API key / .env validation
# ---------------------------------------------------------------------------
def check_api_key() -> bool:
    """Verify .env contains GEMINI_API_KEY or GOOGLE_API_KEY.

    Returns True if a non-empty key is found, False otherwise.
    """
    env_path = PROJECT_ROOT / ".env"

    if not env_path.is_file():
        _print_api_key_error()
        return False

    # Parse .env manually (stdlib only -- no dotenv import)
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        _print_api_key_error()
        return False

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in ("GEMINI_API_KEY", "GOOGLE_API_KEY") and value:
            # Make sure it's not the placeholder from .env.example
            if value.startswith("your_"):
                continue
            print(f"  {CHECKMARK} API key found")
            return True

    _print_api_key_error()
    return False


def _print_api_key_error() -> None:
    """Print a medieval-flavored error about the missing API key."""
    print()
    _print_error("The tavern requires a magical key to summon its patrons!")
    print(f"  Create a {BOLD}.env{RESET} file in the project root with:")
    print(f"    GEMINI_API_KEY=your-key-here")
    print()
    print(f"  Get your key at: https://aistudio.google.com/apikey")
    print(f"  See README for details.")
    print()


# ---------------------------------------------------------------------------
# Step 4: Start the server
# ---------------------------------------------------------------------------
def start_server() -> None:
    """Launch the game server via Poetry's virtualenv.

    Uses ``poetry run python -c ...`` instead of ``poetry run start``
    because package-mode = false means script entry points aren't
    installed.
    """
    print()
    print(f"  {BOLD}Starting server...{RESET}")
    print()
    try:
        result = subprocess.run(
            POETRY_CMD + [
                "run", "python", "-c",
                "from server.app import run_server; run_server()",
            ],
            cwd=str(PROJECT_ROOT),
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n\nFarewell, traveler. The tavern doors close behind you.")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    """Run all preflight checks, then start the game server."""
    # Ensure we're operating from the project root so Poetry finds
    # pyproject.toml regardless of where the user invoked the script.
    os.chdir(str(PROJECT_ROOT))

    print()
    print(f"  {BOLD}Peasant Simulator: Tavern Edition{RESET}")
    print(f"  Preflight checks...")
    print()

    # 1. Python version
    if not check_python_version():
        sys.exit(1)

    # 2. Poetry + dependencies
    if not check_dependencies():
        sys.exit(1)

    # 3. API key
    if not check_api_key():
        sys.exit(1)

    # All checks passed -- launch!
    start_server()


if __name__ == "__main__":
    main()
