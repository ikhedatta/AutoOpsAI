"""
LogQL query helper — talks to the existing Loki instance.

Provides log queries with configurable time windows, label discovery,
and error-pattern searching for log-pattern anomaly detection.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from agent.models import LogEntry

logger = logging.getLogger(__name__)


class LokiClient:

    def __init__(self, base_url: str = "http://localhost:3100", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout, verify=False)

    # ------------------------------------------------------------------
    # Log queries
    # ------------------------------------------------------------------

    async def query(
        self,
        logql: str,
        limit: int = 100,
        duration_minutes: int = 30,
        direction: str = "backward",
    ) -> list[LogEntry]:
        """Run a LogQL query and return parsed log entries.

        Args:
            logql: LogQL expression, e.g. '{container="nginx"} |= "error"'
            limit: max log lines to return
            duration_minutes: how far back to query
            direction: "backward" (newest first) or "forward" (oldest first)
        """
        # Sanitize common LLM-generated bad patterns: =~".*" → =~".+"
        logql = re.sub(r'=~\s*"(\.\*)"', '=~".+"', logql)
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=duration_minutes)
        try:
            resp = await self._http.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "limit": str(limit),
                    "start": str(int(start.timestamp() * 1_000_000_000)),
                    "end": str(int(now.timestamp() * 1_000_000_000)),
                    "direction": direction,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            entries: list[LogEntry] = []
            for stream in data.get("data", {}).get("result", []):
                labels = stream.get("stream", {})
                source = labels.get("container") or labels.get("job") or "loki"
                for ts, line in stream.get("values", []):
                    # Loki timestamps are nanoseconds — convert to datetime
                    try:
                        ts_dt = datetime.fromtimestamp(int(ts) / 1_000_000_000, tz=timezone.utc)
                    except (ValueError, OSError):
                        ts_dt = None
                    entries.append(LogEntry(
                        timestamp=ts_dt,
                        message=line,
                        source=source,
                        level=_guess_level(line),
                    ))
            return entries
        except Exception:
            logger.warning("Loki query failed: %s", logql, exc_info=True)
            return []

    async def query_raw(
        self,
        logql: str,
        limit: int = 100,
        duration_minutes: int = 30,
    ) -> list[dict[str, Any]]:
        """Return raw Loki stream results (labels + values) without parsing."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=duration_minutes)
        try:
            resp = await self._http.get(
                f"{self.base_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "limit": str(limit),
                    "start": str(int(start.timestamp() * 1_000_000_000)),
                    "end": str(int(now.timestamp() * 1_000_000_000)),
                    "direction": "backward",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("result", [])
        except Exception:
            logger.warning("Loki raw query failed: %s", logql, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Label discovery
    # ------------------------------------------------------------------

    async def get_labels(self) -> list[str]:
        """Get all label names in Loki."""
        try:
            resp = await self._http.get(f"{self.base_url}/loki/api/v1/labels")
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception:
            logger.warning("Loki get_labels failed", exc_info=True)
            return []

    async def get_label_values(self, label: str) -> list[str]:
        """Get all values for a given label."""
        try:
            resp = await self._http.get(
                f"{self.base_url}/loki/api/v1/label/{label}/values"
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception:
            logger.warning("Loki get_label_values(%s) failed", label, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/ready")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._http.aclose()


def _guess_level(line: str) -> str:
    """Best-effort log level extraction from a log line."""
    lower = line[:200].lower()
    for level in ("fatal", "panic", "error", "warn", "info", "debug"):
        if level in lower:
            return level
    return "info"
