"""Quick test: verify Loki + chat tool-calling work end-to-end."""
import httpx
import json
import time

BASE = "http://127.0.0.1:8000"

# 1. Test Loki via observability API (bypasses LLM)
print("=== Test 1: Loki via observability API ===")
r = httpx.get(
    f"{BASE}/api/v1/observability/loki/query",
    params={"logql": '{container="node-exporter"} |~ "(?i)error"', "limit": "5", "duration_minutes": "60"},
    timeout=30,
)
print(f"  Status: {r.status_code}")
d = r.json()
print(f"  Log count: {d.get('count')}")
for e in d.get("entries", [])[:2]:
    print(f"  > {e['message'][:150]}")

# 2. Test Prometheus via observability API
print("\n=== Test 2: Prometheus via observability API ===")
r = httpx.get(f"{BASE}/api/v1/observability/prometheus/targets", timeout=15)
print(f"  Status: {r.status_code}")
d = r.json()
print(f"  Targets: {len(d.get('targets', []))}")

# 3. Test chat endpoint (should trigger tool calls)
print("\n=== Test 3: Chat with tool calling ===")
start = time.time()
try:
    r = httpx.post(
        f"{BASE}/api/v1/chat",
        json={"question": "Are there any errors in the recent logs?"},
        timeout=300,
    )
    elapsed = time.time() - start
    print(f"  Status: {r.status_code} ({elapsed:.1f}s)")
    d = r.json()
    print(f"  Response:\n  {d.get('response', '')[:1200]}")
except httpx.ReadTimeout:
    elapsed = time.time() - start
    print(f"  TIMEOUT after {elapsed:.1f}s")
except Exception as e:
    elapsed = time.time() - start
    print(f"  ERROR after {elapsed:.1f}s: {e}")
