"""FastAPI web server for Peasant Simulator: Tavern Edition."""
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from game.config import load_config
from server.ws_handler import websocket_endpoint

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
AGENT_PROFILES_DIR = Path("agent_profiles")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: print server info and open browser. Shutdown: nothing to clean up in Phase 5."""
    config = load_config()
    port = config.get("server", {}).get("port", 8000)
    print(f"Peasant Simulator: Tavern Edition -- server running on http://localhost:{port}")

    def _open_browser():
        time.sleep(1.0)  # Wait for server to be fully ready
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open_browser, daemon=True).start()
    yield
    # Shutdown -- nothing to clean up in Phase 5


app = FastAPI(lifespan=lifespan)

# Mount static files BEFORE routes -- order matters (RESEARCH.md pitfall 1)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """Serve the title screen / game page."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/save-check")
async def save_check():
    """Check if a valid save file exists for the title screen."""
    from game.save_manager import has_save
    return JSONResponse({"has_save": has_save()})


@app.get("/session-images/{filename}")
async def session_image(filename: str):
    """Serve a session-generated image file (tavern or item PNG)."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    image_path = AGENT_PROFILES_DIR / "images" / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(image_path))


# WebSocket endpoint -- session ID in URL path for reconnect persistence
app.add_api_websocket_route("/ws/{session_id}", websocket_endpoint)


def run_server():
    """Entry point for `poetry run start`. Reads port from settings.toml."""
    config = load_config()
    port = config.get("server", {}).get("port", 8000)
    uvicorn.run("server.app:app", host="127.0.0.1", port=port, reload=False)
