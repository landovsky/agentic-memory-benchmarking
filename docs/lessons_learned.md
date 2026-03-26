# Lessons Learned — Infrastructure Setup Session (2026-03-26)

## Docker Images — Correct Names

| System | Wrong (from original doc) | Correct |
|--------|--------------------------|---------|
| Mem0 | `mem0ai/mem0:latest` | `mem0/openmemory-mcp` (MCP server, port 8765) |
| Graphiti | `build: ./graphiti-mcp` | `zepai/knowledge-graph-mcp:latest` (port 8000) |
| Cognee | `build: ./cognee-service` | `cognee/cognee-mcp:main` (port 8000) |

Cognee image is **13.5 GB** — pre-pull the night before, not the morning of.

---

## Graphiti MCP — Critical Findings

### 1. config.yaml is ignored at boot
The `zepai/knowledge-graph-mcp:latest` image hardcodes `OpenAIClient()` initialization. Mounting a custom config.yaml for Anthropic/Gemini provider does NOT work — the server crashes before reading it if `OPENAI_API_KEY` is absent.

**Fix:** Set `OPENAI_API_KEY` + `OPENAI_BASE_URL` to route through a proxy:
```yaml
OPENAI_API_KEY: sk-not-needed
OPENAI_BASE_URL: http://litellm-proxy:4000   # or Google AI Studio endpoint
MODEL_NAME: gemini-flash
```

### 2. Graphiti uses FalkorDB by default in the official image
The `zepai/knowledge-graph-mcp:latest` image bundles FalkorDB. To use Neo4j, mount a `config.yaml` with `database.provider: neo4j`. The user's config.yaml at `graphiti-config.yaml` (repo root) does this correctly.

### 3. Vector search uses inline cosine similarity, not a vector index
Graphiti queries Neo4j using `vector.similarity.cosine(n.name_embedding, $search_vector)` directly — NOT via a Neo4j vector index. Creating a vector index is not required. Min score default is **0.6**.

### 4. `search_nodes` / `search_memory_facts` / `get_episodes` returning empty despite data in Neo4j

**Root cause: default `group_id` mismatch (`hackathon` vs `hotdesk`).**

The `graphiti-config.yaml` sets `group_id: ${GRAPHITI_GROUP_ID:hackathon}`. When `GRAPHITI_GROUP_ID` is not set in the docker-compose environment, the MCP server starts with group `hackathon`. All data was loaded under `group_id=hotdesk`. Since the MCP tools default to the configured group when no `group_ids` argument is passed, every search silently searched an empty group.

**Confirmation:** Running `g.search_('Sklik', group_ids=['hackathon'])` → 0 results; `group_ids=['hotdesk']` → 10 results. BM25 and cosine search both work fine at the Neo4j level.

**Secondary issue: parameter name mismatch.** The MCP tool parameter is `group_ids` (a list), not `group_id` (a string). Calling `search_nodes(group_id="hotdesk")` silently ignores the argument because `group_id` is not a recognized parameter — the tool falls back to the default configured group.

**Fix applied:**
1. Changed `graphiti-config.yaml` default from `${GRAPHITI_GROUP_ID:hackathon}` → `${GRAPHITI_GROUP_ID:hotdesk}`
2. Added `GRAPHITI_GROUP_ID: hotdesk` to the `graphiti-mcp` service in `docker-compose.yml`
3. Recreated the container: `docker rm -f agentic-memory-benchmarking-graphiti-mcp-1 && docker compose up -d graphiti-mcp`

**When calling MCP tools, always use the list form:**
```python
# CORRECT — group_ids is a list
mcp__graphiti__search_nodes(query="coworking Praha", group_ids=["hotdesk"])
mcp__graphiti__get_episodes(group_ids=["hotdesk"], max_episodes=5)
mcp__graphiti__search_memory_facts(query="Sklik keywords", group_ids=["hotdesk"])

# WRONG — group_id (singular) is silently ignored
mcp__graphiti__search_nodes(query="...", group_id="hotdesk")  # NO-OP
```

