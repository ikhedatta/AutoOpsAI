"""
MongoDB persistence layer for AutoOps AI.

Provides a shared async-friendly MongoDB client and typed collection
accessors for incident history, audit logs, and conversation state.

All modules should import from here instead of creating their own
pymongo clients.

Usage:
    from POCs.persistence import get_db, collections

    db = get_db()
    db.incidents.insert_one({...})
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

import POCs.env  # noqa: F401 — load .env

logger = logging.getLogger("autoopsai.persistence")

# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: MongoClient | None = None


def get_client() -> MongoClient:
    """Return the shared MongoClient, creating it on first call."""
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        _client = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
    return _client


def get_db() -> Database:
    """Return the application database."""
    db_name = os.getenv("MONGODB_DATABASE", "autoopsai")
    return get_client()[db_name]


def health_check() -> bool:
    """Return True if MongoDB is reachable."""
    try:
        get_client().admin.command("ping")
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError):
        return False


def close():
    """Close the shared client (call at shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def incidents_collection() -> Collection:
    return get_db()["incidents"]


def audit_collection() -> Collection:
    return get_db()["audit_log"]


def conversations_collection() -> Collection:
    return get_db()["conversations"]


def pipeline_runs_collection() -> Collection:
    return get_db()["pipeline_runs"]


# ---------------------------------------------------------------------------
# Ensure indexes (call once at startup)
# ---------------------------------------------------------------------------

def ensure_indexes() -> None:
    """Create indexes for common query patterns."""
    try:
        inc = incidents_collection()
        inc.create_index("incident_id", unique=True)
        inc.create_index("resolved_at")
        inc.create_index([("context.symptom", pymongo.TEXT)])
        inc.create_index("context.container")
        inc.create_index("playbook_id")

        audit = audit_collection()
        audit.create_index("incident_id")
        audit.create_index("timestamp")
        audit.create_index("action")
        audit.create_index("session_id")

        conv = conversations_collection()
        conv.create_index("conversation_id", unique=True)
        conv.create_index("updated_at")

        runs = pipeline_runs_collection()
        runs.create_index("incident_id")
        runs.create_index("started_at")

        logger.info("MongoDB indexes ensured")
    except Exception:
        logger.warning("Could not ensure MongoDB indexes — database may be unavailable", exc_info=True)


# ---------------------------------------------------------------------------
# CRUD helpers — Incidents
# ---------------------------------------------------------------------------

def save_incident(incident_dict: dict[str, Any]) -> None:
    """Upsert a resolved incident into MongoDB."""
    try:
        incidents_collection().replace_one(
            {"incident_id": incident_dict["incident_id"]},
            incident_dict,
            upsert=True,
        )
    except Exception:
        logger.warning("Failed to save incident %s", incident_dict.get("incident_id"), exc_info=True)


def find_similar_incidents(
    symptom: str,
    container: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search incidents by text symptom and optional container filter."""
    try:
        query: dict[str, Any] = {"$text": {"$search": symptom}}
        if container:
            query["context.container"] = container
        cursor = (
            incidents_collection()
            .find(query, {"score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        return list(cursor)
    except Exception:
        logger.warning("Failed to search incidents", exc_info=True)
        return []


def get_playbook_stats(playbook_id: str) -> dict[str, Any]:
    """Aggregate stats for a playbook from incident history."""
    try:
        pipeline = [
            {"$match": {"playbook_id": playbook_id}},
            {"$group": {
                "_id": "$playbook_id",
                "usage_count": {"$sum": 1},
                "success_count": {
                    "$sum": {"$cond": [{"$eq": ["$status", "resolved"]}, 1, 0]}
                },
                "avg_resolution_time": {"$avg": "$resolution_time_seconds"},
            }},
        ]
        results = list(incidents_collection().aggregate(pipeline))
        if results:
            r = results[0]
            return {
                "playbook_id": playbook_id,
                "usage_count": r["usage_count"],
                "success_count": r["success_count"],
                "success_rate": r["success_count"] / r["usage_count"] if r["usage_count"] else 0,
                "avg_resolution_time_seconds": r.get("avg_resolution_time", 0) or 0,
            }
    except Exception:
        logger.warning("Failed to get playbook stats for %s", playbook_id, exc_info=True)
    return {
        "playbook_id": playbook_id,
        "usage_count": 0,
        "success_count": 0,
        "success_rate": 0.0,
        "avg_resolution_time_seconds": 0.0,
    }


# ---------------------------------------------------------------------------
# CRUD helpers — Audit Log
# ---------------------------------------------------------------------------

def append_audit_entry(entry_dict: dict[str, Any]) -> None:
    """Insert an audit log entry."""
    try:
        audit_collection().insert_one(entry_dict)
    except Exception:
        logger.warning("Failed to write audit entry", exc_info=True)


def get_incident_audit_trail(incident_id: str) -> list[dict]:
    """Retrieve the full audit trail for an incident."""
    try:
        return list(
            audit_collection()
            .find({"incident_id": incident_id})
            .sort("timestamp", pymongo.ASCENDING)
        )
    except Exception:
        logger.warning("Failed to read audit trail for %s", incident_id, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# CRUD helpers — Conversations (Teams bot)
# ---------------------------------------------------------------------------

def save_conversation(conversation_id: str, messages: list[dict]) -> None:
    """Persist conversation history for a Teams conversation."""
    try:
        max_history = int(os.getenv("MAX_CONVERSATION_HISTORY", "20"))
        conversations_collection().replace_one(
            {"conversation_id": conversation_id},
            {
                "conversation_id": conversation_id,
                "messages": messages[-max_history:],
                "updated_at": datetime.now(timezone.utc),
            },
            upsert=True,
        )
    except Exception:
        logger.warning("Failed to save conversation %s", conversation_id, exc_info=True)


def load_conversation(conversation_id: str) -> list[dict]:
    """Load conversation history."""
    try:
        doc = conversations_collection().find_one({"conversation_id": conversation_id})
        if doc:
            return doc.get("messages", [])
    except Exception:
        logger.warning("Failed to load conversation %s", conversation_id, exc_info=True)
    return []


def delete_conversation(conversation_id: str) -> None:
    """Clear a conversation."""
    try:
        conversations_collection().delete_one({"conversation_id": conversation_id})
    except Exception:
        logger.warning("Failed to delete conversation %s", conversation_id, exc_info=True)


# ---------------------------------------------------------------------------
# CRUD helpers — Pipeline Runs
# ---------------------------------------------------------------------------

def save_pipeline_run(run_dict: dict[str, Any]) -> None:
    """Save a pipeline run record (E2E incident processing result)."""
    try:
        pipeline_runs_collection().replace_one(
            {"incident_id": run_dict["incident_id"]},
            run_dict,
            upsert=True,
        )
    except Exception:
        logger.warning("Failed to save pipeline run %s", run_dict.get("incident_id"), exc_info=True)
