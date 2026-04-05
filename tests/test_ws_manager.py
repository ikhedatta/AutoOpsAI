"""Tests for agent.ws.manager — WebSocket connection manager."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.ws.manager import ConnectionManager


class TestConnectionManager:
    def test_initial_state(self):
        mgr = ConnectionManager()
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_connect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        ws.accept.assert_awaited_once()
        assert mgr.client_count == 1

    @pytest.mark.asyncio
    async def test_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        await mgr.broadcast("test_event", {"key": "value"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

        # Verify payload structure
        payload = json.loads(ws1.send_text.call_args[0][0])
        assert payload["event_type"] == "test_event"
        assert payload["data"] == {"key": "value"}
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_broadcast_removes_stale(self):
        mgr = ConnectionManager()
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text.side_effect = Exception("connection closed")

        await mgr.connect(good_ws)
        await mgr.connect(bad_ws)
        assert mgr.client_count == 2

        await mgr.broadcast("test", {})
        # Stale connection should be removed
        assert mgr.client_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_empty(self):
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast("test", {})

    @pytest.mark.asyncio
    async def test_send_to_specific(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.send_to(ws, "specific_event", {"id": "123"})

        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["event_type"] == "specific_event"

    @pytest.mark.asyncio
    async def test_multiple_connects_and_disconnects(self):
        mgr = ConnectionManager()
        clients = [AsyncMock() for _ in range(5)]
        for ws in clients:
            await mgr.connect(ws)
        assert mgr.client_count == 5

        for ws in clients[:3]:
            mgr.disconnect(ws)
        assert mgr.client_count == 2
