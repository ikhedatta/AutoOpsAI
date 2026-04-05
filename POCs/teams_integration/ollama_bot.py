"""
Ollama-powered DevOps assistant bot logic.
Handles incoming messages and generates responses using local Ollama.
"""

import POCs.env  # noqa: F401 — load .env

import os

import httpx

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")

SYSTEM_PROMPT = """\
You are AutoOps AI, a DevOps operations assistant running inside Microsoft Teams.
You help engineers investigate and resolve infrastructure incidents.

Your capabilities:
- Analyze metrics snapshots and log excerpts
- Diagnose container, database, and networking issues
- Suggest remediation steps with risk levels (LOW / MEDIUM / HIGH)
- Explain what happened in plain language

Rules:
- Be concise. Teams messages should be scannable.
- Use bullet points for multi-step answers.
- Always state the risk level when suggesting actions.
- If you don't have enough information, ask clarifying questions.
- Never fabricate metrics — only reason about data the user provides.
"""


async def health_check() -> bool:
    """Check if Ollama is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{OLLAMA_BASE}/api/tags")
            return resp.status_code == 200
    except httpx.ConnectError:
        return False


async def chat(user_message: str, conversation_history: list[dict] | None = None) -> str:
    """Send a message to Ollama and return the assistant response."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": MODEL, "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
