# [Step 31] — Audit Logging & Security Hardening

## Context

Steps 01-30 are complete. The following exist:
- `agent/store/documents.py` — `AuditLogDocument` (user_id, action, resource_type, resource_id, detail, ip_address, timestamp, TTL index 90 days)
- `agent/auth/dependencies.py` — `get_current_user` (returns `UserDocument`)
- All API routers from steps 23 and 30
- `slowapi` installed (from step 01 pyproject.toml)

## Objective

Produce the audit logging middleware and manual audit helpers, enforce audit writes on all state-changing actions, add rate limiting to auth endpoints, add security headers, enforce CORS to dashboard origin only, and add the audit log API endpoint.

## Files to Create

- `agent/store/audit.py` — `AuditStore` CRUD + async write helper.
- `agent/api/routers/admin.py` — Admin-only endpoints (users CRUD, audit log).
- `tests/test_audit.py` — Audit log unit tests.

## Files to Modify

- `agent/main.py` — Add rate limiting, security headers middleware, tighten CORS.
- `agent/api/routers/incidents.py` — Add audit write on escalate.
- `agent/approval/dashboard_approval.py` — Add audit writes on approve/deny/investigate.
- `agent/approval/teams_bot.py` — Add audit writes on Teams approvals.
- `agent/api/routers/playbooks.py` — Add audit writes on create/update/delete.
- `agent/api/routers/agent_control.py` — Add audit writes on start/stop/config update.

## Key Requirements

**agent/store/audit.py:**

```python
from datetime import datetime, timezone
from typing import Optional
from agent.store.documents import AuditLogDocument

class AuditStore:

    @staticmethod
    async def log(
        user_id: str,
        username: str,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: str = "",
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Write an audit log entry. Fire-and-forget — never raises.
        If MongoDB write fails, log a warning but do not block the response.
        """
        try:
            entry = AuditLogDocument(
                user_id=user_id,
                username=username,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail,
                ip_address=ip_address,
                timestamp=datetime.now(timezone.utc),
            )
            await entry.insert()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Audit log write failed: %s", exc)

    @staticmethod
    async def list(
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditLogDocument], int]:
        """List audit entries with optional filters. Sorted by timestamp desc."""
        query = AuditLogDocument.find()
        if user_id:
            query = query.find(AuditLogDocument.user_id == user_id)
        if action:
            query = query.find(AuditLogDocument.action == action)
        if resource_type:
            query = query.find(AuditLogDocument.resource_type == resource_type)
        total = await query.count()
        docs = await query.sort(-AuditLogDocument.timestamp).skip(offset).limit(limit).to_list()
        return docs, total
```

**Standardized action strings for audit log:**

| Action | resource_type | Triggered by |
|---|---|---|
| `"approve"` | `"incident"` | approve endpoint, Teams bot |
| `"deny"` | `"incident"` | deny endpoint, Teams bot |
| `"investigate"` | `"incident"` | investigate endpoint, Teams bot |
| `"escalate"` | `"incident"` | escalate endpoint |
| `"playbook.create"` | `"playbook"` | playbook POST |
| `"playbook.update"` | `"playbook"` | playbook PUT |
| `"playbook.delete"` | `"playbook"` | playbook DELETE |
| `"agent.start"` | `"agent"` | agent start endpoint |
| `"agent.stop"` | `"agent"` | agent stop endpoint |
| `"agent.config_update"` | `"agent"` | config PATCH endpoint |
| `"user.create"` | `"user"` | user management |
| `"user.role_change"` | `"user"` | user role update |
| `"login"` | `"user"` | login endpoint |
| `"login_failed"` | `"user"` | login with wrong password |

**Audit writes in endpoint handlers — pattern to follow:**

```python
# In every state-changing endpoint:
@router.post("/incidents/{incident_id}/escalate",
             dependencies=[Depends(require_role(ADMIN, OPERATOR))])
async def escalate_incident(
    incident_id: str,
    body: dict = Body(default={}),
    request: Request = None,
    current_user: UserDocument = Depends(get_current_user),
) -> dict:
    reason = body.get("reason", "")
    success = await IncidentStore.escalate(incident_id, reason)
    if not success:
        return not_found("Incident", incident_id)
    # Audit log — after successful state change
    await AuditStore.log(
        user_id=str(current_user.id),
        username=current_user.username,
        action="escalate",
        resource_type="incident",
        resource_id=incident_id,
        detail=reason,
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "escalated", "incident_id": incident_id}
```

Apply the same pattern to all state-changing endpoints listed above.

**agent/api/routers/admin.py:**

