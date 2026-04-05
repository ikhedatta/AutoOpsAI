"""
FastAPI dependency functions.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from agent.config import get_settings


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """
    Pre-RBAC static API-key guard on state-changing endpoints.
    If no API_KEY is set in config, all requests are allowed.
    """
    settings = get_settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")
