#!/bin/bash
# bin/preflight.sh — Health-check all Docker services after docker compose up -d
#
# Verifies that PostgreSQL, Qdrant, Neo4j, Mem0 MCP, Graphiti MCP, Cognee MCP,
# and the shared file server are all reachable and responding correctly.
#
# Usage:
#   bash bin/preflight.sh              # check localhost
#   bash bin/preflight.sh 192.168.1.X  # check a remote host

HOST="${1:-localhost}"
PASS=0
FAIL=0

check() {
  local name="$1"
  local cmd="$2"
  if eval "$cmd" &>/dev/null; then
    echo "  [OK]  $name"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL+1))
  fi
}

echo "=== Pre-flight checks (host: $HOST) ==="
echo ""

check "PostgreSQL (healthy)"  "docker compose ps postgres | grep -q healthy"
check "Qdrant"                "curl -sf http://${HOST}:6333/healthz"
check "Neo4j HTTP"            "curl -sf http://${HOST}:7474"
check "Mem0 MCP"              "curl -sf http://${HOST}:8181/docs"
check "Graphiti MCP"          "curl -sf http://${HOST}:8050/ || curl -sf http://${HOST}:8050/health"
check "Cognee MCP"            "curl -sf http://${HOST}:8000/ || curl -sf http://${HOST}:8000/health"
check "File server"           "curl -sf http://${HOST}:9000/test-cases/test_cases.csv | head -1 | grep -q 'id'"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ $FAIL -eq 0 ]; then
  echo "All systems go!"
else
  echo "Fix failures before hackathon starts"
  exit 1
fi
