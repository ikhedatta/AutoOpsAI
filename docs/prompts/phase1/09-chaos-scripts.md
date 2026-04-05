# [Step 09] — Chaos Injection Scripts

## Context

Steps 01-08 are complete. The demo target stack from step 05 is runnable with containers named:
- `autoops-nginx` (service label: `nginx`)
- `autoops-demo-app` (service label: `demo-app`)
- `mongodb-demo` (service label: `mongodb-demo`)
- `demo-redis` (service label: `demo-redis`)

## Objective

Produce six shell scripts that inject specific failure modes into the demo stack for testing the agent's detection and remediation capabilities, plus a restore script.

## Files to Create

- `chaos/docker/kill_mongodb.sh` — Stop the `mongodb-demo` container.
- `chaos/docker/spike_cpu.sh` — Spike CPU in the `autoops-demo-app` container.
- `chaos/docker/fill_redis.sh` — Fill `demo-redis` memory to near capacity.
- `chaos/docker/break_nginx.sh` — Break the Nginx configuration.
- `chaos/docker/oom_demo_app.sh` — Trigger an OOM condition in the demo app container.
- `chaos/docker/restore_all.sh` — Bring the entire demo stack back to a clean running state.

## Files to Modify

None.

## Key Requirements

**All scripts must:**
- Start with `#!/usr/bin/env bash`
- Have `set -e` on the second line (exit on first error)
- Print a descriptive line before each action: `echo "[chaos] Killing mongodb-demo container..."`
- Only reference the demo stack container names listed above — NEVER reference any production MongoDB container
- Be executable (the implementer must run `chmod +x chaos/docker/*.sh`)

**chaos/docker/kill_mongodb.sh:**
```bash
#!/usr/bin/env bash
set -e
echo "[chaos] Stopping mongodb-demo container to simulate database crash..."
docker stop mongodb-demo
echo "[chaos] mongodb-demo stopped. AutoOps should detect this within 15s."
```

**chaos/docker/spike_cpu.sh:**
```bash
#!/usr/bin/env bash
set -e
echo "[chaos] Spiking CPU in autoops-demo-app container..."
# Run stress inside the container for 60 seconds using /dev/urandom as a CPU burner
# Use a background process so the script returns immediately
docker exec -d autoops-demo-app bash -c "cat /dev/urandom | gzip -9 > /dev/null &"
echo "[chaos] CPU spike started in autoops-demo-app. Will auto-clear after ~60s when process is killed."
echo "[chaos] To stop manually: docker exec autoops-demo-app pkill -f gzip"
```

Note: `stress` is often not installed in minimal containers. Using `cat /dev/urandom | gzip -9 > /dev/null` is a dependency-free alternative that creates CPU load.

**chaos/docker/fill_redis.sh:**
```bash
#!/usr/bin/env bash
set -e
echo "[chaos] Setting demo-redis maxmemory to 10mb and flooding with keys..."
# Set a small maxmemory to make it easy to fill
docker exec demo-redis redis-cli CONFIG SET maxmemory 10mb
docker exec demo-redis redis-cli CONFIG SET maxmemory-policy noeviction
echo "[chaos] Writing keys until Redis memory is full..."
# Write in a loop until we hit an OOM error
docker exec demo-redis bash -c '
  for i in $(seq 1 100000); do
    result=$(redis-cli SET "chaos-key-$i" "$(dd if=/dev/urandom bs=100 count=1 2>/dev/null | base64)" 2>&1)
    if echo "$result" | grep -q "OOM"; then
      echo "[chaos] Redis OOM reached at key $i"
      break
    fi
  done
'
echo "[chaos] demo-redis is now at or near memory capacity."
```

**chaos/docker/break_nginx.sh:**
```bash
#!/usr/bin/env bash
set -e
echo "[chaos] Breaking Nginx configuration in autoops-nginx container..."
# Write an invalid config that will cause nginx to return 502/503
docker exec autoops-nginx bash -c "echo 'invalid config syntax ;;;' > /etc/nginx/conf.d/default.conf"
docker exec autoops-nginx nginx -s reload || true
echo "[chaos] Nginx config broken. Demo app should now return errors via proxy."
echo "[chaos] AutoOps should detect HTTP errors within 30s."
```

**chaos/docker/oom_demo_app.sh:**
```bash
#!/usr/bin/env bash
set -e
echo "[chaos] Triggering memory exhaustion in autoops-demo-app container..."
# Allocate memory in a loop using Python
docker exec -d autoops-demo-app python3 -c "
import time
chunks = []
try:
    while True:
        chunks.append(' ' * 10_000_000)  # 10MB per iteration
        time.sleep(0.1)
except MemoryError:
    pass
" || true
echo "[chaos] Memory allocation started in autoops-demo-app."
echo "[chaos] Container may be OOM-killed by Docker. AutoOps should detect this."
```

**chaos/docker/restore_all.sh:**
```bash
#!/usr/bin/env bash
set -e
COMPOSE_FILE="$(dirname "$(realpath "$0")")/../../infra/docker-compose/docker-compose.target.yml"

echo "[restore] Restoring AutoOps demo stack to clean state..."
echo "[restore] Using compose file: $COMPOSE_FILE"

# Stop all demo stack containers (ignore errors if already stopped)
echo "[restore] Stopping all demo stack containers..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans 2>/dev/null || true

# Remove any chaos-injected files/configs by pulling fresh images
echo "[restore] Starting fresh demo stack..."
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate

echo "[restore] Waiting for services to become healthy..."
sleep 10

# Verify health
echo "[restore] Checking health..."
if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
    echo "[restore] Demo app is healthy."
else
    echo "[restore] WARNING: Demo app health check failed. Check docker logs autoops-demo-app"
fi

if docker exec demo-redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[restore] demo-redis is healthy."
else
    echo "[restore] WARNING: demo-redis health check failed."
fi

if docker exec mongodb-demo mongosh --eval 'db.runCommand({ping:1})' --quiet 2>/dev/null | grep -q ok; then
    echo "[restore] mongodb-demo is healthy."
else
    echo "[restore] WARNING: mongodb-demo health check failed."
fi

echo "[restore] Restore complete."
```

**After creating all files**, the implementer must run:
```bash
chmod +x chaos/docker/*.sh
```

## Test Criteria

```bash
cd /Users/dattaikhe/LLM/AutoOpsAI

# First bring up the demo stack
docker compose -f infra/docker-compose/docker-compose.target.yml up -d
sleep 10

# Test kill_mongodb
bash chaos/docker/kill_mongodb.sh
docker ps --filter "name=mongodb-demo" --format "{{.Status}}"
# Expected: shows "Exited" status

# Test restore (brings mongodb back)
bash chaos/docker/restore_all.sh
sleep 10
docker ps --filter "label=com.docker.compose.project=autoops-demo" --format "{{.Names}}\t{{.Status}}"
# Expected: all 4 containers showing "Up"

# Verify all scripts are executable
ls -la chaos/docker/*.sh | awk '{print $1, $9}' | grep -v '^-rwx'
# Expected: empty (all have execute permission)

# Verify no script references production MongoDB
grep -r "MONGODB_URL\|autoops-mongodb\|mongodb:27017" chaos/docker/ || echo "No production MongoDB references found (good)"
```

## Dependencies

- Step 01 (chaos/docker/ directory exists)
- Step 05 (demo target stack defined with exact container names)
