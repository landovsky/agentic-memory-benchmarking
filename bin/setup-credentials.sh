#!/usr/bin/env bash
# bin/setup-credentials.sh — Write GCP service account credentials to disk
#
# Reads GOOGLE_APPLICATION_CREDENTIALS_JSON (a JSON string) from .env and
# writes it to credentials/gcp-sa.json so Docker containers can mount it.
# Required before starting the LiteLLM proxy container.
#
# Usage:
#   bash bin/setup-credentials.sh          # reads .env from current directory
#
# Prerequisites:
#   .env must contain: GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account",...}'
set -euo pipefail

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

if [ -z "${GOOGLE_APPLICATION_CREDENTIALS_JSON:-}" ]; then
  echo "ERROR: GOOGLE_APPLICATION_CREDENTIALS_JSON is not set in .env"
  exit 1
fi

mkdir -p credentials
echo "$GOOGLE_APPLICATION_CREDENTIALS_JSON" > credentials/gcp-sa.json
chmod 600 credentials/gcp-sa.json
echo "credentials/gcp-sa.json written successfully"
