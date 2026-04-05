# [Step 17] — Teams Bot Implementation

## Context

Steps 01-16 are complete. The following exist:
- `agent/approval/card_builder.py` — `CardBuilder`
- `agent/approval/teams_cards/` — all 5 JSON templates
- `agent/store/documents.py` — `IncidentDocument`, `ApprovalDocument`
- `agent/config.py` — `teams_app_id`, `teams_app_password`, `teams_local_emulator`
- `agent/approval/__init__.py` — package exists

## Objective

Produce the MS Teams bot implementation using `botbuilder-core` with HMAC signature verification on incoming webhooks, plus the FastAPI webhook route handler for Teams callbacks.

## Files to Create

- `agent/approval/teams_bot.py` — `TeamsApprovalBot` class using botbuilder-core.
- `agent/approval/teams_webhook.py` — FastAPI `APIRouter` with `POST /api/v1/webhooks/teams/events`.
- `tests/test_teams_bot.py` — Tests with mocked Bot Framework adapter.

## Files to Modify

None. (The webhook router is included in `main.py` in step 22.)

## Key Requirements

**agent/approval/teams_bot.py:**

```python
from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity, ActivityTypes
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from botframework.connector.auth import SimpleCredentialProvider

class TeamsApprovalBot(ActivityHandler):
    def __init__(self, card_builder: CardBuilder, settings: AgentSettings):
        self.card_builder = card_builder
        self.settings = settings
        # Store for tracking sent card activity IDs and conversation references
        # Persisted to MongoDB ApprovalDocument.teams_activity_id and
        # ApprovalDocument.teams_conversation_reference
        self._adapter: Optional[CloudAdapter] = None

    def get_adapter(self) -> CloudAdapter:
        """Lazily initialise the Bot Framework adapter."""
        if self._adapter is None:
            credential_provider = SimpleCredentialProvider(
                self.settings.teams_app_id,
                self.settings.teams_app_password,
            )
            auth = ConfigurationBotFrameworkAuthentication(credential_provider)
            self._adapter = CloudAdapter(auth)
        return self._adapter

    async def on_invoke_activity(self, turn_context: TurnContext) -> None:
        """
        Handle Action.Execute callbacks from Adaptive Card buttons.
        The activity value contains: {"verb": "approve"/"deny"/"investigate", "data": {"incident_id": "..."}}
        """

    async def send_approval_card(
        self,
        channel_id: str,
        service_url: str,
        incident: IncidentDocument,
        approval: ApprovalDocument,
    ) -> Optional[str]:
        """
        Send an Adaptive Card to a Teams channel.
        Returns the activity_id for later card updates.
        If TEAMS_LOCAL_EMULATOR is True, route to emulator instead.
        On failure: log error, return None (do not crash).
        """

    async def update_card(
        self,
        activity_id: str,
        conversation_reference: dict,
        updated_card: dict,
    ) -> bool:
        """
        Update an existing card in Teams using the stored conversation reference.
        Uses adapter.continue_conversation() + update_activity().
        Returns True if successful, False on error.
        """

    async def send_notification(self, channel_id: str, service_url: str, message: str) -> bool:
        """
        Send a plain text or simple card notification to the Teams channel.
        Used for LOW risk auto-resolution notifications.
        """

    async def send_investigation_reply(
        self,
        conversation_reference: dict,
        incident: IncidentDocument,
        llm_reasoning: str,
        log_excerpts: str,
    ) -> bool:
        """
        Send an investigation reply card in the same thread as the original approval card.
        Uses adapter.continue_conversation() to reply in the original thread.
        """

    async def _verify_hmac_signature(self, body: bytes, auth_header: str) -> bool:
        """
        Verify the HMAC signature on incoming Teams webhook requests.
        Teams sends: Authorization header with value "HMAC <base64_signature>"
        Compute: HMAC-SHA256(body, TEAMS_APP_PASSWORD) → base64
        Return True if signatures match, False otherwise.
        """
```

