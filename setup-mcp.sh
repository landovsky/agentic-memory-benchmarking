#!/bin/bash
# setup-mcp.sh — run this on a participant machine to configure MCP servers
# Usage: ./setup-mcp.sh 192.168.1.100
set -e

HOST_IP="${1:-}"
if [ -z "$HOST_IP" ]; then
  # Try to read from .env
  if [ -f .env ]; then
    HOST_IP=$(grep '^HOST_IP=' .env | cut -d= -f2)
  fi
fi
if [ -z "$HOST_IP" ]; then
  read -p "Enter host machine IP: " HOST_IP
fi

echo "Configuring MCP servers for host: $HOST_IP"

# Add MCP servers via claude CLI
claude mcp add --transport sse mem0 "http://${HOST_IP}:8181/sse" && echo "✓ mem0 configured" || echo "✗ mem0 failed (is claude CLI installed?)"
claude mcp add --transport sse graphiti "http://${HOST_IP}:8050/sse" && echo "✓ graphiti configured" || echo "✗ graphiti failed"
claude mcp add --transport sse cognee "http://${HOST_IP}:8000/mcp/sse" && echo "✓ cognee configured" || echo "✗ cognee failed"

echo ""
echo "Done! Test with: curl http://${HOST_IP}:8181/health"
echo "Verify MCPs: claude mcp list"
