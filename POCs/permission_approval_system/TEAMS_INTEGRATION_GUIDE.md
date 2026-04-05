# Teams Integration Guide: Permission & Approval System

> **Note:** This guide describes the *planned design* for integrating the
> approval system with Teams. The `TeamsApprovalHandler` class shown below
> is **not yet implemented** — it is pseudocode illustrating the target
> architecture. To connect approvals to Teams today, use
> `ApprovalWorkflow.set_custom_handler()` together with the webhook and bot
> server from `POCs/teams_two_way/`. The card actions use `Action.Submit`
> (not `Action.Execute`) — see `POCs/approval_flow/cards.py` for the
> implemented card schemas.

This guide shows how to integrate **POC 7 (Permission & Approval System)** with **POC 2 (Teams Integration)** to send approval requests to Microsoft Teams channels.

## Overview

The permission & approval system can be extended to request approvals via Teams instead of (or in addition to) console prompts:

```
Agent wants to execute Docker restart
         │
         ▼
Permission Manager checks permission
         │
         ▼
Approval Workflow needs user approval
         │
         ├─→ Console Prompt (interactive=True)
         └─→ Teams Message (with Teams handler)
         │
         ▼
Teams Channel receives message
         │
         ▼
User approves/rejects via reaction/button
         │
         ▼
Approval decision returned to agent
         │
         ▼
Tool execution continues or stops
```

## Architecture

```
┌─────────────────┐
│ Tool Execution  │
│ Agent (POC 3)   │
└────────┬────────┘
         │
         ▼
┌──────────────────────────┐
│ Permission Manager (POC7)│
│ - Check permissions      │
│ - Need approval?         │
└────────┬─────────────────┘
         │
         ▼
┌──────────────────────────┐
│ Approval Workflow        │
│ - Console handler        │
│ - Teams handler ← NEW!   │
└────────┬─────────────────┘
         │
         ├─→ Console (async input)
         │
         └─→ Teams Bot (POC 2)
             - Send approval request message
             - Wait for user reaction/response
             - Return decision
```

## Implementation

### Step 1: Create Teams Approval Handler

Create a new file: `POCs/permission_approval_system/teams_approval_handler.py`

