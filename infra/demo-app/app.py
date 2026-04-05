"""
Demo FastAPI application — the target service that AutoOps AI monitors.

This is NOT part of the agent.  It's a simple REST API backed by
mongodb-demo and demo-redis, designed to break predictably under chaos.
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Demo App", version="1.0.0")

# Lazy connections
_mongo_client = None
_redis_client = None


def _get_mongo():
    global _mongo_client
    if _mongo_client is None:
        from pymongo import MongoClient
        host = os.getenv("MONGODB_HOST", "mongodb-demo")
        port = int(os.getenv("MONGODB_PORT", "27017"))
        _mongo_client = MongoClient(host, port, serverSelectionTimeoutMS=3000)
    return _mongo_client


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        host = os.getenv("REDIS_HOST", "demo-redis")
        port = int(os.getenv("REDIS_PORT", "6379"))
        _redis_client = redis.Redis(host=host, port=port, socket_timeout=3)
    return _redis_client


@app.get("/health")
async def health():
    checks = {}
    try:
        _get_mongo().admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as exc:
        checks["mongodb"] = f"error: {exc}"

    try:
        _get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        {"status": "healthy" if all_ok else "unhealthy", "checks": checks},
        status_code=status_code,
    )


@app.get("/data")
async def get_data():
    try:
        db = _get_mongo()["demo"]
        items = list(db["items"].find({}, {"_id": 0}).limit(10))
        return {"items": items, "count": len(items)}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/cache")
async def get_cache():
    try:
        r = _get_redis()
        key = "demo:counter"
        val = r.incr(key)
        return {"counter": val}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/slow")
async def slow_endpoint():
    """Endpoint that simulates slow processing — useful for CPU stress testing."""
    time.sleep(2)
    return {"message": "done", "delay_seconds": 2}
