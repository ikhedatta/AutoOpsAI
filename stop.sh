#!/usr/bin/env bash
# =============================================================================
# AutoOps AI — Stop Application
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".autoops.pid"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}⚙️  AutoOps AI — Stopping${NC}"
echo "==========================================="

if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}No PID file found. Checking for running processes...${NC}"
    # Try to find uvicorn running our app
    PIDS=$(pgrep -f "uvicorn agent.main:app" 2>/dev/null || true)
    if [ -z "$PIDS" ]; then
        echo "No AutoOps AI processes found."
        exit 0
    fi
    echo "Found orphaned process(es): $PIDS"
    kill $PIDS 2>/dev/null || true
    echo -e "${GREEN}✓ Stopped${NC}"
    exit 0
fi

PID=$(cat "$PID_FILE")
echo "Stopping server (PID $PID)..."

if kill -0 "$PID" 2>/dev/null; then
    # Graceful shutdown first
    kill "$PID" 2>/dev/null
    
    # Wait up to 10 seconds for graceful exit
    for i in $(seq 1 10); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done
    
    # Force kill if still running
    if kill -0 "$PID" 2>/dev/null; then
        echo "Graceful shutdown timed out, force killing..."
        kill -9 "$PID" 2>/dev/null || true
    fi
    
    echo -e "${GREEN}✓ AutoOps AI stopped${NC}"
else
    echo -e "${YELLOW}Process $PID is not running (already stopped)${NC}"
fi

rm -f "$PID_FILE"
echo "==========================================="
