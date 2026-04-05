# [Step 30] — RBAC Enforcement

## Context

Step 29 is complete. The following exist:
- `agent/auth/dependencies.py` — `get_current_user`, `require_role`
- `agent/api/dependencies.py` — `verify_api_key` (static key guard — now replaced)
- All API routers from step 23
- Frontend auth interceptors (step 29)

## Objective

Replace the static `X-API-Key` guard with JWT `require_role` on every endpoint. Enforce the production permission matrix from the production implementation plan. Add Teams user identity mapping for approval decisions made via the Teams bot.

## Files to Modify

- `agent/api/dependencies.py` — Replace `verify_api_key` with JWT-based alternatives.
- `agent/api/routers/incidents.py` — Add role guards.
- `agent/api/routers/agent_control.py` — Add role guards.
- `agent/api/routers/playbooks.py` — Add role guards.
- `agent/api/routers/chat.py` — Add role guards.
- `agent/approval/dashboard_approval.py` — Add role guards.
- `agent/approval/teams_bot.py` — Add Teams UPN → AutoOps user mapping.
- `agent/ws/router.py` — Add JWT auth to WebSocket handshake.
- `frontend/src/pages/` — Add login page and protected route wrapper.

## Files to Create

- `agent/auth/rbac.py` — Permission matrix constants and helper.
- `frontend/src/pages/LoginPage.tsx` — Login form.
- `frontend/src/hooks/useAuth.ts` — JWT token management hook.
- `frontend/src/components/layout/ProtectedRoute.tsx` — Route guard.
- `tests/test_rbac.py` — RBAC enforcement tests.

## Key Requirements

**Permission matrix (from production-implementation-plan.md):**

| Action | Admin | Operator | Viewer |
|---|---|---|---|
| View incidents, health, metrics | ✅ | ✅ | ✅ |
| Approve/deny MEDIUM risk | ✅ | ✅ | ❌ |
| Approve/deny HIGH risk | ✅ | ❌ | ❌ |
| Escalate incident | ✅ | ✅ | ❌ |
| Start/stop agent | ✅ | ❌ | ❌ |
| Create/edit playbooks | ✅ | ✅ | ❌ |
| Delete playbooks | ✅ | ❌ | ❌ |
| Manage users | ✅ | ❌ | ❌ |
| Update agent config | ✅ | ❌ | ❌ |
| View audit log | ✅ | ❌ | ❌ |

**agent/auth/rbac.py:**

```python
# Role constants
ADMIN = "admin"
OPERATOR = "operator"
VIEWER = "viewer"
ALL_ROLES = [ADMIN, OPERATOR, VIEWER]

# Permission groups
CAN_VIEW = [ADMIN, OPERATOR, VIEWER]           # GET endpoints
CAN_OPERATE = [ADMIN, OPERATOR]                # approve MEDIUM, escalate, create playbooks
CAN_APPROVE_HIGH = [ADMIN]                     # approve HIGH risk only
CAN_ADMIN = [ADMIN]                            # start/stop agent, delete playbooks, manage users
```

**agent/api/dependencies.py — replace `verify_api_key`:**

```python
# Keep verify_api_key as a backwards-compatible no-op stub during transition:
async def verify_api_key() -> None:
    """Deprecated: replaced by JWT auth in step 30. Kept to avoid import errors."""
    pass

# New: JWT-based dependencies (import from agent.auth.dependencies)
from agent.auth.dependencies import get_current_user, require_role
```

All routers that previously used `Depends(verify_api_key)` now use `Depends(require_role(...))`.

**Updated router guards (apply to each router):**

```python
# agent/api/routers/incidents.py
@router.get("/incidents")   # No auth required — viewers can read
@router.get("/incidents/{id}")   # No auth required
@router.post("/incidents/{id}/escalate",
             dependencies=[Depends(require_role(ADMIN, OPERATOR))])

# agent/api/routers/agent_control.py
@router.post("/agent/start", dependencies=[Depends(require_role(ADMIN))])
@router.post("/agent/stop", dependencies=[Depends(require_role(ADMIN))])
@router.get("/agent/config")   # No auth required
@router.patch("/agent/config", dependencies=[Depends(require_role(ADMIN))])

# agent/api/routers/playbooks.py
@router.get("/playbooks")   # No auth
@router.get("/playbooks/{id}")   # No auth
@router.post("/playbooks", dependencies=[Depends(require_role(ADMIN, OPERATOR))])
@router.put("/playbooks/{id}", dependencies=[Depends(require_role(ADMIN, OPERATOR))])
@router.delete("/playbooks/{id}", dependencies=[Depends(require_role(ADMIN))])

# agent/approval/dashboard_approval.py — approval actions gate on risk level
```

**Risk-level-aware approval guard:**

The approval endpoints need to check both role AND risk level. Add a dependency to `dashboard_approval.py`:

```python
async def require_approval_permission(
    incident_id: str,
    current_user: UserDocument = Depends(get_current_user),
) -> UserDocument:
    """
    Gate: operator can approve MEDIUM, only admin can approve HIGH.
    Fetch incident's severity to determine required role.
    """
    incident = await IncidentStore.get(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")

    if incident.severity == "HIGH" and current_user.role != ADMIN:
        raise HTTPException(
            403,
            detail="HIGH risk approvals require admin role. "
                   f"Your role: {current_user.role}"
        )
    if incident.severity == "MEDIUM" and current_user.role not in [ADMIN, OPERATOR]:
        raise HTTPException(403, detail="Requires operator or admin role")

    return current_user

# Apply to all approval POST endpoints:
@router.post("/approval/{incident_id}/approve")
async def approve(incident_id: str, body: dict,
                  user: UserDocument = Depends(require_approval_permission)):
    result = await approval_router.process_decision(incident_id, "approve", user.username)
    return result
```

