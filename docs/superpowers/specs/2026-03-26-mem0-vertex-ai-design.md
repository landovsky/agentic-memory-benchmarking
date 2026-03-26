# Mem0 — Vertex AI via LiteLLM Proxy

**Date:** 2026-03-26
**Status:** Approved

## Goal

Replace Mem0's Anthropic LLM + OpenAI embedder with Google Vertex AI for both LLM and embeddings, using a single service account JSON credential. No Anthropic or OpenAI API keys required.

## Architecture

```
Mem0 MCP (port 8181)
  ├── LLM calls  → LiteLLM proxy (port 4000) → Vertex AI gemini-2.0-flash-001
  └── Embeddings → Vertex AI text-embedding-004 (direct, via google-cloud-aiplatform)
```

## Vertex AI Configuration

| Parameter | Value |
|-----------|-------|
| Project | `coworking-aggegator` |
| Region | `europe-west3` (Frankfurt) |
| LLM model | `gemini-2.0-flash-001` |
| Embedding model | `text-embedding-004` |

## Components

### 1. Credential File Setup

`GOOGLE_APPLICATION_CREDENTIALS_JSON` (raw JSON string) lives in `.env` and must be written to `./credentials/gcp-sa.json` before starting services. A helper script `setup-credentials.sh` handles this. The `credentials/` directory is gitignored.

### 2. `litellm-config.yaml` (new file)

Configures LiteLLM to expose an OpenAI-compatible API that routes to Vertex AI:

```yaml
model_list:
  - model_name: gemini-flash
    litellm_params:
      model: vertex_ai/gemini-2.0-flash-001
      vertex_project: coworking-aggegator
      vertex_location: europe-west3

litellm_settings:
  drop_params: true
```

Credentials are provided via `GOOGLE_APPLICATION_CREDENTIALS` env var pointing to the mounted file.

### 3. `litellm-proxy` service (new in docker-compose)

- Image: `ghcr.io/berriai/litellm:main-latest`
- Port: `4000`
- Mounts `./litellm-config.yaml` and `./credentials/gcp-sa.json` (read-only)
- Sets `GOOGLE_APPLICATION_CREDENTIALS=/credentials/gcp-sa.json`

### 4. `mem0-mcp` changes

| Env var | Old value | New value |
|---------|-----------|-----------|
| `LLM_PROVIDER` | `anthropic` | `openai` |
| `LLM_MODEL` | `claude-3-5-haiku-20241022` | `gemini-flash` |
| `LLM_API_KEY` | `${ANTHROPIC_API_KEY}` | `dummy` |
| `LLM_BASE_URL` | _(not set)_ | `http://litellm-proxy:4000` |
| `EMBEDDER_PROVIDER` | `openai` | `vertexai` |
| `OPENAI_API_KEY` | `${OPENAI_API_KEY}` | _(removed)_ |
| `GOOGLE_APPLICATION_CREDENTIALS` | _(not set)_ | `/credentials/gcp-sa.json` |

Adds volume mount: `./credentials/gcp-sa.json:/credentials/gcp-sa.json:ro`
Adds `depends_on: litellm-proxy`.

### 5. `.env` additions

```
GOOGLE_APPLICATION_CREDENTIALS_JSON=<service account JSON>
VERTEX_PROJECT_ID=coworking-aggegator
VERTEX_LOCATION=europe-west3
```

## Files Changed

| File | Change |
|------|--------|
| `docker-compose.yml` | Add `litellm-proxy` service; update `mem0-mcp` |
| `litellm-config.yaml` | New file |
| `setup-credentials.sh` | New helper script |
| `.env` / `.env.example` | Add Vertex AI vars, remove OpenAI/Anthropic for Mem0 |
| `.gitignore` | Add `credentials/` |
