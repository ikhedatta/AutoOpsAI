# [Step 05] — Demo Target Stack

## Context

Steps 01-04 are complete. The `infra/demo-app/` and `infra/docker-compose/` directories exist (with `.gitkeep` files). Docker Compose is available on the host.

## Objective

Produce a runnable demo infrastructure stack (Nginx + FastAPI demo app + MongoDB + Redis) on an isolated Docker network that can be started independently and deliberately broken by chaos scripts.

## Files to Create

- `infra/demo-app/app.py` — FastAPI application serving `/health`, `/data`, `/cache`.
- `infra/demo-app/requirements.txt` — Python dependencies for the demo app only.
- `infra/demo-app/Dockerfile` — Container image for the demo app.
- `infra/docker-compose/docker-compose.target.yml` — Compose file defining the 4-service demo stack.
- `infra/docker-compose/nginx.conf` — Nginx reverse proxy configuration.

## Files to Modify

None.

## Key Requirements

**CRITICAL NAMING:** The MongoDB container must be named `mongodb-demo` and the Redis container must be named `demo-redis`. These names are hardcoded in chaos scripts. The AutoOps production MongoDB (`MONGODB_URL` in `.env`) is a completely different instance — chaos scripts must NEVER reference it.

**infra/demo-app/app.py:**

```python
# Exact endpoints required:
# GET /health  — returns {"status": "ok", "mongodb": bool, "redis": bool, "timestamp": ISO}
#   - Tests both connections, returns degraded status if either fails
#   - Returns HTTP 200 if app itself is up (even if dependencies are down)
#   - Returns HTTP 503 if app cannot start at all

# GET /data  — reads from MongoDB, returns {"source": "mongodb", "count": int, "data": list}
#   - On MongoDB connection error: returns HTTP 503 with {"error": "mongodb unavailable"}

# GET /cache — reads key "demo-key" from Redis, writes it back with TTL 60s if missing
#   - Returns {"source": "redis", "value": str, "cache_hit": bool}
#   - On Redis connection error: returns HTTP 503 with {"error": "redis unavailable"}
```

Environment variables the app reads (with defaults):
```
MONGODB_HOST=mongodb-demo
MONGODB_PORT=27017
REDIS_HOST=demo-redis
REDIS_PORT=6379
APP_PORT=5000
```

Use `pymongo` for MongoDB (synchronous, not Motor — this is the demo app, not the agent). Use `redis-py` for Redis. Log every request using Python's `logging` module in JSON format:
```json
{"timestamp": "...", "method": "GET", "path": "/health", "status": 200, "duration_ms": 12.3}
```
Use `logging.basicConfig(format='%(message)s')` and emit JSON strings via `json.dumps()`. This structured format allows Promtail to ship logs to Loki with proper labels.

**infra/demo-app/requirements.txt:**
```
fastapi==0.110.0
uvicorn[standard]==0.27.0
pymongo==4.6.1
redis==5.0.1
```

**infra/demo-app/Dockerfile:**
- Base image: `python:3.11-slim`
- Non-root user: `RUN adduser --disabled-password --gecos "" appuser && USER appuser`
- WORKDIR `/app`
- COPY requirements.txt, RUN pip install, COPY app.py
- EXPOSE 5000
- CMD `["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]`

**infra/docker-compose/docker-compose.target.yml:**

```yaml
version: "3.9"

networks:
  autoops-demo-net:
    name: autoops-demo-net
    driver: bridge

services:
  nginx:
    image: nginx:1.25-alpine
    container_name: autoops-nginx
    ports:
      - "8080:80"        # Exposed on host port 8080
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - demo-app
    networks:
      - autoops-demo-net
    labels:
      com.docker.compose.project: autoops-demo
      autoops.health.type: http
      autoops.health.url: http://localhost:80/health

  demo-app:
    build:
      context: ../demo-app
      dockerfile: Dockerfile
    container_name: autoops-demo-app
    ports:
      - "5000:5000"
    environment:
      - MONGODB_HOST=mongodb-demo
      - MONGODB_PORT=27017
      - REDIS_HOST=demo-redis
      - REDIS_PORT=6379
    depends_on:
      - mongodb-demo
      - demo-redis
    networks:
      - autoops-demo-net
    labels:
      com.docker.compose.project: autoops-demo
      com.docker.compose.service: demo-app
      autoops.health.type: http
      autoops.health.url: http://localhost:5000/health

  mongodb-demo:
    image: mongo:7.0
    container_name: mongodb-demo
    networks:
      - autoops-demo-net
    volumes:
      - mongodb-demo-data:/data/db
    labels:
      com.docker.compose.project: autoops-demo
      com.docker.compose.service: mongodb-demo
      autoops.health.type: command
      autoops.health.command: "mongosh --eval 'db.runCommand({ping:1})' --quiet"

  demo-redis:
    image: redis:7-alpine
    container_name: demo-redis
    networks:
      - autoops-demo-net
    labels:
      com.docker.compose.project: autoops-demo
      com.docker.compose.service: demo-redis
      autoops.health.type: command
      autoops.health.command: "redis-cli ping"

volumes:
  mongodb-demo-data:
```

All 4 containers must have the `com.docker.compose.project: autoops-demo` label — this is what the `DockerComposeProvider` uses to discover services.

**infra/docker-compose/nginx.conf:**
```nginx
upstream demo_app {
    server demo-app:5000;
}

server {
    listen 80;

    location /health {
        proxy_pass http://demo_app/health;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://demo_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI

# Start the demo stack
docker compose -f infra/docker-compose/docker-compose.target.yml up -d --build

# Wait for startup
sleep 10

# Health check the demo app
curl -s http://localhost:5000/health | python3 -m json.tool
# Expected: {"status": "ok", "mongodb": true, "redis": true, "timestamp": "..."}

# Test data endpoint
curl -s http://localhost:5000/data | python3 -m json.tool
# Expected: {"source": "mongodb", "count": 0, "data": []}

# Test cache endpoint
curl -s http://localhost:5000/cache | python3 -m json.tool
# Expected: {"source": "redis", "value": "...", "cache_hit": false}

# Test via Nginx
curl -s http://localhost:8080/health | python3 -m json.tool
# Expected: same as direct app health

# Verify all 4 containers are running
docker ps --filter "label=com.docker.compose.project=autoops-demo" --format "table {{.Names}}\t{{.Status}}"
# Expected: 4 rows all showing "Up"

# Tear down
docker compose -f infra/docker-compose/docker-compose.target.yml down
```

## Dependencies

- Step 01 (project setup, directory skeleton exists)
- Step 04 (Docker Compose provider exists — not required to run, but ensures consistent container naming for steps 06 and beyond)
