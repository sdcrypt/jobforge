"""
JobForge — WebSocket manager
Broadcasts real-time agent events to all connected frontend clients.
"""

import json
import asyncio
from typing import Any
from fastapi import WebSocket
from redis.asyncio import Redis
import structlog
from core.config import settings

log = structlog.get_logger()
EVENT_CHANNEL = "jobforge:agent-events"


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
        job_id: str | None = None,
        persist: bool = True,
    ):
        """Structured event for agent activity feed in the UI."""
        if not persist:
            await self.broadcast("agent_event", {"agent": agent, "status": status, "message": message, "extra": data or {}})
            return
        from core import database
        from core.runs import current_run
        from models.application import AgentEvent
        context = current_run.get()
        event = AgentEvent(agent=agent, status=status, message=message, extra=data or {},
                           job_id=job_id, run_id=context[0] if context else None)
        async with database.AsyncSessionLocal() as db:
            db.add(event)
            await db.commit()
        payload = {
            "id": event.id, "agent": agent, "status": status, "message": message,
            "extra": data or {}, "run_id": event.run_id,
            "created_at": event.created_at.isoformat() + "Z",
        }
        try:
            async with Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2) as redis:
                await redis.publish(EVENT_CHANNEL, json.dumps(payload, default=str))
        except Exception as exc:
            log.warning("events.publish_failed", error=str(exc))

    async def listen(self):
        while True:
            try:
                async with Redis.from_url(settings.redis_url, socket_connect_timeout=2) as redis:
                    async with redis.pubsub() as subscription:
                        await subscription.subscribe(EVENT_CHANNEL)
                        async for message in subscription.listen():
                            if message["type"] == "message":
                                await self.broadcast("agent_event", json.loads(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("events.subscription_failed", error=str(exc))
                await asyncio.sleep(3)


# Singleton — imported everywhere
ws_manager = ConnectionManager()
