"""
Ollama LLM client — local inference, no data leaves the network.

Wraps the ``ollama`` Python SDK with structured output parsing,
retries, fallback model support, and graceful degradation when
Ollama is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import ollama
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import Settings
from agent.llm.prompts import (
    chat_prompt,
    diagnosis_prompt,
    novel_issue_prompt,
    summary_prompt,
)
from agent.models import Diagnosis

logger = logging.getLogger(__name__)


class LLMClient:

    def __init__(self, settings: Settings):
        self.host = settings.ollama_host
        self.model = settings.ollama_model
        self.fallback_model = settings.ollama_fallback_model
        self.timeout = settings.ollama_timeout
        self._client = ollama.Client(host=self.host, timeout=self.timeout)
        self._available: bool | None = None  # lazy check

    # -- health --------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            await asyncio.to_thread(self._client.list)
            self._available = True
        except Exception:
            self._available = False
        return self._available

    async def warm_up(self) -> None:
        """Pre-load the model into memory."""
        try:
            await asyncio.to_thread(
                self._client.chat,
                model=self.model,
                messages=[{"role": "user", "content": "ping"}],
            )
            logger.info("Ollama model '%s' warmed up", self.model)
        except Exception:
            logger.warning("Ollama warm-up failed — will retry on first real call", exc_info=True)

    # -- core chat -----------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def _chat_sync(self, messages: list[dict], *, use_json: bool = False) -> str:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if use_json:
            kwargs["format"] = "json"
        try:
            resp = self._client.chat(**kwargs)
        except Exception:
            # Try fallback model once
            logger.warning("Primary model failed, trying fallback '%s'", self.fallback_model)
            kwargs["model"] = self.fallback_model
            resp = self._client.chat(**kwargs)
        return resp["message"]["content"]

    async def _chat(self, messages: list[dict], *, use_json: bool = False) -> str:
        """Run synchronous Ollama chat in a thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self._chat_sync, messages, use_json=use_json)

    async def _chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream tokens from Ollama without blocking the event loop."""
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _run() -> None:
            try:
                try:
                    stream = self._client.chat(**kwargs)
                except Exception:
                    logger.warning("Primary model stream failed, trying fallback '%s'", self.fallback_model)
                    kwargs["model"] = self.fallback_model
                    stream = self._client.chat(**kwargs)

                for chunk in stream:
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        loop.call_soon_threadsafe(queue.put_nowait, token)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.get_event_loop().run_in_executor(None, _run)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    async def chat_stream(
        self,
        question: str,
        system_state: dict[str, Any],
        incident_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Interactive streaming chat — yields tokens as they arrive."""
        messages = chat_prompt(question, system_state, incident_context)
        async for token in self._chat_stream(messages):
            yield token

    def _parse_json(self, text: str) -> dict:
        """Extract JSON from LLM output (handles markdown code fences)."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from code fence
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Last resort: find first { ... }
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse JSON from LLM output: %s", text[:200])
        return {}

    # -- high-level methods --------------------------------------------------

    async def diagnose(
        self,
        anomaly: dict[str, Any],
        metrics: dict[str, Any],
        playbook_context: str | None = None,
        logs: list[str] | None = None,
    ) -> Diagnosis:
        """Call LLM to diagnose an anomaly.  Returns structured Diagnosis."""
        messages = diagnosis_prompt(anomaly, metrics, playbook_context, logs)
        try:
            raw = await self._chat(messages, use_json=True)
            data = self._parse_json(raw)
            return Diagnosis(
                summary=data.get("summary", "Unknown issue"),
                explanation=data.get("explanation", raw),
                confidence=float(data.get("confidence", 0.5)),
                root_cause=data.get("root_cause"),
                recommended_actions=data.get("recommended_actions", []),
            )
        except Exception:
            logger.warning("LLM diagnosis failed", exc_info=True)
            return Diagnosis(
                summary=f"Anomaly on {anomaly.get('service_name', 'unknown')}",
                explanation="LLM diagnosis unavailable — falling back to playbook diagnosis.",
                confidence=0.3,
            )

    async def reason_novel_issue(
        self,
        metrics: dict[str, Any],
        logs: list[str] | None = None,
        prometheus_context: str | None = None,
    ) -> Diagnosis:
        """Diagnose a novel issue with no playbook match."""
        messages = novel_issue_prompt(metrics, logs, prometheus_context)
        try:
            raw = await self._chat(messages, use_json=True)
            data = self._parse_json(raw)
            return Diagnosis(
                summary=data.get("summary", "Unknown anomaly"),
                explanation=data.get("explanation", raw),
                confidence=float(data.get("confidence", 0.3)),
                root_cause=data.get("root_cause"),
                recommended_actions=data.get("recommended_actions", []),
                novel=True,
            )
        except Exception:
            logger.warning("LLM novel reasoning failed", exc_info=True)
            return Diagnosis(
                summary="Unknown anomaly detected",
                explanation="LLM unavailable. Manual investigation required.",
                confidence=0.1,
                novel=True,
            )

    async def generate_summary(self, incident: dict[str, Any]) -> str:
        """Generate a conversational incident summary for the dashboard."""
        messages = summary_prompt(incident)
        try:
            return await self._chat(messages)
        except Exception:
            return f"Incident on {incident.get('service_name', 'unknown')}: {incident.get('diagnosis_summary', 'N/A')}"

    async def chat(
        self,
        question: str,
        system_state: dict[str, Any],
        incident_context: dict[str, Any] | None = None,
    ) -> str:
        """Interactive chat — operator asks the agent about system state."""
        messages = chat_prompt(question, system_state, incident_context)
        try:
            return await self._chat(messages)
        except Exception:
            logger.warning("LLM chat failed", exc_info=True)
            return "I'm having trouble connecting to my reasoning engine. Please try again."
