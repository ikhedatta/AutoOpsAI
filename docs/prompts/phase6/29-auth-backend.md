# [Step 29] — Auth Backend (JWT + bcrypt)

## Context

Steps 01-28 are complete. The following exist:
- `agent/store/documents.py` — `UserDocument` (username, email, hashed_password, role, Teams UPN)
- `agent/auth/__init__.py` — package exists
- `agent/config.py` — `jwt_secret_key`, `jwt_algorithm`, `jwt_access_token_expire_minutes`, `jwt_refresh_token_expire_days`
- `agent/api/dependencies.py` — `verify_api_key` (static key guard, to be replaced)
- `agent/main.py` — FastAPI app, router mounting

## Objective

Produce the full JWT auth system: token creation, validation, refresh, user CRUD, bcrypt password hashing, FastAPI dependency injection, and login/refresh/me endpoints. Wire it into the app so all existing API key guards can be replaced by JWT dependencies in Step 30.

## Files to Create

- `agent/auth/passwords.py` — bcrypt hashing helpers.
- `agent/auth/tokens.py` — JWT creation and validation.
- `agent/auth/users.py` — User CRUD via Beanie.
- `agent/auth/dependencies.py` — FastAPI dependencies: `get_current_user`, `require_role`.
- `agent/api/routers/auth.py` — Login, refresh, and `/me` endpoints.
- `tests/test_auth.py` — Auth unit tests.

## Files to Modify

- `agent/main.py` — Add auth router, add first-run admin seed.

## Key Requirements

**agent/auth/passwords.py:**

```python
from passlib.context import CryptContext

_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt. Returns the hashed string."""
    return _ctx.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash. Constant-time comparison."""
    return _ctx.verify(plain, hashed)
```

**agent/auth/tokens.py:**

```python
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from agent.config import get_settings

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

def create_access_token(user_id: str, username: str, role: str) -> str:
    """
    Create a JWT access token.
    Payload: sub=user_id, username=username, role=role, type="access", exp=now+expire_minutes
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def create_refresh_token(user_id: str) -> str:
    """
    Create a JWT refresh token.
    Payload: sub=user_id, type="refresh", exp=now+expire_days
    Refresh tokens contain only user_id (not role — role may change between refreshes).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": REFRESH_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(days=settings.jwt_refresh_token_expire_days),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT. Returns payload dict.
    Raises jose.JWTError on invalid/expired token.
    """
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

def verify_access_token(token: str) -> dict:
    """
    Decode + assert type=="access".
    Raises JWTError if invalid, expired, or wrong type.
    """
    payload = decode_token(token)
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise JWTError("Not an access token")
    return payload

def verify_refresh_token(token: str) -> dict:
    """
    Decode + assert type=="refresh".
    Raises JWTError if invalid, expired, or wrong type.
    """
    payload = decode_token(token)
    if payload.get("type") != REFRESH_TOKEN_TYPE:
        raise JWTError("Not a refresh token")
    return payload
```

**agent/auth/users.py:**

```python
from typing import Optional
from agent.store.documents import UserDocument
from agent.auth.passwords import hash_password, verify_password

class UserStore:

    @staticmethod
    async def create(username: str, email: str, password: str, role: str = "viewer") -> UserDocument:
        """
        Create a new user. Hashes password before saving.
        Raises ValueError if username already exists.
        """
        existing = await UserDocument.find_one(UserDocument.username == username)
        if existing:
            raise ValueError(f"Username '{username}' already taken")
        doc = UserDocument(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=role,
        )
        await doc.insert()
        return doc

    @staticmethod
    async def get_by_username(username: str) -> Optional[UserDocument]:
        return await UserDocument.find_one(UserDocument.username == username)

    @staticmethod
    async def get_by_id(user_id: str) -> Optional[UserDocument]:
        """Fetch by string ID (converted from PydanticObjectId)."""
        from beanie import PydanticObjectId
        return await UserDocument.get(PydanticObjectId(user_id))

    @staticmethod
    async def authenticate(username: str, password: str) -> Optional[UserDocument]:
        """
        Verify username + password. Returns user if valid, None if not found or wrong password.
        Does NOT raise on wrong password — returns None for security (no timing oracle).
        """
        user = await UserStore.get_by_username(username)
        if not user:
            # Run verify_password anyway to prevent timing attacks
            verify_password(password, "$2b$12$fakehashfakehashfakehashfakehashfakehashfakeha")
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    async def update_last_login(user_id: str) -> None:
        from datetime import datetime, timezone
        user = await UserStore.get_by_id(user_id)
        if user:
            user.last_login = datetime.now(timezone.utc)
            await user.save()

    @staticmethod
    async def seed_admin_if_empty(admin_password: str) -> None:
        """
        Create default admin user if no users exist.
        Called at startup from main.py lifespan.
        Admin username: "admin", role: "admin".
        Logs a warning to change the password.
        """
        count = await UserDocument.count()
        if count == 0:
            await UserStore.create("admin", "admin@autoops.local", admin_password, role="admin")
            import logging
            logging.getLogger(__name__).warning(
                "Default admin user created. Change the password immediately via PATCH /api/v1/auth/me."
            )
```