```python
from fastapi import APIRouter, Depends
from agent.auth.rbac import ADMIN
from agent.auth.dependencies import require_role
from agent.auth.users import UserStore
from agent.store.audit import AuditStore

router = APIRouter(prefix="/api/v1/admin", tags=["admin"],
                   dependencies=[Depends(require_role(ADMIN))])

# User management
@router.get("/users")
async def list_users() -> dict:
    """List all users. Admin only."""
    users = await UserDocument.find_all().to_list()
    return {"users": [{"id": str(u.id), "username": u.username,
                        "email": u.email, "role": u.role} for u in users]}

@router.post("/users")
async def create_user(body: dict, current_user=Depends(get_current_user)) -> dict:
    """Create a new user. Body: {username, email, password, role}"""
    user = await UserStore.create(
        username=body["username"],
        email=body.get("email", ""),
        password=body["password"],
        role=body.get("role", "viewer"),
    )
    await AuditStore.log(str(current_user.id), current_user.username,
                         "user.create", "user", str(user.id),
                         detail=f"role={user.role}")
    return {"id": str(user.id), "username": user.username, "role": user.role}

@router.patch("/users/{user_id}/role")
async def update_user_role(user_id: str, body: dict, current_user=Depends(get_current_user)) -> dict:
    """Change a user's role. Body: {role: "admin"|"operator"|"viewer"}"""
    new_role = body.get("role")
    if new_role not in ["admin", "operator", "viewer"]:
        raise HTTPException(400, "role must be admin, operator, or viewer")
    user = await UserStore.get_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    old_role = user.role
    user.role = new_role
    await user.save()
    await AuditStore.log(str(current_user.id), current_user.username,
                         "user.role_change", "user", user_id,
                         detail=f"{old_role} → {new_role}")
    return {"user_id": user_id, "role": new_role}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, current_user=Depends(get_current_user)) -> dict:
    """Delete a user. Cannot delete yourself."""
    if user_id == str(current_user.id):
        raise HTTPException(400, "Cannot delete your own account")
    user = await UserStore.get_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await user.delete()
    return {"deleted": user_id}

# Audit log
@router.get("/audit")
async def get_audit_log(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Filterable audit log. Admin only."""
    docs, total = await AuditStore.list(
        user_id=user_id, action=action, resource_type=resource_type,
        limit=limit, offset=offset,
    )
    return {
        "entries": [{"timestamp": d.timestamp.isoformat(), "username": d.username,
                     "action": d.action, "resource_type": d.resource_type,
                     "resource_id": d.resource_id, "detail": d.detail,
                     "ip_address": d.ip_address} for d in docs],
        "total": total, "limit": limit, "offset": offset,
    }
```

Mount admin router in `agent/main.py`:
```python
from agent.api.routers.admin import router as admin_router
app.include_router(admin_router)
```

**Rate limiting on auth endpoints (`agent/main.py`):**

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to login endpoint in auth.py:
from slowapi.extension import limit

@router.post("/login")
@limiter.limit("10/minute")  # max 10 login attempts per minute per IP
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    ...
```

**Security headers middleware (`agent/main.py`):**

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

**Tighten CORS (replace the development wildcard):**

```python
# In create_app(), replace the development CORS config:
ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # production: set to dashboard FQDN only
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
```

Add `CORS_ALLOWED_ORIGINS` to `agent/config.py` and `.env.example`.

**No secrets in logs — log redaction:**

Add a log filter to redact sensitive fields:

```python
import logging
import re

class SecretRedactingFilter(logging.Filter):
    PATTERNS = [
        (re.compile(r'(password["\s:=]+)[^\s,"\']+', re.I), r'\1[REDACTED]'),
        (re.compile(r'(token["\s:=]+)[^\s,"\']+', re.I), r'\1[REDACTED]'),
        (re.compile(r'(Authorization:\s*Bearer\s+)\S+', re.I), r'\1[REDACTED]'),
    ]
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(str(record.msg))
        return True

    def _redact(self, text: str) -> str:
        for pattern, replacement in self.PATTERNS:
            text = pattern.sub(replacement, text)
        return text

# Apply to root logger in main.py startup:
logging.getLogger().addFilter(SecretRedactingFilter())
```

**tests/test_audit.py:**

All tests `@pytest.mark.asyncio`.

Required test cases:
1. `test_audit_log_write` — call `AuditStore.log()`, fetch from DB, assert all fields present.
2. `test_audit_log_write_never_raises` — mock DB insert raising an exception, call `log()`, assert no exception propagates.
3. `test_audit_list_filter_by_action` — insert 3 logs with different actions, filter, assert only matching returned.
4. `test_approve_endpoint_writes_audit` — mock approve endpoint call, assert `AuditStore.log` called with `action="approve"`.
5. `test_admin_audit_log_endpoint` — admin token, `GET /api/v1/admin/audit`, assert 200 + `"entries"` key.
6. `test_viewer_cannot_access_audit` — viewer token, assert 403.
7. `test_rate_limit_login` — send 11 login attempts in a loop, assert 11th returns 429.
8. `test_security_headers_present` — `GET /health`, assert `X-Content-Type-Options` header present.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_audit.py -v
# Expected: all 8 tests pass

# Verify no unguarded state-changing endpoints
python -c "
from agent.main import app
for route in app.routes:
    if hasattr(route, 'methods') and {'POST','PUT','PATCH','DELETE'} & route.methods:
        deps = [str(d) for d in getattr(route, 'dependencies', [])]
        print(route.path, route.methods, 'has deps:', bool(deps))
"
# Expected: all POST/PUT/PATCH/DELETE routes have at least one dependency

# Phase 6 exit criteria check:
python -c "
from agent.auth.passwords import hash_password, verify_password
from agent.auth.tokens import create_access_token, create_refresh_token
from agent.store.audit import AuditStore
from agent.api.routers.admin import router as admin_router
print('all phase 6 imports OK')
"
```

**Phase 6 exit criteria:** JWT auth works end-to-end (login → access token → API calls). RBAC enforced: viewer cannot approve/escalate, operator cannot approve HIGH risk, admin can do everything. Audit log captures every approval/denial/escalation/playbook edit. Rate limiting rejects brute-force login. Security headers present on all responses.

## Dependencies

- Step 08 (AuditLogDocument, UserDocument)
- Step 22 (FastAPI main app, middleware pattern)
- Step 23 (API endpoints)
- Step 29 (JWT auth, UserStore)
- Step 30 (RBAC — require_role dependencies already applied to endpoints)
