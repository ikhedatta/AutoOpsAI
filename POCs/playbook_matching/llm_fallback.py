"""
LLM fallback: when no playbook matches an anomaly, use Ollama to reason
about the issue and generate a structured diagnosis + action plan.

Validates that structured JSON output from Ollama is reliable enough
for downstream automation.
"""

from __future__ import annotations

import POCs.env  # noqa: F401 — load .env

import json
import os
import re
from dataclasses import dataclass

import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

SYSTEM_PROMPT = """\
You are AutoOps AI, a DevOps operations agent. You have detected an
anomaly in the infrastructure you're monitoring.

Your task:
1. Explain what's happening in plain language (2-3 sentences)
2. Assess the severity (LOW / MEDIUM / HIGH)
3. Recommend a specific remediation action
4. Explain the rollback plan if the fix doesn't work
5. State what you'll check to verify the fix worked

Respond ONLY with valid JSON in this exact format (no markdown, no extra text):
{
  "diagnosis": "...",
  "severity": "LOW|MEDIUM|HIGH",
  "recommended_action": "...",
  "action_type": "docker_restart|redis_command|collect_logs|escalate",
  "action_target": "container_name",
  "rollback_plan": "...",
  "verification_check": "...",
  "confidence": 0.0-1.0
}
"""


@dataclass
class LLMDiagnosis:
    """Structured diagnosis from the LLM."""
    diagnosis: str
    severity: str
    recommended_action: str
    action_type: str
    action_target: str
    rollback_plan: str
    verification_check: str
    confidence: float
    raw_response: str  # Keep the raw text for debugging


def _build_user_prompt(anomaly_description: str, system_state: dict | None = None) -> str:
    parts = [f"Anomaly detected:\n{anomaly_description}"]
    if system_state:
        state_str = json.dumps(system_state, indent=2, default=str)
        parts.insert(0, f"Current system state:\n{state_str}")
    parts.append("\nNo matching playbook was found for this anomaly. Analyze and respond with JSON.")
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences and extra text."""
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fence
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding the first { ... } block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


REQUIRED_FIELDS = {"diagnosis", "severity", "recommended_action", "action_type",
                   "action_target", "rollback_plan", "verification_check", "confidence"}


def _validate_diagnosis(data: dict) -> LLMDiagnosis | None:
    """Validate that the parsed JSON has all required fields."""
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        return None

    severity = data["severity"].upper()
    if severity not in ("LOW", "MEDIUM", "HIGH"):
        severity = "MEDIUM"  # Safe default

    confidence = data.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    return LLMDiagnosis(
        diagnosis=str(data["diagnosis"]),
        severity=severity,
        recommended_action=str(data["recommended_action"]),
        action_type=str(data["action_type"]),
        action_target=str(data["action_target"]),
        rollback_plan=str(data["rollback_plan"]),
        verification_check=str(data["verification_check"]),
        confidence=confidence,
        raw_response="",
    )


@retry(
    wait=wait_exponential(min=1, max=8),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(httpx.ConnectError),
)
def llm_diagnose(
    anomaly_description: str,
    system_state: dict | None = None,
    model: str = MODEL,
) -> LLMDiagnosis | None:
    """
    Ask the local Ollama model to diagnose an unknown anomaly.

    Returns a structured LLMDiagnosis if the model produces valid JSON,
    or None if the response can't be parsed after retries.
    """
    user_prompt = _build_user_prompt(anomaly_description, system_state)

    resp = httpx.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.2},  # Low temp for structured output
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw_text = resp.json().get("message", {}).get("content", "")

    data = _extract_json(raw_text)
    if data is None:
        return None

    diagnosis = _validate_diagnosis(data)
    if diagnosis:
        diagnosis.raw_response = raw_text
    return diagnosis
