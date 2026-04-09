"""
GitHub Models LLM client — Azure-hosted inference via GitHub PAT.

Drop-in replacement for the Ollama LLMClient. Uses direct HTTP calls
to ``https://models.inference.ai.azure.com/chat/completions``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import Settings
from agent.llm.prompts import (
    chat_prompt,
    chat_prompt_with_tools,
    diagnosis_prompt,
    novel_issue_prompt,
    summary_prompt,
)
from agent.llm.tools import get_ollama_tool_schemas
from agent.models import Diagnosis

logger = logging.getLogger(__name__)


def _friendly_error_message(exc: Exception) -> str:
    msg = str(exc).lower()
    if "rate limit" in msg or "429" in msg:
        return "GitHub Models rate limit reached. Please wait a moment and try again."
    if "unauthorized" in msg or "401" in msg or "403" in msg:
        return "GitHub token is invalid or expired. Check GITHUB_TOKEN in .env."
    if "timeout" in msg:
        return "The GitHub Models request timed out. Please try again."
    if "connection" in msg or "connect" in msg:
        return "Cannot reach GitHub Models API. Check your network connection."
    return "I'm having trouble connecting to my reasoning engine. Please try again."


class GitHubLLMClient:
    """LLM client backed by GitHub Models (Azure-hosted)."""

    def __init__(self, settings: Settings):
        self.model = settings.github_model
        self.max_tokens = settings.llm_max_tokens
        self.timeout = settings.llm_timeout
        self._endpoint = f"{settings.github_models_endpoint}/chat/completions"
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.github_token}",
        }
        self._session = httpx.Client(
            verify=False,
            timeout=httpx.Timeout(connect=10, read=self.timeout, write=10, pool=10),
        )
        self._available: bool | None = None

    # -- health --------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            resp = await asyncio.to_thread(
                self._session.post,
                self._endpoint,
                headers=self._headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_completion_tokens": 5,
                },
            )
            resp.raise_for_status()
            self._available = True
        except Exception:
            self._available = False
        return self._available

    async def warm_up(self) -> None:
        # Already warmed up by is_available check
        logger.info("GitHub Models '%s' ready", self.model)

    # -- core chat -----------------------------------------------------------

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5), reraise=True)
    def _chat_sync(
        self, messages: list[dict], *, max_tokens: int | None = None,
    ) -> str:
        resp = self._session.post(
            self._endpoint,
            headers=self._headers,
            json={
                "model": self.model,
                "messages": messages,
                "max_completion_tokens": max_tokens or self.max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _chat(
        self, messages: list[dict], *, use_json: bool = False,
    ) -> str:
        if use_json:
            messages = list(messages)
            if messages and messages[0]["role"] == "system":
                messages[0] = {
                    **messages[0],
                    "content": messages[0]["content"]
                    + "\n\nRespond ONLY with valid JSON.",
                }
        return await asyncio.to_thread(self._chat_sync, messages)

    async def _chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _run() -> None:
            try:
                with self._session.stream(
                    "POST",
                    self._endpoint,
                    headers=self._headers,
                    json={
                        "model": self.model,
                        "messages": messages,
                        "max_completion_tokens": self.max_tokens,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                            delta = chunk["choices"][0].get("delta", {})
                            token = delta.get("content", "")
                            if token:
                                loop.call_soon_threadsafe(queue.put_nowait, token)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
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
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        messages = chat_prompt(question, system_state, incident_context, history)
        async for token in self._chat_stream(messages):
            yield token

    def _parse_json(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
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
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = chat_prompt(question, system_state, incident_context, history)
        try:
            return await self._chat(messages)
        except Exception as exc:
            logger.warning("LLM chat failed", exc_info=True)
            return _friendly_error_message(exc)

    # -- tool-augmented chat ------------------------------------------------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _chat_with_tools_sync(
        self, messages: list[dict], tools: list[dict],
    ) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
        resp = self._session.post(
            self._endpoint, headers=self._headers, json=payload,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        # Keep the raw message format for OpenAI API compatibility.
        # The assistant message with tool_calls must include the tool_call ids,
        # and tool role responses must reference them via tool_call_id.
        return msg

    async def chat_with_tools(
        self,
        question: str,
        system_state: dict[str, Any],
        incident_context: dict[str, Any] | None = None,
        *,
        tool_executor: Any = None,
        max_iterations: int = 5,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        if tool_executor is None:
            return await self.chat(question, system_state, incident_context, history)

        messages = chat_prompt_with_tools(question, system_state, incident_context, history)
        tool_schemas = get_ollama_tool_schemas()

        try:
            for iteration in range(max_iterations):
                msg = await asyncio.to_thread(
                    self._chat_with_tools_sync, messages, tool_schemas,
                )

                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    return msg.get("content", "") or ""

                # Add the full assistant message (with tool_calls including ids)
                messages.append(msg)

                # Parse and execute tool calls
                parsed_calls = []
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_call_id = tc.get("id", "")
                    name = func.get("name", "unknown")
                    # Arguments may be a JSON string (OpenAI format) or dict (Ollama)
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    parsed_calls.append((tool_call_id, name, args))

                results = await asyncio.gather(
                    *(tool_executor.execute(name, args) for _, name, args in parsed_calls)
                )

                for (tool_call_id, tool_name, tool_args), result in zip(parsed_calls, results):
                    logger.info(
                        "Tool call [iter=%d]: %s(%s) → success=%s",
                        iteration, tool_name,
                        json.dumps(tool_args, default=str)[:100],
                        result.success,
                    )
                    # OpenAI API requires tool_call_id in tool responses
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result.to_json(),
                    })

            messages.append({
                "role": "user",
                "content": "Please summarise your findings so far in a concise answer.",
            })
            final = await asyncio.to_thread(
                self._chat_with_tools_sync, messages, [],
            )
            return final.get("content", "I couldn't complete the analysis within the allowed steps.")

        except Exception as exc:
            logger.warning("Tool-augmented chat failed, falling back to plain chat", exc_info=True)
            try:
                return await self.chat(question, system_state, incident_context)
            except Exception:
                return _friendly_error_message(exc)

    # -- streaming tool-augmented chat --------------------------------------

    async def _run_tool_loop(
        self,
        messages: list[dict],
        tool_schemas: list[dict],
        tool_executor: Any,
        max_iterations: int,
    ) -> str | None:
        """Execute the tool-calling loop, mutating *messages* in place.

        Returns:
            ``None``  — tools were called; *messages* now contains tool
                        results and is ready for a final streaming call.
            ``str``   — the LLM answered directly (no tools used);
                        the string is the final content.
        """
        for iteration in range(max_iterations):
            msg = await asyncio.to_thread(
                self._chat_with_tools_sync, messages, tool_schemas,
            )

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # LLM produced a final text answer
                return msg.get("content", "") or ""

            messages.append(msg)

            parsed_calls = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_call_id = tc.get("id", "")
                name = func.get("name", "unknown")
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parsed_calls.append((tool_call_id, name, args))

            results = await asyncio.gather(
                *(tool_executor.execute(name, args) for _, name, args in parsed_calls)
            )

            for (tool_call_id, tool_name, tool_args), result in zip(parsed_calls, results):
                logger.info(
                    "Tool call [iter=%d]: %s(%s) → success=%s",
                    iteration, tool_name,
                    json.dumps(tool_args, default=str)[:100],
                    result.success,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result.to_json(),
                })

        # Exhausted iterations — messages has tool results, ready for final call
        return None

    async def chat_stream_with_tools(
        self,
        question: str,
        system_state: dict[str, Any],
        incident_context: dict[str, Any] | None = None,
        *,
        tool_executor: Any = None,
        max_iterations: int = 5,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        """Tool-augmented chat with the final answer streamed token-by-token.

        1. Runs the tool loop (non-streamed) so tools get called.
        2. Streams the final LLM response that incorporates tool results.
        Falls back to plain streaming on any error.
        """
        if tool_executor is None:
            async for token in self.chat_stream(question, system_state, incident_context, history):
                yield token
            return

        messages = chat_prompt_with_tools(question, system_state, incident_context, history)
        tool_schemas = get_ollama_tool_schemas()

        try:
            direct_answer = await self._run_tool_loop(
                messages, tool_schemas, tool_executor, max_iterations,
            )
            if direct_answer is not None:
                # LLM answered without needing to stream (e.g. tools
                # returned results and LLM synthesised in a non-streaming
                # call, or LLM answered directly without tools).
                yield direct_answer
                return

            # Tools were called — messages now has tool results.
            # Stream the final synthesised answer.
            async for token in self._chat_stream(messages):
                yield token

        except Exception:
            logger.warning("Streaming tool chat failed, falling back to plain stream", exc_info=True)
            async for token in self._chat_stream(
                chat_prompt(question, system_state, incident_context, history)
            ):
                yield token
