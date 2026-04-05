"""
Microsoft Teams Bot integration using Bot Framework SDK.

This is the Teams-facing webhook server. It receives activities from
the Bot Framework channel and delegates to the Ollama-powered assistant.

Setup:
  1. Register a Bot in Azure Bot Service (or use Bot Framework Emulator for local dev)
  2. Set APP_ID and APP_PASSWORD environment variables
  3. Run: uv run uvicorn POCs.teams_integration.teams_app:app --port 3978
  4. Expose via ngrok (or dev tunnel) for Teams to reach your local server
"""

import POCs.env  # noqa: F401 — load .env

import os
import traceback

from aiohttp import web
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.integration.aiohttp import BotFrameworkHttpClient
from botbuilder.schema import Activity, ActivityTypes

from . import ollama_bot

# --- Bot Framework adapter ---------------------------------------------------

APP_ID = os.getenv("TEAMS_APP_ID", "")
APP_PASSWORD = os.getenv("TEAMS_APP_PASSWORD", "")

if not APP_ID or not APP_PASSWORD:
    import warnings
    warnings.warn(
        "TEAMS_APP_ID and TEAMS_APP_PASSWORD not set. "
        "Bot Framework auth will be disabled (local dev mode only).",
        stacklevel=2,
    )

settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(settings)

# Per-conversation history (in-memory for POC)
_histories: dict[str, list[dict]] = {}
MAX_HISTORY = 20  # keep last N messages per conversation


async def on_error(context: TurnContext, error: Exception):
    print(f"[bot error] {error}")
    traceback.print_exc()
    await context.send_activity("Sorry, something went wrong on my end.")


adapter.on_turn_error = on_error

# Per-conversation history: backed by MongoDB with in-memory cache
_histories: dict[str, list[dict]] = {}
MAX_HISTORY = int(os.getenv("MAX_CONVERSATION_HISTORY", "20"))

_db_available = False
try:
    from POCs.persistence import (
        health_check as _db_health,
        load_conversation,
        save_conversation,
        delete_conversation,
    )
    _db_available = _db_health()
except Exception:
    pass


def _get_history(conv_id: str) -> list[dict]:
    """Load conversation history from cache or MongoDB."""
    if conv_id in _histories:
        return _histories[conv_id]
    if _db_available:
        history = load_conversation(conv_id)
        _histories[conv_id] = history
        return history
    return []


def _save_history(conv_id: str, history: list[dict]) -> None:
    """Save conversation history to cache and MongoDB."""
    trimmed = history[-MAX_HISTORY:]
    _histories[conv_id] = trimmed
    if _db_available:
        save_conversation(conv_id, trimmed)


def _clear_history(conv_id: str) -> None:
    """Clear conversation history from cache and MongoDB."""
    _histories.pop(conv_id, None)
    if _db_available:
        delete_conversation(conv_id)


# --- Message handler ----------------------------------------------------------

async def handle_message(turn_context: TurnContext):
    """Process an incoming Teams message."""
    if turn_context.activity.type != ActivityTypes.message:
        return

    user_text = turn_context.activity.text or ""
    conv_id = turn_context.activity.conversation.id

    # Simple commands
    if user_text.strip().lower() in ("/health", "/status"):
        ok = await ollama_bot.health_check()
        status = "Ollama is **running**." if ok else "Ollama is **unreachable**."
        await turn_context.send_activity(status)
        return

    if user_text.strip().lower() in ("/clear", "/reset"):
        _clear_history(conv_id)
        await turn_context.send_activity("Conversation history cleared.")
        return

    # Send typing indicator
    await turn_context.send_activity(Activity(type=ActivityTypes.typing))

    # Build conversation history
    history = _get_history(conv_id)

    try:
        reply = await ollama_bot.chat(user_text, history)
    except Exception as exc:
        await turn_context.send_activity(f"Error contacting Ollama: {exc}")
        return

    # Update history
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    _save_history(conv_id, history)

    await turn_context.send_activity(reply)


# --- aiohttp web app (Bot Framework webhook) ---------------------------------

async def messages(req: web.Request) -> web.Response:
    """Bot Framework messages endpoint."""
    if req.content_type == "application/json":
        body = await req.json()
    else:
        return web.Response(status=415)

    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    response = await adapter.process_activity(activity, auth_header, handle_message)
    if response:
        return web.json_response(data=response.body, status=response.status)
    return web.Response(status=201)


def create_aiohttp_app() -> web.Application:
    """Create the aiohttp web application with Bot Framework endpoint."""
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    return app


# --- FastAPI wrapper for convenience ------------------------------------------
# You can run either the aiohttp app directly or this FastAPI wrapper.

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="AutoOps AI — Teams Bot")


@app.post("/api/messages")
async def fastapi_messages(request: Request):
    """Bot Framework messages endpoint (FastAPI version)."""
    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    response = await adapter.process_activity(activity, auth_header, handle_message)
    if response:
        return JSONResponse(content=response.body, status_code=response.status)
    return JSONResponse(content={}, status_code=201)


@app.get("/health")
async def health():
    ollama_ok = await ollama_bot.health_check()
    return {"status": "ok", "ollama": ollama_ok}


if __name__ == "__main__":
    # Run with aiohttp directly (standard for Bot Framework Python SDK)
    web.run_app(create_aiohttp_app(), host="0.0.0.0", port=3978)
