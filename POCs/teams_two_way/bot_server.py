"""
Bot Framework server: receives inbound activities from Teams.

This is the HTTP endpoint that Teams (via Azure Bot Service) calls
when a user sends a message or clicks a button in the channel.

Two types of inbound activity we care about:
  1. message — user typed text (commands like /status, /incidents)
  2. message with value — user clicked an Adaptive Card Action.Submit button

For the two-way POC, this server also pushes proactive messages back
to Teams using the webhook module.

Run (standalone):
    uv run python -m POCs.teams_two_way.bot_server

Run (with uvicorn):
    uv run uvicorn POCs.teams_two_way.bot_server:app --port 3978
"""

from __future__ import annotations

import POCs.env  # noqa: F401 — load .env

import os
import traceback

from aiohttp import web
from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes

from .bot_handler import ActionRouter, ActionType, BotResponse, InboundAction
from .webhook import TeamsWebhook

# --- Configuration -----------------------------------------------------------

APP_ID = os.getenv("TEAMS_APP_ID", "")
APP_PASSWORD = os.getenv("TEAMS_APP_PASSWORD", "")
WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

if not APP_ID or not APP_PASSWORD:
    import warnings
    warnings.warn(
        "TEAMS_APP_ID and TEAMS_APP_PASSWORD not set. "
        "Bot Framework auth will be disabled (local dev mode only).",
        stacklevel=2,
    )

# --- Bot Framework adapter ---------------------------------------------------

settings = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
adapter = BotFrameworkAdapter(settings)

# --- Conversation reference store (for proactive messaging) ------------------

# Stores conversation references keyed by conversation ID.
# Backed by MongoDB when available, with in-memory cache.
_conversation_references: dict[str, dict] = {}

_db_available = False
try:
    from POCs.persistence import health_check as _db_health, get_db
    _db_available = _db_health()
except Exception:
    pass


def _save_conversation_reference(activity: Activity):
    """Capture the conversation reference so we can send proactive messages later."""
    ref = TurnContext.get_conversation_reference(activity)
    _conversation_references[ref.conversation.id] = ref
    if _db_available:
        try:
            from POCs.persistence import get_db
            get_db()["conversation_refs"].replace_one(
                {"conversation_id": ref.conversation.id},
                {"conversation_id": ref.conversation.id, "ref": ref.as_dict()},
                upsert=True,
            )
        except Exception:
            pass  # Non-critical


async def send_proactive_message(conversation_id: str, text: str | None = None, card: dict | None = None):
    """
    Send a proactive message to a previously-seen conversation.

    Use this to push outcome cards back to the thread where the user
    clicked Approve/Deny, even if the current turn has already ended.
    """
    ref = _conversation_references.get(conversation_id)
    if not ref:
        raise ValueError(f"No conversation reference stored for {conversation_id}")

    async def _callback(turn_context: TurnContext):
        if text:
            await turn_context.send_activity(text)
        if card:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[{
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }],
                )
            )

    await adapter.continue_conversation(ref, _callback, APP_ID)


# --- Action router with platform handlers ------------------------------------

router = ActionRouter()
webhook = TeamsWebhook(WEBHOOK_URL) if WEBHOOK_URL else None


@router.on_action(ActionType.APPROVE)
async def handle_approve(action: InboundAction) -> BotResponse:
    """Handle an approval from Teams."""
    msg = (
        f"✅ **Approved** by {action.user_name}\n\n"
        f"Incident `{action.incident_id}` — remediation will execute now."
    )
    # In production, this would trigger the remediation pipeline
    # and then push an outcome card back via webhook
    return BotResponse(text=msg)


@router.on_action(ActionType.DENY)
async def handle_deny(action: InboundAction) -> BotResponse:
    msg = (
        f"❌ **Denied** by {action.user_name}\n\n"
        f"Incident `{action.incident_id}` — remediation cancelled. "
        f"Incident logged for manual review."
    )
    return BotResponse(text=msg)


