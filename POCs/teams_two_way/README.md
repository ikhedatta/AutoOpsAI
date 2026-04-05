# POC 11: Teams Two-Way Communication

## What this proves

Two-way communication between AutoOps AI and Microsoft Teams:

1. **Platform → Teams** — Push alerts and Adaptive Cards via Incoming Webhook
2. **Teams → Platform** — Receive user actions (button clicks, /commands) via Bot Framework
3. **Round-trip** — Alert → User Approve/Deny → Execute → Outcome back to Teams

## Architecture

```
Platform → Teams:   Incoming Webhook (HTTP POST with card payload)
Teams → Platform:   Bot Framework (Azure Bot Service routes to our /api/messages)

┌──────────┐  webhook POST   ┌───────────────┐
│ Platform  │ ──────────────→ │ Teams Channel │
│           │                 │               │
│ pipeline  │ ←────────────── │ User clicks   │
│ executor  │  Bot Framework  │ Approve/Deny  │
└──────────┘                  └───────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `webhook.py` | Send messages/cards from platform to Teams |
| `bot_handler.py` | Parse and route inbound actions from Teams |
| `bot_server.py` | HTTP server receiving Bot Framework activities |
| `demo.py` | Test all three directions (outbound, inbound, round-trip) |
| `SETUP_GUIDE.md` | Step-by-step guide to configure Teams |

## Quick Start (Dry Run)

```bash
# No Teams setup needed — shows payloads and simulates actions
uv run python -m POCs.teams_two_way.demo
```

## Live Test (with Teams)

```bash
# Set webhook URL from your Teams channel
export TEAMS_WEBHOOK_URL="https://your-org.webhook.office.com/webhookb2/..."

# Run — sends real messages to your channel
uv run python -m POCs.teams_two_way.demo
```

## Full Bot Setup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for complete instructions on:
- Creating an Incoming Webhook (5 min)
- Registering an Azure Bot (15 min)
- Setting up ngrok for local dev
- Wiring everything together

## Key Insight

- **Incoming Webhooks** can push Adaptive Cards, but button clicks do nothing (one-way)
- **Bot Framework** cards have working buttons — clicks route back to your server
- For the full approve/deny flow, the bot must send the card (not the webhook)
- Best practice: Use webhook for read-only alerts, bot for interactive workflows
