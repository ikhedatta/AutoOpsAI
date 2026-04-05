# Teams Integration Setup Guide

> **Goal**: Make Teams the face of AutoOps AI — all alerts, approvals, and responses flow through a Teams channel. The platform is the brain; Teams is the UI.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Microsoft Teams Channel                      │
│                                                                   │
│  ┌──────────────┐    ┌──────────────────┐    ┌───────────────┐  │
│  │ Alert Cards   │    │ Approval Cards    │    │ /commands     │  │
│  │ (read-only)   │    │ Approve/Deny btns │    │ /status etc   │  │
│  └──────┬───────┘    └────────┬─────────┘    └───────┬───────┘  │
│         │                     │                       │          │
└─────────┼─────────────────────┼───────────────────────┼──────────┘
          │                     │                       │
    Incoming Webhook      Bot Framework           Bot Framework
    (one-way push)     (two-way via Azure)     (two-way via Azure)
          │                     │                       │
          ▼                     ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AutoOps AI Platform                            │
│                                                                   │
│  webhook.py              bot_server.py                           │
│  (send alerts)           (receive actions, send responses)       │
│       │                       │                                   │
│       └───────────┬───────────┘                                  │
│                   ▼                                               │
│            AutoOps Pipeline                                      │
│  (detect → match → route → fix → verify)                        │
└─────────────────────────────────────────────────────────────────┘
```

## Two Communication Channels

### Channel 1: Incoming Webhook (Platform → Teams)

**What it does**: Pushes alerts, status updates, and outcome cards into a Teams channel.

**Limitations**: One-way only. Cards sent via webhook can display `Action.Submit` buttons, but **clicks on those buttons do nothing** — webhooks can't receive responses. Use this for read-only notifications.

**Best for**: Alert notifications, incident summaries, remediation outcomes.

### Channel 2: Bot Framework (Teams ↔ Platform)

**What it does**: Full two-way communication. Users can:
- Type `/commands` and get responses
- Click buttons on Adaptive Cards and the platform receives the action
- Have conversations with the Ollama-powered assistant

**Requires**: Azure Bot Service registration (free tier available).

**Best for**: Approval workflows, interactive investigation, command interface.

---

## Setup Step-by-Step

### Prerequisites

- A Microsoft Teams workspace where you have permission to add apps/webhooks
- An Azure account (free tier works) for the Bot registration
- Python 3.12+ with dependencies installed (`uv sync`)
- `ngrok` installed for local development (`brew install ngrok` or https://ngrok.com)

---

### Part 1: Incoming Webhook (5 minutes)

This lets the platform **push messages** to a Teams channel.

#### Step 1.1: Create the Webhook in Teams

1. Open Microsoft Teams
2. Go to the channel where you want alerts (e.g., `#ops-alerts`)
3. Click the `⋯` (more options) next to the channel name
4. Select **Manage channel** → **Connectors** (or **Edit channel** → **Connectors**)
   - **New Teams UI (2024+)**: Go to channel → **Workflows** → search for **"Post to a channel when a webhook request is received"** → configure it
5. Find **Incoming Webhook** and click **Configure** (or **Add**)
6. Give it a name: `AutoOps AI Alerts`
7. Optionally upload an icon
8. Click **Create**
9. **Copy the webhook URL** — it looks like:
   ```
   https://your-org.webhook.office.com/webhookb2/...
   ```

> **Important**: This URL is a secret. Anyone with it can post to your channel. Store it securely (environment variable, not in code).

#### Step 1.2: Test It

```bash
# Set the webhook URL
export TEAMS_WEBHOOK_URL="https://your-org.webhook.office.com/webhookb2/..."

# Run the POC demo (sends real messages to Teams)
uv run python -m POCs.teams_two_way.demo
```

You should see messages appear in your Teams channel within seconds.

#### Step 1.3: Quick Test with curl

```bash
curl -H "Content-Type: application/json" \
     -d '{"text": "Hello from AutoOps AI!"}' \
     "$TEAMS_WEBHOOK_URL"
```

---

### Part 2: Bot Registration (15 minutes)

This lets users **respond** to the platform from Teams.

#### Step 2.1: Create an Azure Bot

