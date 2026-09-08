"""
JobForge — FastAPI Application Entry Point
Run: uvicorn main:app --reload --port 8000
"""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import init_db
from core.websocket import ws_manager
from api.routes import health, profile, jobs, applications

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables. Shutdown: cleanup."""
    log.info("jobforge.startup", llm=settings.llm_base_url, model=settings.llm_model_smart)
    await init_db()
    log.info("jobforge.db_ready")
    yield
    log.info("jobforge.shutdown")


app = FastAPI(
    title="JobForge API",
    description="AI-powered job search, ranking, and application platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routes ──────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(profile.router)
app.include_router(jobs.router)
app.include_router(applications.router)


# ─── WebSocket — real-time agent activity feed ───────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Connect to this from the frontend to receive real-time agent events.

    Event shape:
    {
      "event": "agent_event",
      "data": {
        "agent": "search|rank|docgen|apply|research|coordinator",
        "status": "started|thinking|done|error",
        "message": "Human readable message",
        "extra": {}
      }
    }
    """
    await ws_manager.connect(websocket)
    log.info("ws.client_connected")
    try:
        while True:
            # Keep connection alive — frontend can send ping messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        log.info("ws.client_disconnected")


@app.get("/")
async def root():
    return {
        "app": "JobForge",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "ws://localhost:8000/ws",
    }
