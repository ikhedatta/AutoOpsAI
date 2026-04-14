#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  AutoOpsAI HTTPS Setup Script
#  Configures Grafana + Prometheus for sub-path routing,
#  then starts the Nginx HTTPS reverse proxy.
#
#  After running this, all services are accessible via:
#    https://10.41.31.20/            → AutoOps AI
#    https://10.41.31.20/grafana/    → Grafana
#    https://10.41.31.20/prometheus/ → Prometheus
#    https://10.41.31.20/loki/       → Loki (API only)
# ─────────────────────────────────────────────────────────────
set -e

IP_ADDR="10.41.31.20"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "  AutoOpsAI HTTPS Setup"
echo "============================================"

# ── Step 1: Generate SSL cert if missing ──
if [ ! -f "$PROJECT_DIR/infra/ssl/selfsigned.crt" ]; then
    echo "[1/4] Generating self-signed SSL certificate..."
    bash "$PROJECT_DIR/infra/ssl/generate-cert.sh"
else
    echo "[1/4] SSL certificate already exists. Skipping."
fi

# ── Step 2: Reconfigure Grafana for sub-path /grafana/ ──
echo "[2/4] Reconfiguring Grafana for sub-path /grafana/ ..."

# Get current Grafana container details for volume mounts
GRAFANA_ID=$(docker ps -q --filter "ancestor=grafana/grafana:latest" 2>/dev/null || true)
if [ -z "$GRAFANA_ID" ]; then
    GRAFANA_ID=$(docker ps -q --filter "name=grafana" 2>/dev/null || true)
fi

if [ -n "$GRAFANA_ID" ]; then
    # Capture existing volume mounts
    GRAFANA_VOLUMES=$(docker inspect "$GRAFANA_ID" --format '{{range .Mounts}}-v {{.Source}}:{{.Destination}} {{end}}' 2>/dev/null || true)

    echo "  Stopping existing Grafana container..."
    docker stop "$GRAFANA_ID" >/dev/null 2>&1 || true
    docker rm "$GRAFANA_ID" >/dev/null 2>&1 || true

    echo "  Starting Grafana with sub-path support..."
    docker run -d \
        --name grafana \
        --restart unless-stopped \
        -p 3000:3000 \
        -e GF_SECURITY_ADMIN_USER=admin \
        -e GF_SECURITY_ADMIN_PASSWORD=autoops@123 \
        -e GF_USERS_ALLOW_SIGN_UP=false \
        -e GF_UNIFIED_ALERTING_ENABLED=true \
        -e GF_SERVER_ROOT_URL="https://${IP_ADDR}/grafana/" \
        -e GF_SERVER_SERVE_FROM_SUB_PATH=true \
        $GRAFANA_VOLUMES \
        grafana/grafana:latest
    echo "  Grafana reconfigured ✓"
else
    echo "  WARNING: Grafana container not found. Please start it with:"
    echo "    docker run -d --name grafana -p 3000:3000 \\"
    echo "      -e GF_SERVER_ROOT_URL=https://${IP_ADDR}/grafana/ \\"
    echo "      -e GF_SERVER_SERVE_FROM_SUB_PATH=true \\"
    echo "      grafana/grafana:latest"
fi

# ── Step 3: Reconfigure Prometheus for sub-path /prometheus/ ──
echo "[3/4] Reconfiguring Prometheus for sub-path /prometheus/ ..."

PROMETHEUS_ID=$(docker ps -q --filter "ancestor=prom/prometheus:latest" 2>/dev/null || true)
if [ -z "$PROMETHEUS_ID" ]; then
    PROMETHEUS_ID=$(docker ps -q --filter "name=prometheus" 2>/dev/null || true)
fi

if [ -n "$PROMETHEUS_ID" ]; then
    # Capture existing volume mounts
    PROM_VOLUMES=$(docker inspect "$PROMETHEUS_ID" --format '{{range .Mounts}}-v {{.Source}}:{{.Destination}} {{end}}' 2>/dev/null || true)

    echo "  Stopping existing Prometheus container..."
    docker stop "$PROMETHEUS_ID" >/dev/null 2>&1 || true
    docker rm "$PROMETHEUS_ID" >/dev/null 2>&1 || true

    echo "  Starting Prometheus with sub-path support..."
    docker run -d \
        --name prometheus \
        --restart unless-stopped \
        -p 9090:9090 \
        $PROM_VOLUMES \
        prom/prometheus:latest \
        --config.file=/etc/prometheus/prometheus.yml \
        --storage.tsdb.path=/prometheus \
        --storage.tsdb.retention.time=30d \
        --web.enable-lifecycle \
        --web.external-url="https://${IP_ADDR}/prometheus/"
    echo "  Prometheus reconfigured ✓"
else
    echo "  WARNING: Prometheus container not found. Please start it with:"
    echo "    docker run -d --name prometheus -p 9090:9090 \\"
    echo "      prom/prometheus:latest \\"
    echo "      --web.external-url=https://${IP_ADDR}/prometheus/"
fi

# ── Step 4: Start/Restart the HTTPS reverse proxy ──
echo "[4/4] Starting HTTPS reverse proxy..."
cd "$PROJECT_DIR"
docker compose -f docker-compose.https.yml down 2>/dev/null || true
docker compose -f docker-compose.https.yml up -d

echo ""
echo "============================================"
echo "  HTTPS Setup Complete!"
echo "============================================"
echo ""
echo "Endpoints:"
echo "  https://${IP_ADDR}/             → AutoOps AI (frontend + API)"
echo "  https://${IP_ADDR}/grafana/     → Grafana"
echo "  https://${IP_ADDR}/prometheus/  → Prometheus"
echo "  https://${IP_ADDR}/loki/        → Loki (API)"
echo ""
echo "NOTE: Since this uses a self-signed certificate,"
echo "browsers will show a security warning. Click"
echo "'Advanced' → 'Proceed' to continue."
echo ""
echo "To verify: curl -k https://${IP_ADDR}/"