**HMAC signature verification:**
```python
import hmac
import hashlib
import base64

async def _verify_hmac_signature(self, body: bytes, auth_header: str) -> bool:
    if not auth_header.startswith("HMAC "):
        return False
    received_sig = auth_header[5:]  # Remove "HMAC " prefix
    expected = base64.b64encode(
        hmac.new(
            self.settings.teams_app_password.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return hmac.compare_digest(received_sig, expected)
```

**Emulator routing in `send_approval_card()`:**
```python
if self.settings.teams_local_emulator:
    from agent.approval.teams_emulator import add_card, EmulatorCard
    emulator_card = EmulatorCard(
        incident_id=incident.incident_id,
        title=incident.title,
        severity=incident.severity,
        service=incident.service,
        diagnosis=incident.diagnosis_summary or "",
        proposed_action=incident.proposed_action or "",
        rollback_plan=incident.rollback_plan,
        risk_level=incident.severity,
        requested_at=approval.requested_at,
        timeout_at=approval.timeout_at,
    )
    add_card(emulator_card)
    return f"emulator-{incident.incident_id}"   # Fake activity_id for emulator
```

**On `invoke_activity` for real Teams:** Parse `turn_context.activity.value`, extract `verb` and `incident_id` from `data`. Call the ApprovalRouter (which is injected via constructor in step 18). For now, implement `on_invoke_activity` as a stub that logs the action and returns a 200 acknowledgement card.

**agent/approval/teams_webhook.py:**

```python
from fastapi import APIRouter, Request, Response, HTTPException, Header
from agent.approval.teams_bot import TeamsApprovalBot

webhook_router = APIRouter()
_bot: Optional[TeamsApprovalBot] = None

def set_bot(bot: TeamsApprovalBot) -> None:
    """Called from main.py to inject the bot instance."""
    global _bot
    _bot = bot

@webhook_router.post("/api/v1/webhooks/teams/events")
async def teams_events(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Response:
    """
    Receive Bot Framework activity payloads from Teams.
    1. Read raw body
    2. Verify HMAC signature
    3. Process with bot adapter
    """
    body = await request.body()

    if _bot is None:
        raise HTTPException(503, "Bot not initialised")

    # HMAC verification
    if authorization and not await _bot._verify_hmac_signature(body, authorization):
        raise HTTPException(401, "Invalid HMAC signature")

    # Process with Bot Framework adapter
    adapter = _bot.get_adapter()
    activity = Activity().deserialize(body.decode("utf-8"))

    async def callback(turn_context: TurnContext):
        await _bot.on_invoke_activity(turn_context)

    await adapter.process_activity(activity, authorization or "", callback)
    return Response(status_code=200)
```

**tests/test_teams_bot.py:**

Use `unittest.mock.AsyncMock` for the adapter. All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_hmac_verification_valid` — compute correct HMAC, assert `_verify_hmac_signature` returns True.
2. `test_hmac_verification_invalid` — wrong signature, assert returns False.
3. `test_hmac_verification_missing_prefix` — header without "HMAC " prefix, assert False.
4. `test_send_approval_card_emulator` — with `teams_local_emulator=True`, assert card is added to emulator store.
5. `test_send_approval_card_emulator_returns_fake_id` — assert returned ID starts with "emulator-".
6. `test_update_card_failure_returns_false` — mock adapter raises exception, assert returns False.
7. `test_send_notification_emulator_mode` — with emulator on, assert no Bot Framework calls made.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_teams_bot.py -v
# Expected: all 7 tests pass

# Verify imports
python -c "
from agent.approval.teams_bot import TeamsApprovalBot
from agent.approval.teams_webhook import webhook_router, set_bot
print('teams bot imports OK')
"
```

## Dependencies

- Step 01 (botbuilder-core, botbuilder-integration-aiohttp installed)
- Step 02 (core models)
- Step 08 (MongoDB documents)
- Step 15 (teams emulator — `add_card`, `EmulatorCard`)
- Step 16 (card builder — `CardBuilder`)
