# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A hackathon benchmark comparing three AI memory systems — **Mem0** (vector/Qdrant), **Graphiti** (knowledge graph/Neo4j), and **Cognee** (graph+semantic/PostgreSQL) — to evaluate recall, temporal reasoning, hallucination resistance, and other memory dimensions.

## Setup

```bash
# Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r eval-harness/requirements.txt
pip install -r data-loaders/requirements.txt

# Configure secrets
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, GOOGLE_API_KEY, RUNNER_NAME, HOST_IP
```

## Infrastructure (Host Machine)

```bash
docker compose up -d          # Start all services
docker compose ps             # Check health
docker compose down           # Stop (keep data)
docker compose down -v        # Stop + wipe volumes
bash preflight.sh             # Run health checks
```

## MCP Setup (Participant Machines)

```bash
bash setup-mcp.sh 192.168.x.x   # Register all 3 MCP servers in Claude Code
claude mcp list                  # Verify
```

## Running Evaluations

```bash
# Single system
python -m eval_harness.runner --system mem0 --runner <name> --host <HOST_IP>
python -m eval_harness.runner --system graphiti --runner <name> --host <HOST_IP>
python -m eval_harness.runner --system cognee --runner <name> --host <HOST_IP>

# All systems
python -m eval_harness.runner --system all --runner <name> --host <HOST_IP>

# Generate HTML report (reads from PostgreSQL)
python eval-harness/report.py --host <HOST_IP> --output report.html
```

## Data Loading Pipeline

Run in order to populate memory systems from Claude Code session files:

```bash
python data-loaders/jsonl_parser.py --file session.jsonl --output sessions.json
python data-loaders/memory_extractor.py --input sessions.json --output facts.json
python data-loaders/load_mem0.py --facts facts.json --host <HOST_IP>
python data-loaders/load_graphiti.py --facts facts.json --host <HOST_IP>
python data-loaders/load_cognee.py --facts facts.json --host <HOST_IP>
```

## Architecture

### Services and Ports

| Service | Port | Role |
|---------|------|------|
| PostgreSQL (pgvector) | 5432 | Eval results (`eval_runs` table) + Cognee storage |
| Qdrant | 6333 | Mem0 vector store |
| Neo4j | 7474/7687 | Graphiti graph DB |
| Mem0 MCP | 8181 | `/sse` — Claude Haiku LLM + Qdrant |
| Graphiti MCP | 8050 | MCP endpoint — Gemini 2.0 Flash + Neo4j |
| Cognee MCP | 8000 | `/mcp/sse` — Claude LLM + PostgreSQL + Gemini embeddings |
| File Server | 9000 | Serves `shared-data/` over HTTP |

### Evaluation Flow

1. `eval-harness/runner.py` reads test cases from `shared-data/test-cases/test_cases.csv`
2. For each test case, queries the target memory system (Mem0/Graphiti/Cognee SDK)
3. Scores the response using one of three methods in `eval-harness/scorers.py`:
   - **exact_contains** — substring match
   - **llm_judge** — Claude grades whether the answer is correct
   - **llm_judge_negation** — Claude checks that system properly refuses unknown queries (anti-hallucination)
4. Persists (system, query, answer, score, latency_ms) to the `eval_runs` PostgreSQL table
5. `report.py` queries PostgreSQL and generates a color-coded HTML pivot table

### Data Loading Flow

`jsonl_parser.py` → structured conversation JSON → `memory_extractor.py` (Claude extracts facts with type: preference/episodic/semantic/goal + confidence) → system-specific loaders (`load_mem0.py`, `load_graphiti.py`, `load_cognee.py`)

### Test Cases

10 cases in Czech across 7 dimensions (`shared-data/test-cases/`): recall, temporal, isolation, hallucination, proactive, scale (100 vs 1000 facts), type_distinction. Projects referenced: MedicMee, HřištěHrou, Pharmacy.

## Key Credentials (Hardcoded for Docker environment)

- PostgreSQL: `hackathon / hackathon2025`
- Neo4j: `neo4j / hackathon2025`
- Primary LLM: `claude-3-5-haiku-20241022`; Graphiti fallback: Gemini 2.0 Flash
