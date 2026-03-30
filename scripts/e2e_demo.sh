#!/bin/bash
# E2E Demo: полный цикл SRE-агента
# Stress playground → Zabbix alert (manual) → SRE Agent → SSH diagnostics → LLM → Telegram
#
# Usage: bash scripts/e2e_demo.sh

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[E2E]${NC} $1"; }
warn() { echo -e "${YELLOW}[E2E]${NC} $1"; }
err() { echo -e "${RED}[E2E]${NC} $1"; }

AGENT_URL="http://localhost:8002"
LITELLM_URL="http://localhost:4000"
REGISTRY_URL="http://localhost:8001"
GRAFANA_URL="http://localhost:3000"
LANGFUSE_URL="http://localhost:3001"
PLAYGROUND_URL="http://localhost:8090"

# --- Step 1: Check services ---
log "Step 1: Checking all services..."

check_service() {
    local name=$1
    shift
    if curl -sf "$@" > /dev/null 2>&1; then
        echo "  ✅ $name"
    else
        err "  ❌ $name - not responding"
        return 1
    fi
}

check_service "SRE Agent" "$AGENT_URL/health"
check_service "LiteLLM Gateway" -H "Authorization: Bearer sk-master-changeme" "$LITELLM_URL/health"
check_service "Agent Registry" "$REGISTRY_URL/health"
check_service "Playground" "$PLAYGROUND_URL/health"
check_service "Grafana" "$GRAFANA_URL/api/health"
echo ""

# --- Step 2: Verify agent registered ---
log "Step 2: Verifying A2A agent registration..."
AGENT_CARD=$(curl -sf "$REGISTRY_URL/agents/sre-agent-01" -H "Authorization: Bearer changeme-registry-key" 2>/dev/null || echo "")
if echo "$AGENT_CARD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Agent: {d[\"name\"]} v{d[\"version\"]}')" 2>/dev/null; then
    echo "  ✅ Agent registered in A2A Registry"
else
    warn "  ⚠️  Agent not registered (will register on first request)"
fi
echo ""

# --- Step 3: Send CPU alert ---
log "Step 3: Sending CPU stress alert to SRE Agent..."
RESPONSE=$(curl -sf -X POST "$AGENT_URL/webhooks/zabbix" \
    -H "Content-Type: application/json" \
    -d "{
        \"alert_id\": \"e2e-demo-$(date +%s)\",
        \"host\": \"playground\",
        \"trigger\": \"CPU usage > 90%\",
        \"severity\": \"high\",
        \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
        \"description\": \"CPU utilization exceeded 90% for 5 minutes on playground host\"
    }")

INVESTIGATION_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['investigation_id'])" 2>/dev/null)
STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)

echo "  Status: $STATUS"
echo "  Investigation ID: $INVESTIGATION_ID"
echo ""

# --- Step 4: Wait for investigation ---
log "Step 4: Waiting for investigation to complete..."
for i in $(seq 1 24); do
    sleep 5
    METRICS=$(curl -sf "$AGENT_URL/health" 2>/dev/null || echo '{}')
    COMPLETED=$(echo "$METRICS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('metrics',{}).get('investigations_completed',0))" 2>/dev/null || echo "0")
    ACTIVE=$(echo "$METRICS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('metrics',{}).get('investigations_active',0))" 2>/dev/null || echo "0")
    echo "  [$((i*5))s] completed=$COMPLETED active=$ACTIVE"
    if [ "$ACTIVE" = "0" ] && [ "$COMPLETED" != "0" ]; then
        break
    fi
done

# --- Step 5: Check results ---
echo ""
log "Step 5: Results"
FINAL_METRICS=$(curl -sf "$AGENT_URL/health" 2>/dev/null)
echo "$FINAL_METRICS" | python3 -c "
import sys, json
m = json.load(sys.stdin)['metrics']
print(f'  Investigations total:     {m[\"investigations_total\"]}')
print(f'  Investigations completed: {m[\"investigations_completed\"]}')
print(f'  Investigations failed:    {m[\"investigations_failed\"]}')
"
echo ""

# --- Step 6: Check where to see results ---
log "Step 6: Where to see results"
echo "  📱 Telegram: check your bot chat for the SRE report"
echo "  📊 Grafana:  $GRAFANA_URL (admin/admin) → LLM Gateway Overview"
echo "  🔍 Langfuse: $LANGFUSE_URL (admin@local.dev/admin1234) → Traces"
echo "  📈 Prometheus: $LITELLM_URL/metrics/"
echo ""

log "✅ E2E Demo complete!"
