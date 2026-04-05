"""
Inbound message handler: Teams → Platform via Bot Framework.

Handles two types of inbound activity:
  1. Text messages — user types commands or questions in the channel
  2. Card action submissions — user clicks Approve/Deny/Investigate on an Adaptive Card

This module provides the logic layer. The server (bot_server.py) wires
it to the Bot Framework adapter.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


class ActionType(Enum):
    APPROVE = "approve"
    DENY = "deny"
    INVESTIGATE = "investigate"
    UNKNOWN = "unknown"


@dataclass
class InboundAction:
    """Parsed result of a user action from Teams."""
    action_type: ActionType
    incident_id: str
    user_name: str
    user_id: str
    raw_data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class BotResponse:
    """What the bot should reply with."""
    text: str | None = None
    card: dict | None = None  # Adaptive Card to send back


# Type alias for action callbacks
ActionCallback = Callable[[InboundAction], Awaitable[BotResponse]]


class ActionRouter:
    """
    Routes inbound Teams actions to platform handlers.

    Register callbacks for specific action types. When a card action
    arrives from Teams, the router parses it and dispatches to the
    appropriate handler.
    """

    def __init__(self):
        self._handlers: dict[ActionType, ActionCallback] = {}
        self._command_handlers: dict[str, ActionCallback] = {}
        self.action_log: list[InboundAction] = []

    def on_action(self, action_type: ActionType):
        """Decorator to register a handler for a card action type."""
        def decorator(fn: ActionCallback):
            self._handlers[action_type] = fn
            return fn
        return decorator

    def on_command(self, command: str):
        """Decorator to register a handler for a text command (e.g., /status)."""
        def decorator(fn: ActionCallback):
            self._command_handlers[command.lower().strip("/")] = fn
            return fn
        return decorator

    def parse_card_action(self, data: dict, user_name: str = "", user_id: str = "") -> InboundAction:
        """
        Parse an Adaptive Card Action.Submit payload from Teams.

        When a user clicks a button on an Adaptive Card sent by our bot,
        Teams sends the button's `data` field back to us.
        """
        action_str = data.get("action", "unknown")
        try:
            action_type = ActionType(action_str)
        except ValueError:
            action_type = ActionType.UNKNOWN

        return InboundAction(
            action_type=action_type,
            incident_id=data.get("incident_id", ""),
            user_name=user_name,
            user_id=user_id,
            raw_data=data,
        )

    def parse_text_command(self, text: str, user_name: str = "", user_id: str = "") -> tuple[str, str]:
        """
        Parse a text message for commands.

        Returns (command, remainder) — e.g., "/status INC-001" → ("status", "INC-001")
        """
        text = text.strip()
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            command = parts[0].lower() if parts else ""
            remainder = parts[1] if len(parts) > 1 else ""
            return command, remainder
        return "", text

    async def handle_card_action(self, data: dict, user_name: str = "", user_id: str = "") -> BotResponse:
        """Process an Adaptive Card button click."""
        action = self.parse_card_action(data, user_name, user_id)
        self.action_log.append(action)

        handler = self._handlers.get(action.action_type)
        if handler:
            return await handler(action)

        return BotResponse(
            text=f"Received action '{action.action_type.value}' for incident {action.incident_id}, "
                 f"but no handler is registered."
        )

    async def handle_text(self, text: str, user_name: str = "", user_id: str = "") -> BotResponse:
        """Process a text message (may contain a /command)."""
        command, remainder = self.parse_text_command(text, user_name, user_id)

        if command and command in self._command_handlers:
            # Wrap command into an InboundAction for consistency
            action = InboundAction(
                action_type=ActionType.UNKNOWN,
                incident_id=remainder.strip(),
                user_name=user_name,
                user_id=user_id,
                raw_data={"command": command, "args": remainder},
            )
            self.action_log.append(action)
            return await self._command_handlers[command](action)

        # No command matched — return None to let other handlers (e.g., Ollama chat) take over
        return BotResponse(text=None)