**Teams UPN → AutoOps user mapping (`agent/approval/teams_bot.py`):**

When `on_invoke_activity` processes a button click, map the Teams user to an AutoOps user for audit purposes:

```python
async def _resolve_teams_user(self, turn_context: TurnContext) -> str:
    """
    Get the Teams user's Azure AD UPN (user principal name) from the activity.
    Look up UserDocument by teams_upn field.
    If found: return username for audit trail.
    If not found: raise or return "unknown:<upn>" — deny approval with message.
    """
    upn = turn_context.activity.from_property.aad_object_id or \
          turn_context.activity.from_property.name
    user = await UserDocument.find_one(UserDocument.teams_upn == upn)
    if not user:
        await turn_context.send_activity(
            "You are not authorized to approve this action. "
            "Contact an admin to link your Teams account to AutoOps."
        )
        return None
    if user.role not in [ADMIN, OPERATOR]:
        await turn_context.send_activity(
            f"Your role ({user.role}) cannot approve actions. Requires operator or admin."
        )
        return None
    return user.username
```

Add `teams_upn: Optional[str] = None` to `UserDocument` if not already present.

**WebSocket JWT auth (`agent/ws/router.py`):**

```python
@ws_router.websocket("/api/v1/ws/events")
async def websocket_events(websocket: WebSocket, token: Optional[str] = Query(None)) -> None:
    """
    Accept WebSocket. Token passed as query param: ws://host/api/v1/ws/events?token=<jwt>
    If token invalid: close with 4001 (auth error). If no token: allow (viewer-level access).
    JWT auth on WebSocket is best-effort — events are non-sensitive (metric updates, not secrets).
    """
    if token:
        try:
            verify_access_token(token)
        except JWTError:
            await websocket.close(code=4001)
            return
    # Proceed with existing connection logic
    ...
```

**Frontend: useAuth.ts hook:**

```typescript
// frontend/src/hooks/useAuth.ts
import { useState, useCallback, useEffect } from 'react'
import { api, setAccessToken, clearAccessToken } from '../api/client'

interface AuthState {
  user: { username: string; role: string } | null
  isLoading: boolean
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({ user: null, isLoading: true })

  // Attempt to restore session from stored refresh token
  useEffect(() => {
    const stored = sessionStorage.getItem('refresh_token')
    if (stored) {
      api.refresh(stored)
        .then((tokens) => {
          setAccessToken(tokens.access_token)
          sessionStorage.setItem('refresh_token', tokens.refresh_token)
          return api.me()
        })
        .then((user) => setState({ user, isLoading: false }))
        .catch(() => { setState({ user: null, isLoading: false }) })
    } else {
      setState({ user: null, isLoading: false })
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const tokens = await api.login(username, password)
    setAccessToken(tokens.access_token)
    sessionStorage.setItem('refresh_token', tokens.refresh_token)
    const user = await api.me()
    setState({ user, isLoading: false })
    return user
  }, [])

  const logout = useCallback(() => {
    clearAccessToken()
    sessionStorage.removeItem('refresh_token')
    setState({ user: null, isLoading: false })
  }, [])

  // Handle auth:expired events from API interceptor
  useEffect(() => {
    const handler = () => logout()
    window.addEventListener('auth:expired', handler)
    return () => window.removeEventListener('auth:expired', handler)
  }, [logout])

  return { ...state, login, logout }
}
```

**Frontend: LoginPage.tsx and ProtectedRoute.tsx:**

`LoginPage.tsx`: Simple form with username/password inputs, calls `useAuth().login()`, redirects to `/health` on success. Shows error message on failure.

`ProtectedRoute.tsx`: Wraps `<Outlet />` with auth check — if `user` is null and not loading, redirect to `/login`. If loading, show spinner.

Update `App.tsx`: wrap all routes except `/login` in `<ProtectedRoute />`.

**tests/test_rbac.py:**

Use `httpx.AsyncClient` with mocked `get_current_user` dependency override.

Required test cases:
1. `test_viewer_can_list_incidents` — viewer token, `GET /api/v1/incidents`, assert 200.
2. `test_viewer_cannot_escalate` — viewer token, `POST /api/v1/incidents/xxx/escalate`, assert 403.
3. `test_operator_can_escalate` — operator token, assert 200.
4. `test_operator_cannot_approve_high_risk` — operator token, HIGH risk incident, approve, assert 403.
5. `test_admin_can_approve_high_risk` — admin token, HIGH risk incident, approve, assert not 403.
6. `test_viewer_cannot_delete_playbook` — viewer token, DELETE, assert 403.
7. `test_unauthenticated_gets_401` — no token, any protected endpoint, assert 401.
8. `test_teams_unknown_upn_denied` — mock Teams activity with unknown UPN, assert denial message sent.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_rbac.py -v
# Expected: all 8 tests pass

# Verify no endpoints still use static API key guard
grep -r "verify_api_key" agent/api/routers/
# Expected: only the stub definition in dependencies.py, no active Depends() usages

# Verify login flow
python -c "
from agent.main import app
routes = {r.path for r in app.routes}
assert '/api/v1/auth/login' in routes
print('auth routes present')
"
```

## Dependencies

- Step 23 (API endpoints)
- Step 29 (JWT auth — `get_current_user`, `require_role`)
- Step 20 (IncidentStore — for risk-level lookup in approval guard)
