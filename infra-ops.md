# infra/ — Hackathon Infrastructure

> **gitignored** — never commit this directory.

## Setup

```bash
cp ../.env.example .env
# Edit .env — fill in ANTHROPIC_API_KEY and GOOGLE_API_KEY
```

## Start

```bash
docker compose up -d
docker compose ps     # verify all healthy
```

## Pre-pull images (do this the day before!)

```bash
docker compose pull
```

This pulls: pgvector/pgvector, qdrant/qdrant, neo4j:5-community, mem0/openmemory-mcp, zepai/knowledge-graph-mcp, cognee/cognee-mcp, halverneus/static-file-server

## Port reference

| Service | Host Port | Purpose |
|---------|-----------|---------|
| PostgreSQL | 5432 | Eval results DB + Cognee storage |
| Qdrant | 6333 | Mem0 vector store |
| Neo4j HTTP | 7474 | Neo4j browser UI |
| Neo4j Bolt | 7687 | Graphiti connection |
| Cognee MCP | 8000 | SSE at /mcp/sse |
| Mem0 MCP | 8080 | SSE at /sse |
| Graphiti MCP | 8050 | MCP endpoint |
| File server | 9000 | Shared test data HTTP |

## Logs

```bash
docker compose logs -f mem0-mcp
docker compose logs -f graphiti-mcp
docker compose logs -f cognee-mcp
```

## Pre-flight checks (from another machine)

```bash
curl http://HOST_IP:8080/health    # Mem0
curl http://HOST_IP:8000/health    # Cognee
curl http://HOST_IP:8050/health    # Graphiti
# Neo4j browser: http://HOST_IP:7474
# File server: http://HOST_IP:9000/test-cases/test_cases.csv
```

Or run the bundled script:

```bash
bash preflight.sh              # check localhost
bash preflight.sh 192.168.1.X  # check from another machine
```

## Teardown

```bash
docker compose down          # stop, keep data
docker compose down -v       # stop + delete all volumes (reset)
```

## Notes

- `OPENAI_API_KEY` is only needed for Mem0's OpenAI embedder. If unavailable,
  switch `EMBEDDER_PROVIDER=ollama` in docker-compose.yml and add an ollama service.
- Neo4j APOC plugin is auto-downloaded on first start — needs internet access.
- Cognee connects to the `cognee` database on the shared postgres instance.
- The fileserver serves `../shared-data` (repo root `shared-data/`) over HTTP on port 9000.