**agent/auth/dependencies.py:**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from agent.auth.tokens import verify_access_token
from agent.auth.users import UserStore
from agent.store.documents import UserDocument

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserDocument:
    """
    FastAPI dependency — decode JWT and return current user.
    Raises HTTP 401 if token invalid, expired, or user not found.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = verify_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = await UserStore.get_by_id(user_id)
    if not user:
        raise credentials_exc
    return user

def require_role(*allowed_roles: str):
    """
    Factory: returns a FastAPI dependency that checks the user's role.
    Usage: Depends(require_role("admin", "operator"))
    """
    async def dependency(current_user: UserDocument = Depends(get_current_user)) -> UserDocument:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(allowed_roles)}. Your role: {current_user.role}",
            )
        return current_user
    return dependency
```

**agent/api/routers/auth.py:**

```python
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from agent.auth.users import UserStore
from agent.auth.tokens import create_access_token, create_refresh_token, verify_refresh_token
from agent.auth.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    """
    Authenticate with username + password.
    Uses OAuth2PasswordRequestForm (form-encoded, not JSON) to be compatible with
    FastAPI's automatic /docs "Authorize" button.
    Returns: access_token, refresh_token, token_type="bearer"
    """
    user = await UserStore.authenticate(form.username, form.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    await UserStore.update_last_login(str(user.id))
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.username, user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest) -> TokenResponse:
    """
    Exchange a refresh token for a new access + refresh token pair.
    Raises 401 if refresh token is invalid or expired.
    """
    from jose import JWTError
    try:
        payload = verify_refresh_token(body.refresh_token)
        user_id = payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = await UserStore.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return TokenResponse(
        access_token=create_access_token(str(user.id), user.username, user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )

@router.get("/me")
async def me(current_user=Depends(get_current_user)) -> dict:
    """Return the current authenticated user's profile."""
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
    }
```

**agent/main.py additions:**

In the lifespan startup section, after `init_db()`:
```python
from agent.auth.users import UserStore
from agent.config import get_settings
settings = get_settings()
await UserStore.seed_admin_if_empty(admin_password=settings.api_key or "admin")
```

In `create_app()`:
```python
from agent.api.routers.auth import router as auth_router
app.include_router(auth_router)
```

**Frontend wiring (update `frontend/src/api/client.ts`):**

Add JWT interceptor:
```typescript
// Store tokens in memory (not localStorage — avoids XSS risk)
let accessToken: string | null = null

export function setAccessToken(token: string) { accessToken = token }
export function clearAccessToken() { accessToken = null }

// Request interceptor: attach Bearer token
apiClient.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
  return config
})

// 401 interceptor: attempt token refresh
apiClient.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      // Attempt refresh — handled in useAuth hook (step 29 frontend)
      window.dispatchEvent(new Event('auth:expired'))
    }
    return Promise.reject(error)
  }
)

// Auth API
api.login = (username: string, password: string) =>
  apiClient.post<TokenResponse>('/auth/login',
    new URLSearchParams({ username, password }),
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
  ).then(r => r.data)

api.refresh = (refreshToken: string) =>
  apiClient.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken })
    .then(r => r.data)

api.me = () => apiClient.get('/auth/me').then(r => r.data)
```

**tests/test_auth.py:**

All tests `@pytest.mark.asyncio`. Use in-memory MongoDB via `mongomock-motor` or mock `UserStore`.

Required test cases:
1. `test_hash_and_verify_password` — hash a password, verify matches, verify wrong password returns False.
2. `test_create_access_token_decodes_correctly` — create token, decode, assert sub/username/role/type.
3. `test_access_token_rejects_refresh_token` — create refresh token, call `verify_access_token`, assert raises JWTError.
4. `test_refresh_token_rejects_access_token` — reverse of above.
5. `test_login_endpoint_success` — mock `UserStore.authenticate` returning valid user, POST `/api/v1/auth/login`, assert 200 + access_token.
6. `test_login_endpoint_wrong_password` — mock returns None, assert 401.
7. `test_me_endpoint_valid_token` — set Bearer token in header, assert 200 + username.
8. `test_me_endpoint_no_token` — no Authorization header, assert 401.
9. `test_refresh_endpoint` — create refresh token, POST `/api/v1/auth/refresh`, assert new access token returned.
10. `test_seed_admin_creates_user` — mock empty DB, call `seed_admin_if_empty`, assert user created with role=admin.

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI
pytest tests/test_auth.py -v
# Expected: all 10 tests pass

python -c "
from agent.auth.passwords import hash_password, verify_password
from agent.auth.tokens import create_access_token, verify_access_token
from agent.auth.dependencies import get_current_user, require_role
from agent.api.routers.auth import router
print('auth imports OK')
"

# Verify login endpoint available
python -c "
from agent.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/auth/login' in routes, 'login route missing'
assert '/api/v1/auth/refresh' in routes
assert '/api/v1/auth/me' in routes
print('auth routes registered OK')
"
```

## Dependencies

- Step 01 (python-jose, passlib[bcrypt] installed)
- Step 08 (MongoDB setup, UserDocument)
- Step 22 (FastAPI main app)