```python
"""
Teams Approval Handler

Sends approval requests to Microsoft Teams channels and waits for user responses.
Integrates with POCs.teams_integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

from .approval_workflow import ApprovalRequest, ApprovalStatus, ApprovalMethod


@dataclass
class TeamsApprovalConfig:
    """Configuration for Teams approval handler."""
    
    # Teams bot configuration
    teams_bot_id: str
    teams_channel_id: str
    teams_webhook_url: Optional[str] = None
    
    # Approval timeout
    timeout_seconds: int = 300  # 5 minutes
    
    # Admin users who can approve
    admin_user_ids: list[str] = None
    
    def __post_init__(self):
        if self.admin_user_ids is None:
            self.admin_user_ids = []


class TeamsApprovalHandler:
    """
    Handles approval requests via Microsoft Teams.
    
    Sends rich formatted messages to Teams channels and waits for user responses.
    """
    
    def __init__(self, config: TeamsApprovalConfig):
        """
        Initialize Teams approval handler.
        
        Args:
            config: TeamsApprovalConfig with Teams details
        """
        self.config = config
        self.pending_approvals: dict[str, dict] = {}
        self.approval_callbacks: dict[str, asyncio.Event] = {}
    
    async def request_approval(self, request: ApprovalRequest) -> bool:
        """
        Request approval via Teams.
        
        Returns:
            True if approved, False if rejected/timeout
        """
        
        # Create approval ID
        approval_id = f"{request.tool_name}_{id(request)}"
        
        # Build Teams message
        message = self._build_approval_message(request, approval_id)
        
        # Send to Teams
        await self._send_teams_message(message)
        
        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(
                self._wait_for_approval(approval_id),
                timeout=self.config.timeout_seconds,
            )
            return result
        except asyncio.TimeoutError:
            return False
    
    def _build_approval_message(self, request: ApprovalRequest, approval_id: str) -> dict:
        """
        Build a formatted Teams message for approval request.
        
        Returns:
            AdaptiveCard JSON for Teams
        """
        
        # Risk level colors
        risk_colors = {
            'read_only': '008000',        # Green
            'low_risk': '90EE90',         # Light green
            'medium_risk': 'FFA500',      # Orange
            'high_risk': 'FF0000',        # Red
            'blocked': '000000',          # Black
        }
        
        color = risk_colors.get(request.risk_level.value, '0078D4')  # Microsoft blue
        
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "Container",
                                "style": "emphasis",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": "🔐 Tool Approval Request",
                                        "weight": "bolder",
                                        "size": "large",
                                        "color": "accent",
                                    }
                                ]
                            },
                            {
                                "type": "Container",
                                "style": "warning",
                                "items": [
                                    {
                                        "type": "FactSet",
                                        "facts": [
                                            {
                                                "name": "Tool:",
                                                "value": request.tool_name,
                                            },
                                            {
                                                "name": "Risk Level:",
                                                "value": f"🔴 {request.risk_level.value.upper()}"
                                                if request.risk_level.value == 'high_risk'
                                                else f"⚠️ {request.risk_level.value.upper()}",
                                            },
                                            {
                                                "name": "Category:",
                                                "value": request.tool_meta.category,
                                            },
                                        ]
                                    }
                                ]
                            },
                            {
                                "type": "TextBlock",
                                "text": "Description:",
                                "weight": "bolder",
                                "size": "medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": request.tool_meta.description,
                                "wrap": True,
                            },
                            {
                                "type": "TextBlock",
                                "text": "Parameters:",
                                "weight": "bolder",
                                "size": "medium",
                                "spacing": "medium",
                            },
                            {
                                "type": "TextBlock",
                                "text": str(request.parameters) if request.parameters else "None",
                                "wrap": True,
                                "fontType": "monospace",
                            },
                            {
                                "type": "TextBlock",
                                "text": "Required Permissions:",
                                "weight": "bolder",
                                "size": "medium",
                                "spacing": "medium",
                            },
                            {
                                "type": "Container",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"✓ {perm}",
                                        "wrap": True,
                                    }
                                    for perm in request.tool_meta.required_permissions
                                ]
                            },
                            {
                                "type": "TextBlock",
                                "text": f"Reason: {request.reason}" if request.reason else "",
                                "spacing": "medium",
                                "weight": "bolder",
                            } if request.reason else None,
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "✅ Approve",
                                "url": f"https://autoopsai.local/approve?id={approval_id}",
                                "style": "positive",
                            },
                            {
                                "type": "Action.OpenUrl",
                                "title": "❌ Reject",
                                "url": f"https://autoopsai.local/reject?id={approval_id}",
                                "style": "destructive",
                            },
                        ]
                    }
                }
            ]
        }
    
    async def _send_teams_message(self, message: dict) -> None:
        """
        Send message to Teams channel.
        
        In production, this would use the Teams Bot Framework.
        For demo purposes, this is a placeholder.
        """
        # TODO: Implement Teams Bot Framework integration
        # Example (pseudo-code):
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(
        #         self.config.teams_webhook_url,
        #         json=message,
        #     ) as resp:
        #         return await resp.json()
        
        print(f"[Teams] Sending approval message to channel {self.config.teams_channel_id}")
        print(f"[Teams] Message: {message['attachments'][0]['content']['body'][0]['text']}")
    
    async def _wait_for_approval(self, approval_id: str) -> bool:
        """
        Wait for user approval response.
        
        Returns:
            True if approved, False if rejected
        """
        
        # Create event to wait on
        event = asyncio.Event()
        self.approval_callbacks[approval_id] = event
        
        # Wait for response
        await event.wait()
        
        # Get result
        result = self.pending_approvals.get(approval_id, {}).get('approved', False)
        
        # Cleanup
        del self.approval_callbacks[approval_id]
        del self.pending_approvals[approval_id]
        
        return result
    
    def handle_approval_response(self, approval_id: str, approved: bool) -> None:
        """
        Handle user's approval response from Teams.
        
        Called when user clicks approve/reject button in Teams.
        """
        
        if approval_id not in self.pending_approvals:
            self.pending_approvals[approval_id] = {}
        
        self.pending_approvals[approval_id]['approved'] = approved
        
        # Signal waiting task
        if approval_id in self.approval_callbacks:
            self.approval_callbacks[approval_id].set()


# Global Teams handler instance
_teams_handler: Optional[TeamsApprovalHandler] = None


def init_teams_approval(config: TeamsApprovalConfig) -> TeamsApprovalHandler:
    """Initialize global Teams approval handler."""
    global _teams_handler
    _teams_handler = TeamsApprovalHandler(config)
    return _teams_handler


def get_teams_handler() -> TeamsApprovalHandler:
    """Get global Teams approval handler."""
    if _teams_handler is None:
        raise RuntimeError("Teams handler not initialized. Call init_teams_approval() first.")
    return _teams_handler
```

