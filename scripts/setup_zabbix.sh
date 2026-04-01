#!/bin/bash
# Setup Zabbix 7.0 for SRE Agent integration
# Configures host, media type (webhook), and trigger action via JSON-RPC API.
#
# Usage: bash scripts/setup_zabbix.sh
#
# Prerequisites:
#   - Zabbix stack running (docker compose up)
#   - Zabbix web available at ZABBIX_URL (default: http://localhost:8080)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ZABBIX_URL="${ZABBIX_URL:-http://localhost:8080}"
ZABBIX_API="${ZABBIX_URL}/api_jsonrpc.php"
ZABBIX_USER="${ZABBIX_USER:-Admin}"
ZABBIX_PASSWORD="${ZABBIX_PASSWORD:-zabbix}"
SRE_WEBHOOK_URL="${SRE_WEBHOOK_URL:-http://sre-agent:8002/webhooks/zabbix}"

HOST_GROUP_NAME="SRE Monitored"
HOST_NAME="playground"
HOST_DNS="zabbix-agent"
HOST_PORT="10050"
MEDIA_TYPE_NAME="SRE Agent Webhook"
ACTION_NAME="Send to SRE Agent"

# Severity threshold for trigger action (4 = High)
MIN_SEVERITY=2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[ZABBIX-SETUP]${NC} $1"; }
warn() { echo -e "${YELLOW}[ZABBIX-SETUP]${NC} $1"; }
err()  { echo -e "${RED}[ZABBIX-SETUP]${NC} $1"; }

# JSON-RPC call helper.
# Usage: zabbix_call <method> <params_json> [auth_token]
#   - When auth_token is provided, sends Authorization: Bearer header (Zabbix 7.0+).
#   - Returns raw JSON response.
zabbix_call() {
    local method="$1"
    local params="$2"
    local token="${3:-}"

    local payload
    payload=$(cat <<ENDJSON
{
    "jsonrpc": "2.0",
    "method": "${method}",
    "params": ${params},
    "id": 1
}
ENDJSON
)

    local response
    if [[ -n "$token" ]]; then
        response=$(curl -s -X POST "${ZABBIX_API}" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${token}" \
            -d "${payload}")
    else
        response=$(curl -s -X POST "${ZABBIX_API}" \
            -H "Content-Type: application/json" \
            -d "${payload}")
    fi

    # Check for JSON-RPC error
    local rpc_error
    rpc_error=$(echo "$response" | python3 -c "
import sys, json
r = json.load(sys.stdin)
if 'error' in r:
    print(json.dumps(r['error']))
" 2>/dev/null || true)

    if [[ -n "$rpc_error" ]]; then
        err "API error calling ${method}: ${rpc_error}"
        return 1
    fi

    echo "$response"
}

# Extract .result from JSON-RPC response using python3 (available everywhere).
jq_result() {
    python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin).get('result', '')))"
}

# ---------------------------------------------------------------------------
# Step 0: Wait for Zabbix API to become available
# ---------------------------------------------------------------------------
log "Waiting for Zabbix API at ${ZABBIX_API} ..."

MAX_WAIT=120
WAITED=0
while true; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${ZABBIX_API}" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}' 2>/dev/null || true)

    if [[ "$HTTP_CODE" == "200" ]]; then
        break
    fi

    if (( WAITED >= MAX_WAIT )); then
        err "Zabbix API not available after ${MAX_WAIT}s. Aborting."
        exit 1
    fi

    sleep 2
    WAITED=$((WAITED + 2))
done

API_VERSION=$(curl -s -X POST "${ZABBIX_API}" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('result','unknown'))")

log "Zabbix API ready (version ${API_VERSION})"

# ---------------------------------------------------------------------------
# Step 1: Authenticate
# ---------------------------------------------------------------------------
log "Step 1: Authenticating as '${ZABBIX_USER}' ..."

AUTH_RESPONSE=$(zabbix_call "user.login" "{\"username\":\"${ZABBIX_USER}\",\"password\":\"${ZABBIX_PASSWORD}\"}")
AUTH_TOKEN=$(echo "$AUTH_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['result'])")

if [[ -z "$AUTH_TOKEN" || "$AUTH_TOKEN" == "None" ]]; then
    err "Authentication failed."
    exit 1
fi

log "Authenticated successfully (token: ${AUTH_TOKEN:0:8}...)"

