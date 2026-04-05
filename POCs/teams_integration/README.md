# POC 2: Teams App Integration with Local Ollama

Demonstrates a Microsoft Teams bot powered by a local Ollama model for DevOps incident assistance.

## Architecture

```
Teams Channel → Bot Framework → FastAPI/aiohttp webhook → Ollama (local)
                                       ↕
                              Conversation History (in-memory)
```

## Quick Start (Local Demo)

```bash
# From project root
uv run python -m POCs.teams_integration.demo
```

This runs a simulated Teams conversation against the local Ollama model — no Azure registration needed.

## Deploy to Teams

1. Register a bot in [Azure Bot Service](https://portal.azure.com/#create/Microsoft.BotServiceConnectivityGalleryPackage)
2. Enable the Microsoft Teams channel
3. Set environment variables:
   ```bash
   export TEAMS_APP_ID="your-app-id"
   export TEAMS_APP_PASSWORD="your-app-password"
   ```
4. Start the server:
   ```bash
   uv run python -m POCs.teams_integration.teams_app
   ```
5. Expose port 3978 via ngrok: `ngrok http 3978`
6. Set the messaging endpoint in Azure Bot → Settings → `https://<ngrok-url>/api/messages`

## Bot Commands

| Command | Description |
|---------|-------------|
| `/health` | Check if Ollama is reachable |
| `/clear` | Reset conversation history |
| *(any text)* | Ask the DevOps assistant |

## Features

- Conversational memory (per-conversation history)
- Typing indicator while Ollama generates response
- Error handling with user-friendly messages
- Health check endpoint at `GET /health`
