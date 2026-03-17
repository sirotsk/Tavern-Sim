# Peasant Simulator: Tavern Edition

A text-based medieval tavern RPG powered by Google Gemini AI. Chat with AI-driven patrons, play bar games, trade items, and explore procedurally generated taverns -- every session is different.

## Prerequisites

- **Python 3.11 or newer** -- [Download](https://www.python.org/downloads/)
  - On Windows, check "Add Python to PATH" during installation
- **Gemini API key** -- [Get one free](https://aistudio.google.com/apikey)

## Quick Start

-----------------------------------------------------------------------------------------------
# NOAH READ THIS FOR STARTUP

## 1. Install peotry
* open a cmd terminal and paste this:
curl -sSL https://install.python-poetry.org | py -

After that finishes run this:
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\Users\sirot\AppData\Roaming\Python\Scripts", "User")

Okay so thats wrong but give it to Claude to fix.

After that, close your terminal, go into the project folder, and run the "run.bat"

Success.





----------------------------------------------------------------------------------------------

1. **Get the code**
   ```
   git clone <repo-url>
   cd peasant-simulator-tavern-edition
   ```

2. **Add your API key**
   - Copy `.env.example` to `.env`
   - Replace `your_gemini_api_key_here` with your actual key
   ```
   cp .env.example .env
   ```

3. **Run the game**

   **Windows (double-click):**
   Double-click `run.bat` in the project folder.

   **Any platform (terminal):**
   ```
   python run.py
   ```

   The launcher checks your setup, installs dependencies if needed, and opens the game in your browser.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Python not found" | Install Python 3.11+ and ensure it's on your PATH |
| "Python too old" | Upgrade to Python 3.11 or newer |
| "API key not found" | Create a `.env` file with `GEMINI_API_KEY=your-key` |
| Dependencies fail to install | Run `pip install -r requirements.txt` manually |
| Browser doesn't open | Navigate to http://localhost:8000 manually |
| Port already in use | Change the port in `settings.toml` under `[server]` |