### 5. Episode processing is async and sequential per group_id
78 episodes queued to `group_id=hotdesk` process one at a time. Each episode takes ~50-80 seconds (LLM entity extraction + embedding). Total: ~78 minutes for the full batch. Queue processing via `queue_service` is logged clearly.

---

## LiteLLM Proxy — Works Well

Using litellm as a proxy for Vertex AI works correctly:
- Routes `openai`-style calls to `vertex_ai/gemini-2.5-flash` and `vertex_ai/text-embedding-004`
- GCP service account JSON passed via volume mount + `GOOGLE_APPLICATION_CREDENTIALS`
- Proxy stays `unhealthy` per Docker healthcheck (healthcheck endpoint `/health` returns non-200) but **functions correctly** — ignore the unhealthy status
- `drop_params: true` in litellm config prevents unknown param errors

---

## Mem0 / OpenMemory MCP

- Container exposes port **8765** (not 8080 as docs suggest)
- No root route — health check must hit `/docs` not `/`
- `EMBEDDER_PROVIDER=vertexai` with `GOOGLE_APPLICATION_CREDENTIALS` works for embeddings
- `LLM_BASE_URL` pointing to litellm proxy works for LLM calls
- Port 8080 was occupied on the test machine → moved to **8181**

---

## Neo4j

- `NEO4J_PLUGINS: '["apoc"]'` auto-downloads APOC on first start — requires internet access
- `neo4j:5-community` 5.26.x supports `vector.similarity.cosine()` inline function
- Creating a VECTOR index via `CREATE VECTOR INDEX` worked syntactically but the index does not appear in `SHOW INDEXES WHERE type = 'VECTOR'` — Neo4j Community may not fully support vector indexes, but inline cosine similarity works fine without one
- Graphiti creates all required indexes via `build_indices_and_constraints()` on startup — some harmless `EquivalentSchemaRuleAlreadyExists` errors logged if indexes exist from a previous run

---

## General Infrastructure

### Port conflicts
Port 8080 was in use on the host machine. Always check ports before starting:
```bash
ss -tlnp | grep 8080
```

### bash `set -e` + arithmetic counter bug
```bash
# BROKEN: ((FAIL++)) when FAIL=0 evaluates to 0 (falsy) → exits with set -e
set -e
((FAIL++))

# FIXED:
FAIL=$((FAIL+1))
```

### docker compose ps vs docker ps -a
Services removed from `docker-compose.yml` but still running won't appear in `docker compose ps`. Use `docker ps -a` to see all containers.

### Container time vs host time
Container logs use UTC; host may be CET (UTC+1). `--since 5m` on docker logs uses container time. Account for this when reading recent logs.

---

## Data Ingestion Pipeline

- `hotdesk_sessions.json`: 78 sessions, 1050 messages, date range 2026-03-15 to 2026-03-26
- Successfully queued all 78 sessions via graphiti MCP `add_memory` with `group_id=hotdesk`, `source=message`
- Processing ongoing at time of session end — expect ~78 min total for full graph construction
- Neo4j fulltext search (`node_name_and_summary` index) works immediately once entities are stored
- Vector/semantic search via MCP may require further debugging (see Graphiti section above)

---

## Repo Structure Clarification

- `infra/` = **runtime directory** (Docker volumes, DB storage, credentials) — gitignored
- `docker-compose.yml`, `graphiti-config.yaml`, `litellm-config.yaml`, `init-scripts/`, `preflight.sh` = **infra-as-code** at repo root — git-tracked
- `credentials/` = gitignored (GCP service account JSON)
- `.env` = gitignored

---

## Pre-Hackathon Checklist Additions (Beyond Original Doc)

- [ ] Pre-pull ALL images the evening before (especially cognee 13.5GB)
- [ ] Check for port conflicts: `ss -tlnp | grep -E '8000|8050|8181|5432|6333|7474|4000'`
- [ ] Verify litellm-proxy is routing correctly even if Docker healthcheck shows unhealthy
- [ ] Run graphiti ingestion the night before — it takes ~1 min/episode
- [ ] Confirm Neo4j has entities via cypher-shell before declaring ingestion complete
- [ ] `credentials/gcp-sa.json` must be present before `docker compose up`
