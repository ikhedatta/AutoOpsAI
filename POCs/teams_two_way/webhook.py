"""
Outbound messaging: Platform → Teams via Incoming Webhook.

Incoming Webhooks are the simplest way to push notifications into a Teams
channel.  No bot registration needed — just a URL you POST JSON to.

Supports:
  - Plain text messages
  - Adaptive Cards (rich interactive cards)
  - Message-card (legacy Office 365 connector format)
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class WebhookResult:
    """Result of a webhook POST."""
    success: bool
    status_code: int
    message: str


class TeamsWebhook:
    """Send messages to a Teams channel via Incoming Webhook URL."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_text(self, text: str) -> WebhookResult:
        """Send a simple text message."""
        payload = {"text": text}
        return await self._post(payload)

    async def send_adaptive_card(self, card: dict) -> WebhookResult:
        """
        Send an Adaptive Card to the channel.

        The card dict should follow Adaptive Card schema v1.4+.
        Teams Incoming Webhooks expect the card wrapped in an attachment.
        """
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card,
                }
            ],
        }
        return await self._post(payload)

    async def send_alert(
        self,
        title: str,
        severity: str,
        container: str,
        description: str,
        facts: dict[str, str] | None = None,
    ) -> WebhookResult:
        """
        Send a pre-built alert card.

        Convenience method that builds an Adaptive Card for incident alerts.
        """
        severity_colors = {"LOW": "good", "MEDIUM": "warning", "HIGH": "attention"}
        severity_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}

        color = severity_colors.get(severity.upper(), "default")
        emoji = severity_emoji.get(severity.upper(), "⚪")

        fact_set = [
            {"title": "Container", "value": container},
            {"title": "Severity", "value": f"{emoji} {severity.upper()}"},
        ]
        if facts:
            fact_set.extend({"title": k, "value": v} for k, v in facts.items())

        card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"{emoji} {title}",
                    "weight": "bolder",
                    "size": "large",
                    "color": color,
                },
                {"type": "FactSet", "facts": fact_set},
                {
                    "type": "TextBlock",
                    "text": description,
                    "wrap": True,
                    "size": "small",
                },
            ],
        }
        return await self.send_adaptive_card(card)

    async def _post(self, payload: dict) -> WebhookResult:
        """POST payload to the webhook URL."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code in (200, 202):
                    return WebhookResult(True, resp.status_code, "Message sent")
                return WebhookResult(
                    False, resp.status_code,
                    f"Webhook returned {resp.status_code}: {resp.text[:200]}",
                )
        except httpx.ConnectError as e:
            return WebhookResult(False, 0, f"Connection failed: {e}")
        except httpx.TimeoutException:
            return WebhookResult(False, 0, "Request timed out")
