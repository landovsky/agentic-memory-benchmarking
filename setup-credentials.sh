#!/usr/bin/env bash
set -euo pipefail

# Reads GOOGLE_APPLICATION_CREDENTIALS_JSON from .env and writes it to
# credentials/gcp-sa.json so Docker containers can mount it.

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
