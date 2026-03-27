#!/usr/bin/env bash
# bin/setup-mcp.sh — Configure Graphiti (+ optionally Mem0/Cognee) MCP servers in Claude Code
#
# Usage:
#   bash bin/setup-mcp.sh [OPTIONS] [HOST_IP]
#
# Options:
#   --all             Also add mem0 and cognee (off by default)
#   --mem0            Also add mem0
#   --cognee          Also add cognee
#   --scope <scope>   Where to install: project (default) | user
#   --remove          Remove configured MCP servers instead of adding them
#   -h, --help        Show this help

set -euo pipefail

# ── defaults ────────────────────────────────────────────────────────────────
HOST_IP=""
ADD_MEM0=false
ADD_COGNEE=false
SCOPE="project"    # project = .claude.json, user = ~/.claude.json
REMOVE=false

# ── parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)    ADD_MEM0=true; ADD_COGNEE=true; shift ;;
    --mem0)   ADD_MEM0=true; shift ;;
    --cognee) ADD_COGNEE=true; shift ;;
    --scope)
      SCOPE="${2:-}"
      if [[ "$SCOPE" != "project" && "$SCOPE" != "user" ]]; then
        echo "ERROR: --scope must be 'project' or 'user'" >&2; exit 1
      fi
      shift 2
      ;;
    --remove) REMOVE=true; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2; exit 1
      ;;
    *)
      HOST_IP="$1"; shift
      ;;
  esac
done

# ── resolve HOST_IP ──────────────────────────────────────────────────────────
if [[ -z "$HOST_IP" ]]; then
  # Try .env in script's parent directory (repo root)
  REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  if [[ -f "$REPO_ROOT/.env" ]]; then
    HOST_IP=$(grep '^HOST_IP=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2 || true)
  fi
fi
if [[ -z "$HOST_IP" ]]; then
  read -rp "Enter host machine IP (or 'localhost'): " HOST_IP
fi

# ── build scope flag ─────────────────────────────────────────────────────────
SCOPE_FLAG=""
if [[ "$SCOPE" == "user" ]]; then
  SCOPE_FLAG="--global"
fi

# ── helpers ──────────────────────────────────────────────────────────────────
mcp_add() {
  local name="$1" url="$2"
  # shellcheck disable=SC2086
  if claude mcp add --transport http $SCOPE_FLAG "$name" "$url" 2>&1; then
    echo "  [OK]  $name added ($url)"
  else
    echo "  [WARN] $name: add failed (already exists? run with --remove first)"
  fi
}

mcp_remove() {
  local name="$1"
  # shellcheck disable=SC2086
  if claude mcp remove $SCOPE_FLAG "$name" 2>&1; then
    echo "  [OK]  $name removed"
  else
    echo "  [WARN] $name: not found (already removed?)"
  fi
}

# ── main ─────────────────────────────────────────────────────────────────────
echo "Host: $HOST_IP  |  Scope: $SCOPE  |  Action: $( [[ "$REMOVE" == true ]] && echo remove || echo add )"
echo ""

if [[ "$REMOVE" == true ]]; then
  mcp_remove "graphiti"
  $ADD_MEM0   && mcp_remove "mem0"
  $ADD_COGNEE && mcp_remove "cognee"
else
  mcp_add "graphiti" "http://${HOST_IP}:8050/mcp"
  $ADD_MEM0   && mcp_add "mem0"   "http://${HOST_IP}:8181/mcp"
  $ADD_COGNEE && mcp_add "cognee" "http://${HOST_IP}:8000/mcp"
fi

echo ""
echo "Done. Verify with: claude mcp list"
