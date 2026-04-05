#!/usr/bin/env bash
# =============================================================================
# AutoOps AI — Start Application
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${AUTOOPS_PORT:-8000}"
HOST="${AUTOOPS_HOST:-127.0.0.1}"
PID_FILE=".autoops.pid"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}⚙️  AutoOps AI — Starting${NC}"
echo "==========================================="

# --- Check if already running ---
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo -e "${YELLOW}⚠ AutoOps AI is already running (PID $OLD_PID)${NC}"
        echo "   Dashboard: http://$HOST:$PORT"
        echo "   Run ./stop.sh to stop it first."
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# --- Check prerequisites ---
echo -n "Checking MongoDB...     "
if command -v mongosh &>/dev/null; then
    if mongosh --quiet --eval "db.runCommand({ping:1})" mongodb://localhost:27017 &>/dev/null; then
        echo -e "${GREEN}✓ running${NC}"
    else
        echo -e "${RED}✗ not reachable at localhost:27017${NC}"
        echo "  Start MongoDB before running AutoOps AI."
        exit 1
    fi
else
    # Try connecting with python
    if uv run python -c "import pymongo; pymongo.MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=2000).server_info()" &>/dev/null; then
        echo -e "${GREEN}✓ running${NC}"
    else
        echo -e "${RED}✗ not reachable at localhost:27017${NC}"
        echo "  Start MongoDB before running AutoOps AI."
        exit 1
    fi
fi

echo -n "Checking Ollama...      "
if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo -e "${GREEN}✓ running${NC}"
else
    echo -e "${YELLOW}⚠ not reachable (LLM features will be unavailable)${NC}"
fi

echo -n "Checking Docker...      "
if docker info &>/dev/null 2>&1; then
    echo -e "${GREEN}✓ running${NC}"
else
    echo -e "${YELLOW}⚠ not running (provider will operate in degraded mode)${NC}"
fi

# --- Install dependencies ---
echo ""
echo "Installing Python dependencies..."
uv sync --quiet 2>/dev/null || uv sync

# --- Build frontend ---
echo ""
echo "Building frontend..."
if [ -f "frontend/package.json" ]; then
    pushd frontend > /dev/null
    if [ ! -d "node_modules" ]; then
        echo "  Installing npm dependencies..."
        npm install --silent 2>/dev/null || echo -e "${YELLOW}⚠ npm install failed — frontend may be stale${NC}"
    fi
    if npx vite build > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Frontend built${NC}"
    else
        echo -e "  ${YELLOW}⚠ Frontend build failed — serving last build${NC}"
    fi
    popd > /dev/null
else
    echo -e "  ${YELLOW}⚠ No frontend/package.json found — skipping build${NC}"
fi

# --- Start server ---
echo ""
echo -e "${GREEN}Starting AutoOps AI server...${NC}"
nohup uv run uvicorn agent.main:app --host "$HOST" --port "$PORT" > autoops.log 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# Wait for server to be ready
echo -n "Waiting for server"
for i in $(seq 1 60); do
    if curl -sf "http://$HOST:$PORT/api/v1/health" >/dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}==========================================${NC}"
        echo -e "${GREEN}✓ AutoOps AI is running!${NC}"
        echo ""
        echo "   Dashboard:  http://$HOST:$PORT"
        echo "   API:        http://$HOST:$PORT/api/v1"
        echo "   Health:     http://$HOST:$PORT/api/v1/health"
        echo "   WebSocket:  ws://$HOST:$PORT/api/v1/ws/events"
        echo "   PID:        $SERVER_PID"
        echo "   Logs:       tail -f autoops.log"
        echo ""
        echo "   Run ./stop.sh to stop the server."
        echo -e "${GREEN}==========================================${NC}"
        exit 0
    fi
    echo -n "."
    sleep 2
done

echo ""
echo -e "${RED}✗ Server failed to start within 120s${NC}"
echo "  Check logs: cat autoops.log"
kill "$SERVER_PID" 2>/dev/null
rm -f "$PID_FILE"
exit 1