@router.on_action(ActionType.INVESTIGATE)
async def handle_investigate(action: InboundAction) -> BotResponse:
    msg = (
        f"🔍 **Investigating** — {action.user_name} requested more info.\n\n"
        f"Incident `{action.incident_id}` — collecting diagnostics..."
    )
    return BotResponse(text=msg)


@router.on_command("status")
async def handle_status(action: InboundAction) -> BotResponse:
    return BotResponse(text="🟢 AutoOps AI platform is **online**. Pipeline ready.")


@router.on_command("incidents")
async def handle_incidents(action: InboundAction) -> BotResponse:
    return BotResponse(
        text="📋 **Recent Incidents**\n\n"
             "| ID | Container | Status |\n"
             "|---|---|---|\n"
             "| INC-001 | mongodb | resolved |\n"
             "| INC-002 | redis | awaiting approval |\n\n"
             "_This is a demo response. In production, this queries the incident store._"
    )


@router.on_command("help")
async def handle_help(action: InboundAction) -> BotResponse:
    return BotResponse(
        text="🤖 **AutoOps AI Commands**\n\n"
             "- `/status` — Check platform health\n"
             "- `/incidents` — List recent incidents\n"
             "- `/help` — Show this message\n\n"
             "You can also respond to Adaptive Card alerts with Approve/Deny/Investigate buttons."
    )


# --- Error handler -----------------------------------------------------------

async def on_error(context: TurnContext, error: Exception):
    print(f"[bot error] {error}")
    traceback.print_exc()
    await context.send_activity("Sorry, something went wrong on my end.")


adapter.on_turn_error = on_error


# --- Activity handler --------------------------------------------------------

async def handle_turn(turn_context: TurnContext):
    """Process an incoming Teams activity."""
    activity = turn_context.activity

    # Capture conversation reference for proactive messaging
    _save_conversation_reference(activity)

    if activity.type != ActivityTypes.message:
        return

    # Check if this is a card action (Action.Submit sends data in activity.value)
    if activity.value:
        user_name = activity.from_property.name if activity.from_property else "Unknown"
        user_id = activity.from_property.id if activity.from_property else ""

        response = await router.handle_card_action(
            data=activity.value,
            user_name=user_name,
            user_id=user_id,
        )
        if response.text:
            await turn_context.send_activity(response.text)
        if response.card:
            await turn_context.send_activity(
                Activity(
                    type=ActivityTypes.message,
                    attachments=[{
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": response.card,
                    }],
                )
            )
        return

    # Text message — check for commands first
    user_text = activity.text or ""
    user_name = activity.from_property.name if activity.from_property else "Unknown"
    user_id = activity.from_property.id if activity.from_property else ""

    response = await router.handle_text(user_text, user_name, user_id)
    if response.text:
        await turn_context.send_activity(response.text)
        return

    # No command matched — default response
    await turn_context.send_activity(
        "I didn't recognize that command. Type `/help` to see available commands."
    )


# --- aiohttp web app ---------------------------------------------------------

async def messages(req: web.Request) -> web.Response:
    """Bot Framework messages endpoint."""
    if req.content_type != "application/json":
        return web.Response(status=415)

    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    response = await adapter.process_activity(activity, auth_header, handle_turn)
    if response:
        return web.json_response(data=response.body, status=response.status)
    return web.Response(status=201)


async def health(req: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "webhook_configured": bool(WEBHOOK_URL)})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_get("/health", health)
    return app


if __name__ == "__main__":
    print("Starting AutoOps AI Bot Server on port 3978...")
    print(f"  Webhook URL: {'configured' if WEBHOOK_URL else 'not set'}")
    print(f"  Bot App ID: {'configured' if APP_ID else 'not set (local dev mode)'}")
    web.run_app(create_app(), host="0.0.0.0", port=3978)