# ---------------------------------------------------------------------------
# Step 2: Create Host Group "SRE Monitored" (idempotent)
# ---------------------------------------------------------------------------
log "Step 2: Ensuring host group '${HOST_GROUP_NAME}' exists ..."

EXISTING_GROUP=$(zabbix_call "hostgroup.get" \
    "{\"filter\":{\"name\":[\"${HOST_GROUP_NAME}\"]}}" "$AUTH_TOKEN" \
    | jq_result)

GROUP_ID=$(echo "$EXISTING_GROUP" | python3 -c "
import sys, json
groups = json.load(sys.stdin)
if isinstance(groups, list) and len(groups) > 0:
    print(groups[0]['groupid'])
else:
    print('')
" 2>/dev/null || true)

if [[ -n "$GROUP_ID" ]]; then
    log "Host group '${HOST_GROUP_NAME}' already exists (id=${GROUP_ID})"
else
    CREATE_GROUP=$(zabbix_call "hostgroup.create" \
        "{\"name\":\"${HOST_GROUP_NAME}\"}" "$AUTH_TOKEN" \
        | jq_result)
    GROUP_ID=$(echo "$CREATE_GROUP" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r['groupids'][0])
")
    log "Created host group '${HOST_GROUP_NAME}' (id=${GROUP_ID})"
fi

# ---------------------------------------------------------------------------
# Step 3: Find template "Linux by Zabbix agent"
# ---------------------------------------------------------------------------
log "Step 3: Searching for Linux monitoring template ..."

# Try both common template names
TEMPLATE_ID=""
for TMPL_NAME in "Linux by Zabbix agent" "Linux by Zabbix agent active"; do
    TMPL_RESULT=$(zabbix_call "template.get" \
        "{\"filter\":{\"host\":[\"${TMPL_NAME}\"]}}" "$AUTH_TOKEN" \
        | jq_result)

    TEMPLATE_ID=$(echo "$TMPL_RESULT" | python3 -c "
import sys, json
t = json.load(sys.stdin)
if isinstance(t, list) and len(t) > 0:
    print(t[0]['templateid'])
else:
    print('')
" 2>/dev/null || true)

    if [[ -n "$TEMPLATE_ID" ]]; then
        log "Found template '${TMPL_NAME}' (id=${TEMPLATE_ID})"
        break
    fi
done

if [[ -z "$TEMPLATE_ID" ]]; then
    # Fallback: search by partial name
    warn "Exact template not found. Searching by partial name 'Linux' ..."
    TMPL_RESULT=$(zabbix_call "template.get" \
        "{\"search\":{\"host\":\"Linux\"},\"limit\":5}" "$AUTH_TOKEN" \
        | jq_result)

    TEMPLATE_INFO=$(echo "$TMPL_RESULT" | python3 -c "
import sys, json
templates = json.load(sys.stdin)
if isinstance(templates, list) and len(templates) > 0:
    print(templates[0]['templateid'] + '|' + templates[0]['host'])
else:
    print('')
")

    if [[ -n "$TEMPLATE_INFO" ]]; then
        TEMPLATE_ID="${TEMPLATE_INFO%%|*}"
        FOUND_NAME="${TEMPLATE_INFO##*|}"
        log "Using template '${FOUND_NAME}' (id=${TEMPLATE_ID})"
    else
        warn "No Linux template found. Host will be created without a template."
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Create Host "playground" (idempotent)
# ---------------------------------------------------------------------------
log "Step 4: Ensuring host '${HOST_NAME}' exists ..."

EXISTING_HOST=$(zabbix_call "host.get" \
    "{\"filter\":{\"host\":[\"${HOST_NAME}\"]}}" "$AUTH_TOKEN" \
    | jq_result)

HOST_ID=$(echo "$EXISTING_HOST" | python3 -c "
import sys, json
hosts = json.load(sys.stdin)
if isinstance(hosts, list) and len(hosts) > 0:
    print(hosts[0]['hostid'])
else:
    print('')
" 2>/dev/null || true)

if [[ -n "$HOST_ID" ]]; then
    log "Host '${HOST_NAME}' already exists (id=${HOST_ID})"
else
    # Build template array
    TEMPLATES_PARAM="[]"
    if [[ -n "$TEMPLATE_ID" ]]; then
        TEMPLATES_PARAM="[{\"templateid\":\"${TEMPLATE_ID}\"}]"
    fi

    CREATE_HOST=$(zabbix_call "host.create" "{
        \"host\": \"${HOST_NAME}\",
        \"groups\": [{\"groupid\": \"${GROUP_ID}\"}],
        \"interfaces\": [{
            \"type\": 1,
            \"main\": 1,
            \"useip\": 0,
            \"dns\": \"${HOST_DNS}\",
            \"ip\": \"\",
            \"port\": \"${HOST_PORT}\"
        }],
        \"templates\": ${TEMPLATES_PARAM}
    }" "$AUTH_TOKEN" | jq_result)

    HOST_ID=$(echo "$CREATE_HOST" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r['hostids'][0])
")
    log "Created host '${HOST_NAME}' (id=${HOST_ID})"
fi

# ---------------------------------------------------------------------------
# Step 5: Create Webhook Media Type (idempotent)
# ---------------------------------------------------------------------------
log "Step 5: Ensuring media type '${MEDIA_TYPE_NAME}' exists ..."

EXISTING_MT=$(zabbix_call "mediatype.get" \
    "{\"filter\":{\"name\":[\"${MEDIA_TYPE_NAME}\"]}}" "$AUTH_TOKEN" \
    | jq_result)

MEDIA_TYPE_ID=$(echo "$EXISTING_MT" | python3 -c "
import sys, json
mt = json.load(sys.stdin)
if isinstance(mt, list) and len(mt) > 0:
    print(mt[0]['mediatypeid'])
else:
    print('')
" 2>/dev/null || true)

# Webhook JavaScript — Zabbix built-in HttpRequest
WEBHOOK_SCRIPT='var params = JSON.parse(value);
var req = new HttpRequest();
req.addHeader('\''Content-Type: application/json'\'');
var payload = JSON.stringify({
    alert_id: params.alert_id,
    host: params.host,
    trigger: params.trigger,
    severity: params.severity,
    timestamp: params.timestamp,
    description: params.description
});
var resp = req.post(params.webhook_url, payload);
return '\''OK: '\'' + resp;'

if [[ -n "$MEDIA_TYPE_ID" ]]; then
    log "Media type '${MEDIA_TYPE_NAME}' already exists (id=${MEDIA_TYPE_ID})"
else
    # Escape the script for JSON embedding
    SCRIPT_JSON=$(python3 -c "
import json, sys
script = '''$WEBHOOK_SCRIPT'''
print(json.dumps(script))
")

    CREATE_MT=$(zabbix_call "mediatype.create" "{
        \"name\": \"${MEDIA_TYPE_NAME}\",
        \"type\": 4,
        \"status\": 0,
        \"script\": ${SCRIPT_JSON},
        \"parameters\": [
            {\"name\": \"alert_id\",    \"value\": \"{EVENT.ID}\"},
            {\"name\": \"host\",        \"value\": \"{HOST.NAME}\"},
            {\"name\": \"trigger\",     \"value\": \"{TRIGGER.NAME}\"},
            {\"name\": \"severity\",    \"value\": \"{TRIGGER.SEVERITY}\"},
            {\"name\": \"timestamp\",   \"value\": \"{EVENT.DATE} {EVENT.TIME}\"},
            {\"name\": \"description\", \"value\": \"{TRIGGER.DESCRIPTION}\"},
            {\"name\": \"webhook_url\", \"value\": \"${SRE_WEBHOOK_URL}\"}
        ]
    }" "$AUTH_TOKEN" | jq_result)

    MEDIA_TYPE_ID=$(echo "$CREATE_MT" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r['mediatypeids'][0])
")
    log "Created media type '${MEDIA_TYPE_NAME}' (id=${MEDIA_TYPE_ID})"
fi

# ---------------------------------------------------------------------------
# Step 6: Assign media to Admin user (idempotent)
# ---------------------------------------------------------------------------
log "Step 6: Assigning webhook media to '${ZABBIX_USER}' user ..."

# Get Admin user ID
ADMIN_RESULT=$(zabbix_call "user.get" \
    "{\"filter\":{\"username\":[\"${ZABBIX_USER}\"]},\"selectMedias\":\"extend\"}" "$AUTH_TOKEN" \
    | jq_result)

ADMIN_INFO=$(echo "$ADMIN_RESULT" | python3 -c "
import sys, json
users = json.load(sys.stdin)
if isinstance(users, list) and len(users) > 0:
    u = users[0]
    userid = u['userid']
    # Check if media already assigned
    medias = u.get('medias', [])
    already = any(str(m.get('mediatypeid')) == '$MEDIA_TYPE_ID' for m in medias)
    print(f'{userid}|{\"yes\" if already else \"no\"}')
else:
    print('')
")

ADMIN_ID="${ADMIN_INFO%%|*}"
MEDIA_EXISTS="${ADMIN_INFO##*|}"

if [[ "$MEDIA_EXISTS" == "yes" ]]; then
    log "Media already assigned to '${ZABBIX_USER}'"
else
    # Collect existing medias to preserve them
    EXISTING_MEDIAS=$(echo "$ADMIN_RESULT" | python3 -c "
import sys, json
users = json.load(sys.stdin)
medias = users[0].get('medias', [])
result = []
for m in medias:
    result.append({
        'mediatypeid': m['mediatypeid'],
        'sendto': m.get('sendto', ''),
        'active': int(m.get('active', 0)),
        'severity': int(m.get('severity', 63)),
        'period': m.get('period', '1-7,00:00-24:00')
    })
# Add new webhook media
result.append({
    'mediatypeid': '$MEDIA_TYPE_ID',
    'sendto': 'sre-agent',
    'active': 0,
    'severity': 63,
    'period': '1-7,00:00-24:00'
})
print(json.dumps(result))
")

    zabbix_call "user.update" "{
        \"userid\": \"${ADMIN_ID}\",
        \"medias\": ${EXISTING_MEDIAS}
    }" "$AUTH_TOKEN" > /dev/null

    log "Assigned webhook media to '${ZABBIX_USER}' (userid=${ADMIN_ID})"
fi

# ---------------------------------------------------------------------------
# Step 7: Create Trigger Action (idempotent)
# ---------------------------------------------------------------------------
log "Step 7: Ensuring action '${ACTION_NAME}' exists ..."

EXISTING_ACTION=$(zabbix_call "action.get" \
    "{\"filter\":{\"name\":[\"${ACTION_NAME}\"]},\"selectOperations\":\"extend\"}" "$AUTH_TOKEN" \
    | jq_result)

ACTION_ID=$(echo "$EXISTING_ACTION" | python3 -c "
import sys, json
actions = json.load(sys.stdin)
if isinstance(actions, list) and len(actions) > 0:
    print(actions[0]['actionid'])
else:
    print('')
" 2>/dev/null || true)

if [[ -n "$ACTION_ID" ]]; then
    log "Action '${ACTION_NAME}' already exists (id=${ACTION_ID})"
else
    CREATE_ACTION=$(zabbix_call "action.create" "{
        \"name\": \"${ACTION_NAME}\",
        \"eventsource\": 0,
        \"status\": 0,
        \"esc_period\": \"60s\",
        \"filter\": {
            \"evaltype\": 0,
            \"conditions\": [
                {
                    \"conditiontype\": 4,
                    \"operator\": 5,
                    \"value\": \"${MIN_SEVERITY}\"
                }
            ]
        },
        \"operations\": [
            {
                \"operationtype\": 0,
                \"esc_period\": \"0s\",
                \"esc_step_from\": 1,
                \"esc_step_to\": 1,
                \"opmessage\": {
                    \"mediatypeid\": \"${MEDIA_TYPE_ID}\",
                    \"default_msg\": 1
                },
                \"opmessage_usr\": [
                    {\"userid\": \"${ADMIN_ID}\"}
                ]
            }
        ]
    }" "$AUTH_TOKEN" | jq_result)

    ACTION_ID=$(echo "$CREATE_ACTION" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(r['actionids'][0])
")
    log "Created action '${ACTION_NAME}' (id=${ACTION_ID})"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
log "========================================="
log "  Zabbix setup complete!"
log "========================================="
log "  Host Group : ${HOST_GROUP_NAME} (id=${GROUP_ID})"
log "  Host       : ${HOST_NAME} (id=${HOST_ID})"
log "  Media Type : ${MEDIA_TYPE_NAME} (id=${MEDIA_TYPE_ID})"
log "  Action     : ${ACTION_NAME} (id=${ACTION_ID})"
log "  Webhook URL: ${SRE_WEBHOOK_URL}"
log "========================================="