1. Go to [Azure Portal](https://portal.azure.com)
2. Search for **"Azure Bot"** → Click **Create**
3. Fill in:
   - **Bot handle**: `autoops-ai-bot`
   - **Subscription**: Your Azure subscription
   - **Resource group**: Create new or use existing
   - **Pricing tier**: **F0 (Free)** — 10,000 messages/month
   - **Microsoft App ID**: Select **"Create new Microsoft App ID"**
4. Click **Review + Create** → **Create**
5. Once created, go to the resource

#### Step 2.2: Get App ID and Password

1. In your Azure Bot resource, go to **Configuration**
2. Copy the **Microsoft App ID**
3. Click **Manage Password** → **New client secret**
4. Copy the **client secret value** (you won't see it again)

```bash
export TEAMS_APP_ID="your-app-id-here"
export TEAMS_APP_PASSWORD="your-client-secret-here"
```

#### Step 2.3: Enable Teams Channel

1. In your Azure Bot resource, go to **Channels**
2. Click **Microsoft Teams** → **Apply**
3. Accept the terms of service

#### Step 2.4: Set Up ngrok (Local Development)

The Bot Framework needs to reach your local server. ngrok creates a public tunnel:

```bash
# Start ngrok tunnel to your bot server
ngrok http 3978
```

ngrok gives you a URL like `https://abc123.ngrok-free.app`.

#### Step 2.5: Configure Messaging Endpoint

1. In Azure Bot → **Configuration**
2. Set **Messaging endpoint** to:
   ```
   https://abc123.ngrok-free.app/api/messages
   ```
3. **Save**

#### Step 2.6: Start the Bot Server

```bash
export TEAMS_APP_ID="your-app-id"
export TEAMS_APP_PASSWORD="your-client-secret"
export TEAMS_WEBHOOK_URL="your-webhook-url"  # optional, for proactive alerts

# Start the bot server
uv run python -m POCs.teams_two_way.bot_server
```

#### Step 2.7: Add Bot to Teams

1. In Azure Bot → **Channels** → click **Microsoft Teams**
2. This opens Teams with the bot — click **Add** (or **Open in Teams**)
3. You can now chat with the bot directly or add it to a channel

To add to a channel:
1. Go to the Teams channel
2. Click `+` (Add a tab) or `⋯` → **Get more apps**
3. Search for your bot name
4. Add it to the channel

---

### Part 3: Wire It All Together

Once both channels are set up, the full flow works:

```
Platform detects anomaly
    ↓
webhook.py sends approval card to #ops-alerts (Incoming Webhook)
    ↓
User sees card in Teams
    ↓
User @mentions the bot or bot sends its OWN card with Action.Submit buttons
    ↓
User clicks Approve on the BOT's card
    ↓
Teams sends action to bot_server.py /api/messages
    ↓
bot_handler.py routes action → triggers remediation pipeline
    ↓
Pipeline executes → result sent back via webhook.py (outcome card)
```

> **Key Point**: For the Approve/Deny buttons to work, the Adaptive Card must be sent **by the bot**, not by the Incoming Webhook. The bot can proactively send cards to a channel it's been added to. See the "Proactive Messaging" section below.

---

## Proactive Messaging (Bot sends first)

For the bot to send messages to a channel without the user messaging first, you need a **conversation reference**. The simplest way:

1. After adding the bot to a channel, have someone type a message to the bot
2. The bot captures the `conversation_reference` from that activity
3. Use `adapter.continue_conversation()` to send proactive messages later

```python
# Capture reference when user first messages the bot
conversation_reference = TurnContext.get_conversation_reference(turn_context.activity)

# Later, send a proactive message
async def send_proactive(card):
    async def callback(turn_context: TurnContext):
        await turn_context.send_activity(
            Activity(
                type=ActivityTypes.message,
                attachments=[{
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }],
            )
        )
    await adapter.continue_conversation(conversation_reference, callback, APP_ID)
```

This is how you get **interactive Adaptive Cards** (with working buttons) sent proactively.

---

## Production Deployment Checklist

| Item | Local Dev | Production |
|------|-----------|------------|
| Bot server hosting | localhost + ngrok | Azure App Service / your server |
| Messaging endpoint | ngrok URL (changes on restart) | Stable HTTPS URL |
| Webhook URL | Env variable | Azure Key Vault / secrets manager |
| App credentials | Env variables | Azure Key Vault / managed identity |
| Ollama | localhost:11434 | Internal server on same network |
| Bot pricing | F0 Free tier | F0 or S1 depending on volume |

## Environment Variables Summary

```bash
# Required for outbound alerts (Incoming Webhook)
TEAMS_WEBHOOK_URL="https://your-org.webhook.office.com/webhookb2/..."

# Required for inbound actions (Bot Framework)
TEAMS_APP_ID="your-azure-bot-app-id"
TEAMS_APP_PASSWORD="your-azure-bot-client-secret"

# Optional: Ollama endpoint (default: http://localhost:11434)
OLLAMA_BASE="http://localhost:11434"
```

## FAQ

**Q: Can I use just Incoming Webhooks without a bot?**
A: Yes, for one-way alerts. But users can't click buttons or respond. Good for notification-only use cases.

**Q: Can I use just the bot without webhooks?**
A: Yes. The bot can send proactive messages with interactive cards. The webhook is simpler for fire-and-forget alerts.

**Q: Is the Azure Bot free?**
A: The F0 tier is free for up to 10,000 messages/month in standard channels (Teams, etc.). Plenty for a DevOps team.

**Q: Does my data go through Microsoft's servers?**
A: Message routing goes through Azure Bot Service. The message content passes through. Your Ollama LLM inference stays local — only the user messages and bot responses transit Microsoft's infrastructure. If this is a concern, consult your security team about the Bot Framework's data handling policies.

**Q: What about Power Automate / Workflows?**
A: Workflows can also trigger HTTP POSTs to your platform when certain events happen in Teams. This is an alternative to the Bot Framework for simpler use cases (e.g., keyword triggers). The Bot Framework gives you more control.

**Q: Can multiple channels use the same bot?**
A: Yes. Add the bot to multiple channels. Each channel gets its own conversation reference for proactive messaging.
