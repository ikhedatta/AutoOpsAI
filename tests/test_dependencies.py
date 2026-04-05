"""Tests for agent.api.dependencies — API key verification."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.api.dependencies import verify_api_key
from agent.config import Settings
from fastapi import HTTPException


class TestVerifyApiKey:
    @pytest.mark.asyncio
    async def test_no_key_configured_allows_all(self):
        with patch("agent.api.dependencies.get_settings") as mock_settings:
            mock_settings.return_value = Settings(api_key="", _env_file=None)
            # Should not raise
            await verify_api_key(x_api_key="")
            await verify_api_key(x_api_key="anything")

    @pytest.mark.asyncio
    async def test_valid_key_passes(self):
        with patch("agent.api.dependencies.get_settings") as mock_settings:
            mock_settings.return_value = Settings(api_key="secret123", _env_file=None)
            await verify_api_key(x_api_key="secret123")

    @pytest.mark.asyncio
    async def test_invalid_key_raises_403(self):
        with patch("agent.api.dependencies.get_settings") as mock_settings:
            mock_settings.return_value = Settings(api_key="secret123", _env_file=None)
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="wrong_key")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_key_when_required_raises_403(self):
        with patch("agent.api.dependencies.get_settings") as mock_settings:
            mock_settings.return_value = Settings(api_key="secret123", _env_file=None)
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="")
            assert exc_info.value.status_code == 403
