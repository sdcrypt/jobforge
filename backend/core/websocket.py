"""
JobForge — WebSocket manager
Broadcasts real-time agent events to all connected frontend clients.
"""

import json
from typing import Any
from fastapi import WebSocket
import structlog

log = structlog.get_logger()


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts agent events."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info("websocket.connected", total=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        log.info("websocket.disconnected", total=len(self.active_connections))

    async def broadcast(self, event_type: str, data: Any):
        """Send an agent event to all connected clients."""
        payload = json.dumps({"event": event_type, "data": data})
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def emit_agent_event(
        self,
        agent: str,
        status: str,          # "started" | "thinking" | "done" | "error"
        message: str,
        data: dict | None = None,
    ):
        """Structured event for agent activity feed in the UI."""
        await self.broadcast(
            "agent_event",
            {
                "agent": agent,
                "status": status,
                "message": message,
                "extra": data or {},
            },
        )


# Singleton — imported everywhere
ws_manager = ConnectionManager()
