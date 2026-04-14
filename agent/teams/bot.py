"""
Teams Bot handler — receives messages and card actions from Microsoft Teams,
routes them to the AutoOps agent backend, and sends responses back.

This module uses the Bot Framework SDK directly, integrated into the existing
FastAPI application (no separate aiohttp server).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import (
    Activity,
    ActivityTypes,
    Attachment,
    ConversationReference,
)

from agent.config import Settings
from agent.store import incidents as incident_store
from agent.store.models import ApprovalDoc

from agent.teams.cards import (
    build_approval_card,
    build_outcome_card,
)

logger = logging.getLogger(__name__)


class AutoOpsTeamsBot:
    """Handles inbound Teams messages and Adaptive Card actions,
    routing them to the production AutoOps API layer."""

    def __init__(self, settings: Settings, app_state: dict):
        self.settings = settings
        self.app_state = app_state

        self.adapter_settings = BotFrameworkAdapterSettings(
            app_id=settings.teams_app_id,
            app_password=settings.teams_app_secret,
            # Single-tenant: set channel_auth_tenant
            channel_auth_tenant=settings.teams_tenant_id or None,
        )
        self.adapter = BotFrameworkAdapter(self.adapter_settings)
        self.adapter.on_turn_error = self._on_error

        # Store conversation references for proactive messaging
        # Key: conversation ID → ConversationReference
        self._conversation_refs: dict[str, ConversationReference] = {}

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    async def _on_error(self, context: TurnContext, error: Exception) -> None:
        logger.error("Teams bot error: %s", error, exc_info=True)
        await context.send_activity("⚠️ Something went wrong. Please try again.")

    # ------------------------------------------------------------------
    # Inbound activity processing (called from FastAPI route)
    # ------------------------------------------------------------------

    async def process_activity(self, body: dict, auth_header: str) -> Any:
        """Process an incoming Bot Framework activity from the /api/messages endpoint."""
        activity = Activity().deserialize(body)
        response = await self.adapter.process_activity(
            activity, auth_header, self._on_turn,
        )
        return response

    async def _on_turn(self, context: TurnContext) -> None:
        """Main turn handler — dispatches by activity type."""
        # Store conversation reference for proactive messaging
        self._save_conversation_ref(context.activity)

        if context.activity.type == ActivityTypes.message:
            await self._handle_message(context)
        elif context.activity.type == ActivityTypes.invoke:
            await self._handle_invoke(context)
        elif context.activity.type in (
            ActivityTypes.conversation_update,
            ActivityTypes.install_update,
        ):
            await self._handle_conversation_update(context)

    # ------------------------------------------------------------------
    # Message handling — slash commands and free-text chat
    # ------------------------------------------------------------------

    async def _handle_message(self, context: TurnContext) -> None:
        text = (context.activity.text or "").strip()
        # Remove @mention of the bot from the text
        text = self._strip_bot_mention(text, context.activity)

        if not text:
            return

        lower = text.lower()

        # Slash commands
        if lower in ("help", "/help"):
            await self._cmd_help(context)
        elif lower in ("status", "/status"):
            await self._cmd_status(context)
        elif lower in ("incidents", "/incidents"):
            await self._cmd_incidents(context)
        elif lower.startswith(("incident ", "/incident ")):
            incident_id = self._extract_arg(text)
            await self._cmd_incident_detail(context, incident_id)
        elif lower.startswith(("approve ", "/approve ")):
            incident_id = self._extract_arg(text)
            await self._cmd_approve(context, incident_id)
        elif lower.startswith(("deny ", "/deny ")):
            incident_id = self._extract_arg(text)
            await self._cmd_deny(context, incident_id)
        elif lower in ("pending", "/pending"):
            await self._cmd_pending(context)
        else:
            # Free-text → route to LLM chat
            await self._cmd_chat(context, text)

    # ------------------------------------------------------------------
    # Command implementations — call production API layer directly
    # ------------------------------------------------------------------

    async def _cmd_help(self, context: TurnContext) -> None:
        help_text = (
            "**AutoOps AI — Commands**\n\n"
            "| Command | Description |\n"
            "|---------|-------------|\n"
            "| `status` | Agent & infrastructure health |\n"
            "| `incidents` | List active incidents |\n"
            "| `incident <ID>` | Incident details |\n"
            "| `pending` | Pending approvals |\n"
            "| `approve <ID>` | Approve remediation |\n"
            "| `deny <ID>` | Deny remediation |\n"
            "| `help` | Show this message |\n\n"
            "Or just type a question — I'll use AI to answer it."
        )
        await context.send_activity(help_text)

    async def _cmd_status(self, context: TurnContext) -> None:
        await context.send_activities([Activity(type=ActivityTypes.typing)])

        from agent.store import database as db
        components = {
            "database": await db.health_check(),
            "collector": self.app_state.get("collector_running", False),
            "provider": self.app_state.get("provider_type", "unknown"),
            "ollama": self.app_state.get("ollama_available", False),
        }

        # Check observability
        for name in ("prometheus", "loki", "grafana"):
            client = self.app_state.get(name)
            if client:
                components[name] = await client.is_available()
            else:
                components[name] = False

        all_ok = all(v for v in components.values() if isinstance(v, bool))

        lines = [f"**{'✅' if all_ok else '⚠️'} System Status**\n"]
        for comp, val in components.items():
            if isinstance(val, bool):
                icon = "✅" if val else "❌"
                lines.append(f"- {icon} {comp}")
            else:
                lines.append(f"- ℹ️ {comp}: {val}")

        await context.send_activity("\n".join(lines))

    async def _cmd_incidents(self, context: TurnContext) -> None:
        await context.send_activities([Activity(type=ActivityTypes.typing)])

        docs = await incident_store.list_incidents(limit=10)
        if not docs:
            await context.send_activity("No incidents found.")
            return

        lines = ["**Active Incidents**\n"]
        for d in docs:
            emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(d.severity, "⚪")
            lines.append(
                f"- {emoji} **{d.incident_id}** | {d.title} | "
                f"{d.severity} | {d.status}"
            )

        await context.send_activity("\n".join(lines))

    async def _cmd_incident_detail(self, context: TurnContext, incident_id: str) -> None:
        if not incident_id:
            await context.send_activity("Usage: `incident <incident_id>`")
            return

        await context.send_activities([Activity(type=ActivityTypes.typing)])

        doc = await incident_store.get_incident(incident_id)
        if not doc:
            await context.send_activity(f"Incident `{incident_id}` not found.")
            return

        emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(doc.severity, "⚪")
        lines = [
            f"{emoji} **{doc.title}**\n",
            f"- **ID:** {doc.incident_id}",
            f"- **Severity:** {doc.severity}",
            f"- **Status:** {doc.status}",
            f"- **Service:** {doc.service_name or '—'}",
            f"- **Anomaly:** {doc.anomaly_type or '—'}",
            f"- **Detected:** {doc.detected_at.strftime('%Y-%m-%d %H:%M:%S') if doc.detected_at else '—'}",
        ]
        if doc.diagnosis_summary:
            lines.append(f"- **Diagnosis:** {doc.diagnosis_summary}")
        if doc.proposed_actions:
            lines.append(f"- **Actions:** {', '.join(doc.proposed_actions)}")

        await context.send_activity("\n".join(lines))

    async def _cmd_pending(self, context: TurnContext) -> None:
        await context.send_activities([Activity(type=ActivityTypes.typing)])

        approvals = await ApprovalDoc.find(
            {"decision": None},
        ).sort("-created_at").to_list()

        if not approvals:
            await context.send_activity("No pending approvals.")
            return

        for appr in approvals:
            doc = await incident_store.get_incident(appr.incident_id)
            if doc:
                card = build_approval_card(doc, appr)
                attachment = Attachment(
                    content_type="application/vnd.microsoft.card.adaptive",
                    content=card,
                )
                await context.send_activity(
                    Activity(type=ActivityTypes.message, attachments=[attachment])
                )

    async def _cmd_approve(self, context: TurnContext, incident_id: str) -> None:
        if not incident_id:
            await context.send_activity("Usage: `approve <incident_id>`")
            return

        await context.send_activities([Activity(type=ActivityTypes.typing)])

        user_name = self._get_user_name(context)
        approval_router = self.app_state.get("approval_router")
        if not approval_router:
            await context.send_activity("⚠️ Approval system not available.")
            return

        from agent.models import ApprovalDecision, ApprovalDecisionType
        decision = ApprovalDecision(
            incident_id=incident_id,
            decision=ApprovalDecisionType.APPROVE,
            decided_by=user_name,
            reason=f"Approved via Teams by {user_name}",
        )
        doc = await approval_router.process_decision(incident_id, decision)
        if not doc:
            await context.send_activity(f"Incident `{incident_id}` not found or not pending.")
            return

        await incident_store.add_chat_message(
            incident_id, "user",
            f"✅ **Approved** by {user_name} (via Teams)",
        )

        card = build_outcome_card(incident_id, "approve", user_name)
        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card,
        )
        await context.send_activity(
            Activity(type=ActivityTypes.message, attachments=[attachment])
        )

    async def _cmd_deny(self, context: TurnContext, incident_id: str) -> None:
        if not incident_id:
            await context.send_activity("Usage: `deny <incident_id>`")
            return

        await context.send_activities([Activity(type=ActivityTypes.typing)])

        user_name = self._get_user_name(context)
        approval_router = self.app_state.get("approval_router")
        if not approval_router:
            await context.send_activity("⚠️ Approval system not available.")
            return

        from agent.models import ApprovalDecision, ApprovalDecisionType
        decision = ApprovalDecision(
            incident_id=incident_id,
            decision=ApprovalDecisionType.DENY,
            decided_by=user_name,
            reason=f"Denied via Teams by {user_name}",
        )
        doc = await approval_router.process_decision(incident_id, decision)
        if not doc:
            await context.send_activity(f"Incident `{incident_id}` not found or not pending.")
            return

        await incident_store.add_chat_message(
            incident_id, "user",
            f"❌ **Denied** by {user_name} (via Teams)",
        )

        card = build_outcome_card(incident_id, "deny", user_name)
        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card,
        )
        await context.send_activity(
            Activity(type=ActivityTypes.message, attachments=[attachment])
        )

    async def _cmd_chat(self, context: TurnContext, question: str) -> None:
        """Route free-text to the LLM chat — same logic as POST /api/v1/chat."""
        await context.send_activities([Activity(type=ActivityTypes.typing)])

        llm = self.app_state.get("llm_client")
        if not llm:
            await context.send_activity("⚠️ LLM not available.")
            return

        # Detect if user mentioned an incident ID
        incident_id = self._detect_incident_id(question)

        # Build system state
        system_state: dict = {}
        collector = self.app_state.get("collector")
        if collector:
            system_state = await collector.collect_once()

        # Enrich with observability context
        system_state = await self._enrich_observability(system_state)

        # Incident context
        incident_context = None
        if incident_id:
            doc = await incident_store.get_incident(incident_id)
            if doc:
                incident_context = {
                    "incident_id": doc.incident_id,
                    "title": doc.title,
                    "status": doc.status,
                    "diagnosis_summary": doc.diagnosis_summary,
                    "evidence": doc.evidence,
                }

        # Fetch history and call LLM
        chat_id = incident_id or "_general"
        settings = self.settings

        from agent.store.models import ChatMessageDoc
        docs = await (
            ChatMessageDoc.find(ChatMessageDoc.incident_id == chat_id)
            .sort("-timestamp")
            .limit(settings.chat_history_turns)
            .to_list()
        )
        docs.reverse()
        history = [
            {"role": {"user": "user", "agent": "assistant"}.get(m.role, m.role), "content": m.content}
            for m in docs
        ]

        # Use tool-augmented chat if enabled
        if settings.chat_tool_calling_enabled:
            from agent.llm.tool_executor import ToolExecutor
            tool_executor = ToolExecutor(
                provider=self.app_state.get("provider"),
                incident_store=incident_store,
                prometheus=self.app_state.get("prometheus"),
                loki=self.app_state.get("loki"),
                grafana=self.app_state.get("grafana"),
            )
            response = await llm.chat_with_tools(
                question=question,
                system_state=system_state,
                incident_context=incident_context,
                tool_executor=tool_executor,
                max_iterations=settings.chat_max_tool_iterations,
                history=history,
            )
        else:
            response = await llm.chat(
                question=question,
                system_state=system_state,
                incident_context=incident_context,
                history=history,
            )

        # Persist
        await incident_store.add_chat_message(chat_id, "user", question)
        await incident_store.add_chat_message(chat_id, "agent", response)

        await context.send_activity(response)

    # ------------------------------------------------------------------
    # Adaptive Card action handling (button clicks)
    # ------------------------------------------------------------------

    async def _handle_invoke(self, context: TurnContext) -> None:
        """Handle Adaptive Card Action.Execute invocations."""
        if context.activity.name != "adaptiveCard/action":
            return

        value = context.activity.value or {}
        action_data = value.get("action", {})

        # action_data comes from the card's Action.Execute data field
        if isinstance(action_data, dict):
            action = action_data.get("action", "")
            incident_id = action_data.get("incident_id", "")
        else:
            action = ""
            incident_id = ""

        user_name = self._get_user_name(context)

        if action in ("approve", "deny", "investigate") and incident_id:
            approval_router = self.app_state.get("approval_router")
            if not approval_router:
                await self._send_invoke_response(context, "⚠️ Approval system unavailable")
                return

            from agent.models import ApprovalDecision, ApprovalDecisionType
            type_map = {
                "approve": ApprovalDecisionType.APPROVE,
                "deny": ApprovalDecisionType.DENY,
                "investigate": ApprovalDecisionType.INVESTIGATE,
            }
            decision = ApprovalDecision(
                incident_id=incident_id,
                decision=type_map[action],
                decided_by=user_name,
                reason=f"{action.title()}d via Teams card by {user_name}",
            )
            doc = await approval_router.process_decision(incident_id, decision)

            await incident_store.add_chat_message(
                incident_id, "user",
                f"{'✅' if action == 'approve' else '❌' if action == 'deny' else '🔎'} "
                f"**{action.title()}d** by {user_name} (via Teams)",
            )

            # Replace the card with outcome
            outcome_card = build_outcome_card(
                incident_id, action, user_name,
                detail=f"Decision applied to {incident_id}" if doc else f"Incident {incident_id} not found",
            )
            await self._send_invoke_response(context, card=outcome_card)
        else:
            await self._send_invoke_response(context, "Unknown action")

    async def _send_invoke_response(
        self, context: TurnContext, text: str = "", card: dict | None = None,
    ) -> None:
        """Send an invoke response (required for Action.Execute)."""
        response_body: dict[str, Any] = {
            "statusCode": 200,
            "type": "application/vnd.microsoft.card.adaptive",
        }
        if card:
            response_body["value"] = card
        elif text:
            response_body["type"] = "application/vnd.microsoft.activity.message"
            response_body["value"] = text

        await context.send_activity(
            Activity(
                type=ActivityTypes.invoke_response,
                value={"status": 200, "body": response_body},
            )
        )

    # ------------------------------------------------------------------
    # Conversation update (bot installed / member added)
    # ------------------------------------------------------------------

    async def _handle_conversation_update(self, context: TurnContext) -> None:
        if context.activity.members_added:
            for member in context.activity.members_added:
                if member.id != context.activity.recipient.id:
                    await context.send_activity(
                        "👋 Hi! I'm **AutoOps AI** — your DevOps operations assistant.\n\n"
                        "Type `help` to see available commands, or just ask me a question."
                    )

    # ------------------------------------------------------------------
    # Proactive messaging support
    # ------------------------------------------------------------------

    def _save_conversation_ref(self, activity: Activity) -> None:
        ref = TurnContext.get_conversation_reference(activity)
        conv_id = ref.conversation.id if ref.conversation else None
        if conv_id:
            self._conversation_refs[conv_id] = ref

    def get_conversation_refs(self) -> dict[str, ConversationReference]:
        """Return all stored conversation references (for proactive messaging)."""
        return self._conversation_refs

    async def send_proactive_message(self, text: str) -> None:
        """Send a text message to all known conversations."""
        for ref in self._conversation_refs.values():
            try:
                await self.adapter.continue_conversation(
                    ref,
                    lambda ctx: ctx.send_activity(text),
                    self.settings.teams_app_id,
                )
            except Exception:
                logger.warning("Failed to send proactive message to %s", ref.conversation.id, exc_info=True)

    async def send_proactive_card(self, card: dict) -> None:
        """Send an Adaptive Card to all known conversations."""
        attachment = Attachment(
            content_type="application/vnd.microsoft.card.adaptive",
            content=card,
        )

        async def _send(ctx: TurnContext) -> None:
            await ctx.send_activity(
                Activity(type=ActivityTypes.message, attachments=[attachment])
            )

        for ref in self._conversation_refs.values():
            try:
                await self.adapter.continue_conversation(
                    ref, _send, self.settings.teams_app_id,
                )
            except Exception:
                logger.warning("Failed to send proactive card to %s", ref.conversation.id, exc_info=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_bot_mention(text: str, activity: Activity) -> str:
        """Remove @BotName mention from the message text."""
        if activity.entities:
            for entity in activity.entities:
                if entity.type == "mention" and hasattr(entity, "mentioned"):
                    mentioned = entity.mentioned
                    if mentioned and hasattr(mentioned, "id") and mentioned.id == activity.recipient.id:
                        mention_text = getattr(entity, "text", "")
                        if mention_text:
                            text = text.replace(mention_text, "").strip()
        return text

    @staticmethod
    def _extract_arg(text: str) -> str:
        """Extract the argument after a command, e.g. 'approve INC-123' → 'INC-123'."""
        parts = text.strip().split(None, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _get_user_name(context: TurnContext) -> str:
        """Get the display name of the user who sent the message."""
        fr = context.activity.from_property
        if fr and fr.name:
            return fr.name
        if fr and fr.id:
            return fr.id
        return "teams_user"

    @staticmethod
    def _detect_incident_id(text: str) -> str | None:
        """Try to detect an incident ID in the text (e.g. INC-xxx)."""
        match = re.search(r'(INC-[A-Za-z0-9-]+)', text, re.IGNORECASE)
        return match.group(1) if match else None

    async def _enrich_observability(self, system_state: dict) -> dict:
        """Add observability source info — mirrors routes_chat logic."""
        obs: dict = {}
        loki = self.app_state.get("loki")
        if loki and await loki.is_available():
            containers = await loki.get_label_values("container")
            obs["loki"] = "available"
            obs["loki_containers"] = containers or []
        prom = self.app_state.get("prometheus")
        if prom and await prom.is_available():
            obs["prometheus"] = "available"
        grafana = self.app_state.get("grafana")
        if grafana and await grafana.is_available():
            obs["grafana"] = "available"
        if obs:
            system_state["_observability"] = obs
        return system_state