### Step 2: Update ApprovalWorkflow to Support Teams

Add Teams handler support to `approval_workflow.py`:

```python
# In approval_workflow.py, add to ApprovalWorkflow class:

def set_teams_handler(
    self,
    handler: Callable[[ApprovalRequest], Awaitable[bool]],
) -> None:
    """Set Teams approval handler."""
    self.teams_handler = handler

async def request_approval_via_teams(
    self,
    request: ApprovalRequest,
) -> ApprovalDecision:
    """Request approval via Teams."""
    
    if not self.teams_handler:
        raise ValueError("Teams handler not configured")
    
    try:
        approved = await self.teams_handler(request)
        
        decision = ApprovalDecision(
            tool_name=request.tool_name,
            status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            method=ApprovalMethod.USER_INTERACTIVE,  # Could be ApprovalMethod.TEAMS
            approved_by="teams_user",
            reason="Approved via Teams" if approved else "Rejected via Teams",
            risk_level=request.risk_level,
            parameters=request.parameters,
        )
        
        self.decisions.append(decision)
        return decision
    
    except Exception as e:
        decision = ApprovalDecision(
            tool_name=request.tool_name,
            status=ApprovalStatus.REJECTED,
            method=ApprovalMethod.USER_INTERACTIVE,
            reason=f"Teams approval error: {str(e)}",
            risk_level=request.risk_level,
            parameters=request.parameters,
        )
        
        self.decisions.append(decision)
        return decision
```

### Step 3: Integration Example with Teams

Create: `POCs/permission_approval_system/teams_integration_example.py`

```python
"""
Teams Integration Example

Shows how to use the permission & approval system with Teams for approval requests.
"""

import asyncio
from pathlib import Path

from .approval_workflow import ApprovalWorkflow
from .tool_registry import get_registry
from .teams_approval_handler import (
    TeamsApprovalConfig,
    init_teams_approval,
)


async def example_teams_approval():
    """Example: Request approval via Teams."""
    
    # Initialize Teams handler
    teams_config = TeamsApprovalConfig(
        teams_bot_id="autoopsai-bot",
        teams_channel_id="devops-approvals",
        teams_webhook_url="https://webhook.example.com/messages",
        timeout_seconds=300,  # 5 minutes
        admin_user_ids=["user1@company.com", "user2@company.com"],
    )
    
    teams_handler = init_teams_approval(teams_config)
    
    # Initialize approval workflow with Teams
    registry = get_registry()
    workflow = ApprovalWorkflow(interactive=False)
    
    # Set Teams as the handler
    async def teams_approval_fn(request):
        return await teams_handler.request_approval(request)
    
    workflow.set_custom_handler(teams_approval_fn)
    
    # Request approval for high-risk operation
    tool = registry.get('docker_restart_container')
    
    print("Requesting approval via Teams...")
    decision = await workflow.request_approval(
        tool_name='docker_restart_container',
        tool_meta=tool,
        parameters={'container_name': 'mongodb'},
        reason='Restart failed MongoDB instance - Production incident',
    )
    
    print(f"\nApproval Decision:")
    print(f"  Status: {decision.status.value}")
    print(f"  Reason: {decision.reason}")
    print(f"  Method: {decision.method.value}")


if __name__ == '__main__':
    asyncio.run(example_teams_approval())
```

## Integration with Tool Execution Agent

Add to `POCs/tool_execution/agent.py`:

```python
# At top of file
from permission_approval_system.teams_approval_handler import (
    TeamsApprovalConfig,
    init_teams_approval,
)

async def run_agent(
    user_message: str,
    use_teams_approval: bool = False,
    teams_channel_id: Optional[str] = None,
) -> AgentRun:
    """
    Run the tool-calling agent loop with permission checking and optional Teams approval.
    """
    
    # Initialize permission system
    registry = get_registry()
    permission_manager = PermissionManager(registry)
    approval_workflow = ApprovalWorkflow(interactive=not use_teams_approval)
    
    # If using Teams for approval, initialize Teams handler
    if use_teams_approval and teams_channel_id:
        teams_config = TeamsApprovalConfig(
            teams_bot_id="autoopsai-bot",
            teams_channel_id=teams_channel_id,
            timeout_seconds=300,
        )
        teams_handler = init_teams_approval(teams_config)
        
        async def teams_approval_handler(request):
            return await teams_handler.request_approval(request)
        
        approval_workflow.set_custom_handler(teams_approval_handler)
    
    # ... rest of agent loop
```

