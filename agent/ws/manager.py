"""
WebSocket connection manager — broadcasts real-time events to all
connected dashboard clients.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Send an event to all connected clients."""
        payload = json.dumps({
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass

    async def send_to(self, ws: WebSocket, event_type: str, data: dict) -> None:
        """Send an event to a specific client."""
        payload = json.dumps({
            "event_type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await ws.send_text(payload)
