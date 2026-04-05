"""Tests for agent.store.database — connection management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import Settings


class TestDatabaseConnection:
    @pytest.mark.asyncio
    async def test_health_check_no_client(self):
        from agent.store.database import health_check
        with patch("agent.store.database._client", None):
            result = await health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        from agent.store.database import health_check
        mock_client = MagicMock()
        mock_client.admin.command = AsyncMock(return_value={"ok": 1})
        with patch("agent.store.database._client", mock_client):
            result = await health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        from agent.store.database import health_check
        mock_client = MagicMock()
        mock_client.admin.command = AsyncMock(side_effect=Exception("timeout"))
        with patch("agent.store.database._client", mock_client):
            result = await health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_close_db_with_client(self):
        from agent.store import database as db_module
        mock_client = MagicMock()
        with patch.object(db_module, "_client", mock_client):
            await db_module.close_db()
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_db_without_client(self):
        from agent.store import database as db_module
        with patch.object(db_module, "_client", None):
            # Should not raise
            await db_module.close_db()