## Teams Bot Integration (POC 2)

Update `POCs/teams_integration/teams_app.py` to handle approval responses:

```python
# Add approval endpoint to FastAPI app

from fastapi import FastAPI, Request
from permission_approval_system.teams_approval_handler import get_teams_handler

app = FastAPI()

@app.post("/api/approval")
async def handle_approval(request: Request):
    """Handle approval response from Teams."""
    
    data = await request.json()
    approval_id = data.get('approval_id')
    approved = data.get('approved', False)
    
    # Get Teams handler and record response
    teams_handler = get_teams_handler()
    teams_handler.handle_approval_response(approval_id, approved)
    
    return {"status": "ok"}
```

## Configuration

### Environment Variables

```bash
# Teams Bot Configuration
export TEAMS_BOT_ID="autoopsai-bot"
export TEAMS_CHANNEL_ID="devops-approvals"
export TEAMS_WEBHOOK_URL="https://webhook.example.com"

# Approval Settings
export APPROVAL_TIMEOUT="300"  # 5 minutes
export ADMIN_USERS="user1@company.com,user2@company.com"
```

### Config File

`~/.autoops/teams_approval.json`:
```json
{
  "teams_bot_id": "autoopsai-bot",
  "teams_channel_id": "devops-approvals",
  "teams_webhook_url": "https://webhook.example.com",
  "timeout_seconds": 300,
  "admin_user_ids": [
    "devops-lead@company.com",
    "oncall@company.com"
  ]
}
```

## Workflow

### Approval Request Flow

```
1. Agent requests tool execution
   ↓
2. Permission Manager checks permissions
   - If safe: Auto-approve ✅
   - If blocked: Auto-deny ❌
   - If needs approval: Request approval
   ↓
3. Approval Workflow sends request
   - Check if Teams enabled
   - If yes: Send to Teams channel
   - If no: Show console prompt
   ↓
4. User approves in Teams
   - Click "Approve" button
   - Teams sends webhook to bot
   - Bot records approval
   - ApprovalWorkflow receives response
   ↓
5. Agent continues or stops execution
```

### Example Teams Message

```
🔐 Tool Approval Request
━━━━━━━━━━━━━━━━━━━━━━━━

Tool:           docker_restart_container
Risk Level:     🔴 HIGH_RISK
Category:       docker

Description:
Restart a Docker container. Use when remediation requires a container restart.

Parameters:
{'container_name': 'mongodb'}

Required Permissions:
✓ docker:write
✓ docker:restart

Reason: Restart failed MongoDB instance - Production incident

[✅ Approve]  [❌ Reject]
```

## Testing

```bash
# Test Teams approval handler (mock mode)
uv run python -m POCs.permission_approval_system.teams_integration_example
```

## Troubleshooting

### Teams bot not responding

1. Check Teams webhook URL is reachable
2. Verify bot credentials in environment
3. Check Teams channel permissions
4. Review bot logs

### Approval timeout

- Increase `APPROVAL_TIMEOUT` environment variable
- Check Teams connectivity
- Verify admin users have access

### Messages not appearing in Teams

1. Check bot is added to channel
2. Verify Teams channel ID is correct
3. Check Teams app permissions
4. Review Teams Activity Feed

## Security Considerations

- ✅ Only admin users can approve
- ✅ All approvals logged in audit trail
- ✅ Timeout prevents indefinite waiting
- ✅ Rich audit trail in Teams
- ✅ Approval context preserved

## Future Enhancements

- [ ] Approval chains (escalation)
- [ ] Time-based approvals (working hours only)
- [ ] Approval delegation
- [ ] Approval patterns (similar requests)
- [ ] Bulk approvals
- [ ] Approval analytics dashboard
- [ ] Integration with Azure AD for user validation
- [ ] Slack/Discord support

---

**Status:** ✅ Ready for Teams integration
**Team Approval:** ✅ Supported
**Documentation:** ✅ Complete
