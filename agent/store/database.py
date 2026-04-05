"""
Async MongoDB connection management via Motor + Beanie ODM.
"""

from __future__ import annotations

import logging

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from agent.config import Settings

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None


async def init_db(settings: Settings) -> AsyncIOMotorClient:
    """Initialise Motor client and Beanie document models."""
    global _client

    from agent.store.models import ALL_DOCUMENTS

    _client = AsyncIOMotorClient(settings.mongodb_url)
    try:
        default_db = _client.get_default_database()
        db_name = default_db.name
    except Exception:
        db_name = "autoops"
    db = _client[db_name]

    await init_beanie(database=db, document_models=ALL_DOCUMENTS)
    logger.info("MongoDB connected: %s / %s", settings.mongodb_url.split("@")[-1], db_name)
    return _client


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")


async def health_check() -> bool:
    if not _client:
        return False
    try:
        await _client.admin.command("ping")
        return True
    except Exception:
        return False
