# [Step 01] — Project Setup & Scaffolding

## Context

Empty repository at `/Users/dattaikhe/LLM/AutoOpsAI`. No Python project exists yet. The `docs/` directory contains architecture and design documents. No source files exist.

## Objective

Produce a fully configured Python project with all dependencies declared, a working Pydantic Settings config module, the complete directory skeleton (all `__init__.py` files), a `.env.example`, and a `docker-compose.agent.yml` that brings up the AutoOps agent, Celery worker, and Redis.

## Files to Create

- `pyproject.toml` — Python project definition with all runtime and dev dependencies, ruff config, mypy config, pytest config.
- `.env.example` — All environment variables the system reads, with placeholder values and a comment on each line explaining what it is. Never populated with real secrets.
- `agent/__init__.py` — Empty, marks package.
- `agent/config.py` — Pydantic Settings class (`AgentSettings`) reading all environment variables. Single `get_settings()` function with `lru_cache` for singleton access.
- `agent/collector/__init__.py` — Empty.
- `agent/engine/__init__.py` — Empty.
- `agent/knowledge/__init__.py` — Empty.
- `agent/llm/__init__.py` — Empty.
- `agent/providers/__init__.py` — Empty.
- `agent/approval/__init__.py` — Empty.
- `agent/remediation/__init__.py` — Empty.
- `agent/store/__init__.py` — Empty.
- `agent/tasks/__init__.py` — Celery app definition (see Key Requirements).
- `agent/ws/__init__.py` — Empty.
- `agent/api/__init__.py` — Empty.
- `agent/api/routers/__init__.py` — Empty.
- `agent/auth/__init__.py` — Empty.
- `tests/__init__.py` — Empty.
- `tests/test_providers/__init__.py` — Empty.
- `tests/e2e/__init__.py` — Empty.
- `playbooks/.gitkeep` — Empty placeholder.
- `chaos/docker/.gitkeep` — Empty placeholder.
- `infra/demo-app/.gitkeep` — Empty placeholder.
- `infra/docker-compose/.gitkeep` — Empty placeholder.
- `frontend/.gitkeep` — Empty placeholder.
- `docker-compose.agent.yml` — Services: `autoops-agent`, `autoops-worker`, `redis`.

## Files to Modify

None — this is the initial scaffold step.

## Key Requirements

**pyproject.toml dependencies (exact package names):**
```
fastapi
uvicorn[standard]
docker
ollama
pydantic
pydantic-settings
httpx
pyyaml
pytest
pytest-asyncio
prometheus-client
celery[redis]
redis[hiredis]
motor
beanie
python-jose[cryptography]
passlib[bcrypt]
websockets
watchfiles
botbuilder-core
botbuilder-integration-aiohttp
ruff
mypy
slowapi
```

Use `[project]` table in pyproject.toml with `requires-python = ">=3.11"`. Set `name = "autoops-ai"`, `version = "0.1.0"`. Separate `[project.optional-dependencies]` with `dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]`. Add `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `testpaths = ["tests"]`. Add `[tool.ruff]` with `line-length = 100` and `select = ["E", "F", "I"]`. Add `[tool.mypy]` with `python_version = "3.11"` and `ignore_missing_imports = true`.

**agent/config.py — AgentSettings fields (exact names and types):**
```python
# LLM
ollama_host: str = "http://localhost:11434"
ollama_model: str = "llama3:8b"
ollama_timeout_seconds: int = 30

# Infrastructure
provider_type: str = "docker_compose"
provider_project_name: str = "autoops-demo"
provider_compose_file: str = "./infra/docker-compose/docker-compose.target.yml"
polling_interval_seconds: int = 15

# Database (AutoOps data store — NOT the monitored demo MongoDB)
mongodb_url: str = "mongodb://autoops:secret@localhost:27017/autoops"
mongodb_database: str = "autoops"

# Task queue
celery_broker_url: str = "redis://localhost:6379/0"
celery_result_backend: str = "redis://localhost:6379/1"

# Observability
prometheus_url: str = "http://prometheus:9090"
loki_url: str = "http://loki:3100"
grafana_url: str = "http://grafana:3000"

# Teams
teams_app_id: str = ""
teams_app_password: str = ""
teams_webhook_url: str = ""
teams_tenant_id: str = ""
teams_local_emulator: bool = True

# Auth
api_key: str = "changeme"
jwt_secret_key: str = "changeme"
jwt_algorithm: str = "HS256"
jwt_access_token_expire_minutes: int = 60
jwt_refresh_token_expire_days: int = 7

# Thresholds
cpu_high_threshold: float = 90.0
memory_high_threshold: float = 85.0
error_rate_high_threshold: float = 50.0
cooldown_default_seconds: int = 300

# App
app_version: str = "0.1.0"
debug: bool = False
```

Use `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)`.

**agent/tasks/__init__.py — Celery app definition:**
```python
from celery import Celery
from agent.config import get_settings

def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "autoops",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=[
            "agent.tasks.remediation_task",
            "agent.tasks.verification_task",
            "agent.tasks.rollback_task",
        ],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
    )
    return app

celery_app = create_celery_app()
```

**docker-compose.agent.yml:**
- `autoops-agent` service: image `autoops-agent:latest`, build context `.`, command `uvicorn agent.main:app --host 0.0.0.0 --port 8000`, ports `8000:8000`, env_file `.env`, depends_on `redis`.
- `autoops-worker` service: image `autoops-agent:latest`, build context `.`, command `celery -A agent.tasks worker --loglevel=info --concurrency=4`, env_file `.env`, depends_on `redis`.
- `redis` service: image `redis:7-alpine`, ports `6379:6379`.
- All three services share network `autoops-agent-net`.

**Naming conventions:**
- All Python package directories must have `__init__.py` files.
- `agent/api/routers/` must exist (used in steps 23, 29, 30).

## Test Criteria

```bash
# Verify Python project structure
cd /Users/dattaikhe/LLM/AutoOpsAI
python -c "from agent.config import get_settings; s = get_settings(); print(s.app_version)"
# Expected: 0.1.0

# Verify all __init__.py exist
python -c "import agent; import agent.collector; import agent.engine; import agent.knowledge; import agent.llm; import agent.providers; import agent.approval; import agent.remediation; import agent.store; import agent.tasks; import agent.ws; import agent.api; import agent.auth; print('all packages OK')"
# Expected: all packages OK

# Verify Celery app loads
python -c "from agent.tasks import celery_app; print(celery_app.main)"
# Expected: autoops

# Verify pyproject.toml parses
python -c "import tomllib; data = tomllib.load(open('pyproject.toml', 'rb')); print(data['project']['name'])"
# Expected: autoops-ai

# Verify .env.example exists and has content
wc -l .env.example
# Expected: >20 lines
```

## Dependencies

None — this is the first step.
