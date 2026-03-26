# Project Deliverables

## Testing

### Prerequisites

- Docker services running (`docker compose up -d`, verify with `docker compose ps`)
- Python venv activated (`source .venv/bin/activate`)
- LiteLLM proxy reachable at `http://localhost:4000` (routes to Vertex AI)
- Facts loaded into the target memory system (see Ingestion above)

### 1. Load test data

Load facts into the memory system you want to evaluate. Only needed once per system (or after wiping its storage).

```bash
# Graphiti (Neo4j)
python data-loaders/load_graphiti.py --facts shared-data/test-data/facts_test.json --group-id hackathon

# Mem0 (Qdrant)
python data-loaders/load_mem0.py --facts shared-data/test-data/facts_test.json --host localhost

# Dry run (any loader) — shows what would be loaded without writing
python data-loaders/load_graphiti.py --facts shared-data/test-data/facts_test.json --dry-run
```

### 2. Run the eval harness

```bash
# Single system — smoke tests (3 cases, fast)
python eval-harness/runner.py --system graphiti \
  --test-cases shared-data/test-cases/test_cases_smoke.csv \
  --runner-name <your-name>

# Single system — full suite (10 cases)
python eval-harness/runner.py --system graphiti \
  --test-cases shared-data/test-cases/test_cases.csv \
  --runner-name <your-name>

# All systems sequentially
python eval-harness/runner.py --system all --runner-name <your-name>
```

Each test case is queried against the memory system, scored, and saved to PostgreSQL. Terminal output shows per-case scores and a summary table with averages.

### 3. Review results

**HTML report** — color-coded pivot table (systems as columns, test cases as rows):

```bash
python eval-harness/report.py --output report.html
xdg-open report.html
```

**PostgreSQL direct query:**

```bash
psql -h localhost -U hackathon -d eval_results -c \
  "SELECT system_name, test_case_id, score, latency_ms, actual_answer
   FROM eval_runs ORDER BY run_timestamp DESC;"
```

Password: `hackathon2025`

### Scoring methods

Defined per test case in the CSV `scoring_method` column:

| Method | What it does |
|--------|-------------|
| `exact_contains` | 1.0 if expected answer is a substring of actual (case-insensitive), 0.0 otherwise |
| `llm_judge` | LLM scores 0.0–1.0 how well the actual response answers the query given the expected answer |
| `llm_judge_negation` | 1.0 if the system correctly refuses (says it doesn't know), 0.0 if it hallucinated |

### Test case files

| File | Cases | Purpose |
|------|-------|---------|
| `shared-data/test-cases/test_cases_smoke.csv` | 3 | Quick validation — recall + isolation |
| `shared-data/test-cases/test_cases.csv` | 10 | Full suite — recall, temporal, isolation, hallucination, proactive, scale, type distinction |

## Agentic system memory integration

### MCP Tool Interfaces

Each memory system exposes a different MCP interface, which determines how an agentic system interacts with it in practice. The following is grounded in the source code of each MCP server (as of 2026-03-26).

---

### Mem0 (OpenMemory MCP) — `mem0/openmemory-mcp`

5 tools. Designed for **short, fact-like statements**.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add_memories` | `text: str`, `infer: bool = True` | Store a memory. When `infer=True`, Mem0's LLM extracts facts from the text. |
| `search_memory` | `query: str` | Semantic search across stored memories. |
| `list_memories` | — | List all memories for the user. |
| `delete_memories` | `memory_ids: list[str]` | Delete specific memories by UUID. |
| `delete_all_memories` | — | Delete all memories. |

- **User/app context** (`user_id`, `client_name`) is injected via URL context variables, not as tool parameters.
- **Input model**: Individual short text statements. Not designed for bulk conversation ingestion. `infer=True` can handle slightly longer text and extract facts from it.

---

### Graphiti MCP (Zep) — `zepai/knowledge-graph-mcp`

9 tools. Designed for **conversation episodes** — the most conversation-native of the three.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add_memory` | `name: str`, `episode_body: str`, `group_id: str \| None`, `source: "text" \| "json" \| "message"`, `source_description: str`, `uuid: str \| None` | Add an episode to the knowledge graph. Primary ingestion method. |
| `search_nodes` | `query: str`, `group_ids: list[str] \| None`, `max_nodes: int = 10`, `entity_types: list[str] \| None` | Search for entity nodes in the graph. |
| `search_memory_facts` | `query: str`, `group_ids: list[str] \| None`, `max_facts: int = 10`, `center_node_uuid: str \| None` | Search for facts (relationships/edges between entities). |
| `get_entity_edge` | `uuid: str` | Get a specific entity edge by UUID. |
| `get_episodes` | `group_ids: list[str] \| None`, `max_episodes: int = 10` | List recent episodes. |
| `delete_entity_edge` | `uuid: str` | Delete a specific entity edge. |
| `delete_episode` | `uuid: str` | Delete a specific episode. |
| `clear_graph` | `group_ids: list[str] \| None` | Clear all data for specified group IDs. |
| `get_status` | — | Check server and database connection status. |

- **Input model**: Episodes — full conversation chunks, JSON, or message-formatted content. `source="message"` is the conversation-native mode.
- Graphiti internally performs entity extraction, relationship detection, deduplication, and temporal tracking.

---

### Cognee MCP — `cognee/cognee-mcp`

7 tools. Designed for **documents, text blobs, and interaction logs**.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `cognify` | `data: str`, `graph_model_file: str \| None`, `graph_model_name: str \| None`, `custom_prompt: str \| None` | Transform data into a structured knowledge graph. Runs as a background task. Accepts raw text, file paths, CSV, JSON. |
| `save_interaction` | `data: str` | Log a user-agent interaction. Processes it into the knowledge graph and generates associated rules. Background task. |
| `search` | `search_query: str`, `search_type: str`, `top_k: int = 10` | Search the knowledge graph. `search_type` options: `GRAPH_COMPLETION`, `RAG_COMPLETION`, `CHUNKS`, `SUMMARIES`, `CODE`, `CYPHER`, `FEELING_LUCKY`. |
| `list_data` | `dataset_id: str \| None` | List all datasets and their data items. |
| `delete` | `data_id: str`, `dataset_id: str`, `mode: str = "soft"` | Delete specific data. Supports `"soft"` and `"hard"` modes. |
| `prune` | — | Reset the entire knowledge graph. |
| `cognify_status` | — | Check the status of a running cognify pipeline. |

- **Input model**: Raw text blobs, documents, file paths, or interaction logs. Processing is asynchronous — use `cognify_status` to check progress.
- `save_interaction` is specifically for user-agent Q&A pairs.
- `cognify` runs a full pipeline: document classification, text chunking, entity extraction, relationship detection, graph construction, summarization.

---

### Implications for data preparation

The three systems want fundamentally different input formats:

| System | Realistic input | What to feed it |
|--------|----------------|-----------------|
| **Mem0** | Individual statements/observations | Short fact-like strings, one at a time. `infer=True` can handle slightly longer text. |
| **Graphiti** | Conversation episodes | Whole conversation chunks with `source="message"`. Extracts entities/relations itself. |
| **Cognee** | Documents or interaction logs | Raw text blobs via `cognify()` or Q&A pairs via `save_interaction()`. |

The data preparation pipeline should produce **conversation segments** (the most natural form), with each system-specific loader adapting the format for its MCP interface. This ensures the benchmark reflects realistic usage rather than artificially pre-digesting the data.

---

## Ingestion

Bulk ingestion populates the memory systems with historical data so the eval harness has something to query against. The MCP tools described above are designed for real-time, single-interaction use by an agent — not for loading hundreds of memories at once. Bulk ingestion therefore **bypasses MCP** and calls each system's native API directly via Python scripts in `data-loaders/`.

### Source data

The canonical input is a set of **conversation segments** — chunks of real Claude Code sessions curated to contain memory-worthy content. These live in `shared-data/test-sessions/` and are produced by the data preparation pipeline (see below).

### Pipeline overview

The ingestion pipeline mimics how an agentic platform would store memories in real life: whole conversation messages are sent to the memory system, which handles extraction internally. We only strip JSONL noise — no pre-extraction of facts.

```
Real CC sessions (JSONL)
        │
        ▼
┌───────────────────────────┐
│  Strip & Filter           │  Drop: progress messages, tool_result content,
│  (jsonl_parser.py)        │        tool_use blocks
│                           │  Keep: user prompt strings,
│                           │        assistant text blocks
│                           │  Preserve: timestamps, parentUuid ordering,
│                           │            session metadata
└────────┬──────────────────┘
         │  Clean conversation messages (user/assistant dialogue only)
         ▼
   ┌─────┼──────┐
   ▼     ▼      ▼
 Mem0  Graphiti  Cognee    (system-specific loaders)
```

Each message (user prompt or assistant text response) is sent as-is to the memory system. The memory system decides what's worth remembering — that's part of what we're benchmarking.

### System-specific ingestion

Each loader sends cleaned conversation messages via the system's native interface:

**Graphiti** — Feed each message as an episode with `source="message"`. Graphiti extracts entities, builds relationships, and handles temporal tracking internally.

**Cognee** — Feed messages via `save_interaction()` (for user-agent Q&A pairs) or `cognify()` (for longer text). Cognee runs its full pipeline: chunking, entity extraction, graph construction.

**Mem0** — Feed each message via `Memory.add()` with `infer=True`. Mem0's LLM extracts facts from the text. This is the closest analogue to how `add_memories` works via MCP.

### TODO

- [ ] Update `jsonl_parser.py` to strip tool_use blocks from assistant messages (currently keeps all content blocks). Output should be clean user/assistant dialogue only.
- [ ] Rewrite `load_graphiti.py` to send conversation messages as `source="message"` episodes instead of pre-extracted facts.
- [ ] Rewrite `load_cognee.py` to use `save_interaction()` for Q&A pairs instead of joining facts into text blobs.
- [ ] Update `load_mem0.py` to send conversation messages with `infer=True` instead of pre-extracted facts.
- [ ] Decide on message granularity: one message per API call vs. batching user+assistant pairs as a single episode.
- [ ] Handle secrets — ensure `strip-claude-secrets.py` runs before ingestion (tool_result stripping helps, but user prompts can also contain secrets).

---

## Golden dataset

The golden dataset is a curated set of test queries with known expected answers, used by the eval harness to score each memory system. It is produced from the same stripped sessions used for ingestion.

### Curation process

```
Stripped sessions (clean dialogue)
        │
        ▼
┌───────────────────────────────┐
│  Claude curates               │  Explores sessions, identifies topics
│                               │  that cover the benchmark dimensions:
│                               │  recall, temporal, isolation,
│                               │  hallucination, proactive, scale,
│                               │  type distinction
└────────┬──────────────────────┘
         │  Candidate topics + lines of enquiry
         ▼
┌───────────────────────────────┐
│  Claude generates test cases  │  For each topic, generates:
│                               │  - query (what to ask the system)
│                               │  - expected answer
│                               │  - dimension + memory type tags
│                               │  - scoring method
│                               │  - source session reference
└────────┬──────────────────────┘
         │  golden_dataset.json (draft)
         ▼
┌───────────────────────────────┐
│  Human review                 │  Verify expected answers are correct,
│                               │  adjust scoring methods, remove
│                               │  ambiguous cases
└────────┬──────────────────────┘
         │  golden_dataset.json (final) → shared-data/test-cases/
         ▼
       Eval harness
```

The output format matches the existing `test_cases.json` schema: `{id, dimension, memory_type, project_scope, setup_memory, query, expected_answer, scoring_method, notes}`.

### TODO

- [ ] Pick a project with sufficient session history (medium size — not the largest, to control token cost).
- [ ] Run strip & filter on its sessions to produce clean dialogue transcripts.
- [ ] Have Claude explore transcripts and propose candidate topics per benchmark dimension.
- [ ] Have Claude generate test cases from approved topics.
- [ ] Human review and finalize the golden dataset.
- [ ] Replace or extend `shared-data/test-cases/test_cases.json` with the curated dataset.
