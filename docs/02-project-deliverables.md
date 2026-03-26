# Project Deliverables

## Testing

### Prerequisites

- Docker services running (`docker compose up -d`, verify with `docker compose ps`)
- Python venv activated (`source .venv/bin/activate`)
- LiteLLM proxy reachable at `http://localhost:4000` (routes to Vertex AI)
- Facts loaded into the target memory system (see Ingestion above)

### 1. Load test data

Load historical conversation data into the memory system you want to evaluate. Only needed once per system (or after wiping its storage). See the **Ingestion** section below for the full pipeline.

> **Note:** The loader commands below still reference the old `--facts` interface. They will be rewritten to accept stripped conversation messages (strip-and-feed approach) instead of pre-extracted facts. See Ingestion TODOs.

### 2. Run the eval harness

```bash
# Single system
python eval-harness/runner.py --system graphiti --runner-name <your-name>

# All systems sequentially
python eval-harness/runner.py --system all --runner-name <your-name>
```

> **Note:** Once the runner is updated to fetch from Google Sheets, no `--test-cases` argument is needed. The URL is configured as a constant/env var.

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

| File | Source | Purpose |
|------|--------|---------|
| Google Sheets published CSV | Dynamic, team-editable | Source of truth — fetched at runtime by runner |
| `shared-data/test-cases/test_cases.csv` | Local snapshot (to be replaced by fetch) | Currently 19 cases — recall, temporal, isolation, hallucination, proactive, scale, type distinction |
| `shared-data/test-cases/test_cases_smoke.csv` | **MISSING** | Was planned for quick validation — does not exist |

### Discrepancies & questions (testing)

1. **CSV should be fetched dynamically from Google Sheets.** The test cases are maintained as a published Google Sheet CSV. The runner should fetch from a URL (constant at top of file or env var with default), not read a local file. The local `test_cases.csv` and `test_cases.json` files should be removed or treated as cache only.

2. **Results must snapshot the test case at eval time.** Since the remote CSV can change between runs, the `eval_runs` table must store the full test case data (query, expected_answer, dimension, scoring_method, etc.) alongside the result. Currently results reference a `test_case_id` that may point to different content across runs. Without snapshotting, historical results become uninterpretable.

3. **`test_cases_smoke.csv` doesn't exist.** Doc references it but the file was never created.

4. **BUG: `expected` vs `expected_answer` column name in main repo runner.** `runner.py:262` reads `row.get("expected", "")` but the CSV column is `expected_answer`. This means the runner passes empty strings to scorers. The graphiti-smoke variant already fixed this — it reads `row.get("expected_answer", "")` at line 314. **Must be fixed.**

5. **BUG: Scoring method names don't match between CSV and main repo scorer.** The CSV uses `exact_contains`, `llm_judge`, `llm_judge_negation`. But `scorers.py` in the main repo dispatches on `"exact"`, `"llm"`, `"negation"`. Any CSV test case hits `raise ValueError(f"Unknown scoring method: ...")`. The graphiti-smoke variant's `scorers.py` already uses the full names (`exact_contains`, `llm_judge`, `llm_judge_negation`). **Must be ported.**

6. **BUG: Scoring method check for client is also wrong.** `runner.py:284` checks `scoring_method in ("llm", "negation")` to decide whether to pass the LLM client. With CSV values being `llm_judge` / `llm_judge_negation`, the client is never passed → scorer raises ValueError. Graphiti-smoke variant checks `("llm_judge", "llm_judge_negation")`. **Must be fixed.**

7. **Main repo scorer uses Anthropic SDK directly, not LiteLLM.** `scorers.py` calls `client.messages.create()` (Anthropic native). The graphiti-smoke variant uses `client.chat.completions.create()` (OpenAI-compatible / LiteLLM). Per the LiteLLM-only strategy, the main repo scorer should be ported to use OpenAI-compatible client via LiteLLM.

8. **DB user mismatch.** Main repo `runner.py:45` connects as `user="postgres"`, graphiti-smoke uses `user="hackathon"`. CLAUDE.md says credentials are `hackathon / hackathon2025`.

9. **Dimension coverage is unbalanced.** 11/19 cases are `recall`, 1 each for temporal, isolation, hallucination, proactive, scale, type_distinction. The CSV should be extended with more non-recall cases. Consider adding a `dimension` (or `test_type`) column to the Google Sheet to make this visible to team members adding test cases.

10. **`setup_memory` column is descriptive, not actionable.** The runner ignores it. Scale tests (TC-008 "100 memories", TC-009 "1000 memories") require different DB states but run in the same CSV pass. No mechanism ensures the right state. This is acceptable if scale tests are run manually, but should be documented.

11. **Mixed languages (Czech/English) in test cases.** TC-001–010 are Czech; TC-011–019 have Czech `setup_memory` but English queries/answers. Fine if intentional, but undocumented.

### TODO (testing)

- [ ] Fetch test cases from Google Sheets published CSV URL (constant/env var with default).
- [ ] Store full test case snapshot in `eval_runs` (or a linked `eval_test_case_snapshots` table).
- [ ] Fix `runner.py`: read `expected_answer` not `expected`.
- [ ] Port `scorers.py` to use OpenAI-compatible client (LiteLLM proxy) instead of Anthropic SDK.
- [ ] Fix scoring method names in `scorers.py` dispatcher to match CSV values (`exact_contains`, `llm_judge`, `llm_judge_negation`).
- [ ] Fix client-passing logic in runner to match the full method names.
- [ ] Fix DB user to `hackathon` (not `postgres`).
- [ ] Extend Google Sheet with more non-recall test cases (temporal, hallucination, proactive, etc.).

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

**Graphiti** (`data-loaders/load_graphiti.py`) — **Done.** Reads `--sessions` JSON (array of `{session_id, messages: [{role, content, timestamp}]}`). Flattens all messages, sends each as an episode via `graphiti.add_episode()` with `source=EpisodeType.message` and body formatted as `"role: content"` (the format Graphiti's message type expects). Uses `graphiti-core[openai]` with OpenAI-compatible clients routed through LiteLLM proxy — requires a monkey-patch (`_patch_openai_client_for_litellm`) because Graphiti v0.28 uses the OpenAI Responses API (`/v1/responses`) which LiteLLM doesn't support; the patch redirects structured completions to `chat.completions` with JSON mode. Each message becomes a separate episode with its original timestamp as `reference_time`, enabling Graphiti's temporal tracking. Graphiti extracts entities, builds relationships, and handles deduplication internally.

```bash
# Dry run (no infra needed)
python3 data-loaders/load_graphiti.py --sessions shared-data/hotdesk_sessions.json --dry-run

# Real run (needs Neo4j + LiteLLM proxy running)
python3 data-loaders/load_graphiti.py --sessions shared-data/hotdesk_sessions.json --host <HOST_IP>
```

**Cognee** — Feed messages via `save_interaction()` (for user-agent Q&A pairs) or `cognify()` (for longer text). Cognee runs its full pipeline: chunking, entity extraction, graph construction.

**Mem0** — Feed each message via `Memory.add()` with `infer=True`. Mem0's LLM extracts facts from the text. This is the closest analogue to how `add_memories` works via MCP.

### TODO

- [x] Update `jsonl_parser.py` to strip tool_use blocks from assistant messages (currently keeps all content blocks). Output should be clean user/assistant dialogue only.
- [x] Rewrite `load_graphiti.py` to send conversation messages as `source="message"` episodes instead of pre-extracted facts.
- [ ] Rewrite `load_cognee.py` to use `save_interaction()` for Q&A pairs instead of joining facts into text blobs.
- [x] Update `load_mem0.py` to send conversation messages with `infer=True` instead of pre-extracted facts.
- [x] Decide on message granularity: one message per API call vs. batching user+assistant pairs as a single episode.
- [ ] Handle secrets — ensure `strip-claude-secrets.py` runs before ingestion (tool_result stripping helps, but user prompts can also contain secrets).

### Discrepancies & questions (ingestion)

1. **Code still does "extract-and-feed", not "strip-and-feed".** The pipeline overview describes sending raw messages to memory systems (letting them extract facts internally), but the actual code runs the old pipeline: `jsonl_parser.py` → `memory_extractor.py` (LLM-based fact extraction) → loaders consume `facts.json`. All three loaders (`load_mem0.py`, `load_graphiti.py`, `load_cognee.py`) accept `--facts facts.json` and iterate over pre-extracted fact objects. They need to be rewritten to accept cleaned conversation messages instead.
   - `memory_extractor.py` should be removed or marked as deprecated — it contradicts the strip-and-feed approach where memory systems do their own extraction.

2. **`shared-data/test-sessions/` doesn't exist.** Doc references it as the canonical location for stripped sessions, but the directory was never created. No sample data exists there.

3. **`shared-data/test-data/` doesn't exist either.** The Testing section references `shared-data/test-data/facts_test.json` for loader commands, but this directory/file doesn't exist.

4. **Loaders use direct API keys, not LiteLLM proxy.** `load_mem0.py` uses `ANTHROPIC_API_KEY` directly with the Anthropic SDK. ~~`load_graphiti.py` uses `GOOGLE_API_KEY` directly.~~ `load_graphiti.py` is now fixed — uses OpenAI-compatible clients via LiteLLM proxy (ported from the graphiti-smoke variant). The remaining loaders need the same treatment.

5. **Single-message vs. episode granularity.** Each message (user→LLM or LLM→user) is ingested as a separate document. This mimics how agentic platforms integrate — each turn triggers a memory write. However, Graphiti's `add_memory` with `source="message"` is designed for conversation episodes (multi-turn chunks). Feeding single messages may lose context that Graphiti is designed to exploit. **Open question for Timur:** does Graphiti's internal entity extraction work well on single messages, or does it need multi-turn context to build meaningful relationships?

6. **Cognee loader uses `cognee.add()` + `cognee.cognify()`, not `save_interaction()`.** The doc says to use `save_interaction()` for Q&A pairs, but the current code joins all facts into a text blob. This needs rewriting to align with single-message ingestion.

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

### Discrepancies & questions (golden dataset)

1. **Golden dataset section describes a future process, but TC-011–019 already exist.** The golden dataset TODO says "pick a project, strip sessions, generate test cases" — but 9 golden-set cases are already in the CSV/JSON. Were these produced through this process or manually? If manually, the curation process diagram is aspirational, not descriptive.

2. **No source session references on golden cases.** The curation process says to include "source session reference" but TC-011–019 have no session reference. This makes it impossible to trace back which conversation the expected answer came from.

3. **Golden dataset vs. test_cases — same file or separate?** The doc says "Replace or extend `test_cases.json`" but it's unclear whether the golden dataset is the same artifact as the test cases or a superset. Currently they're merged into one file.

---

## Integration (Agentic / MCP)

### TODO (integration — future work)

- [ ] **Agent-in-the-loop eval path.** Current eval queries memory SDKs directly. For proactive dimension testing (TC-006), need an LLM agent loop: user query → LLM → LLM decides to call memory tool → memory result → LLM synthesizes answer → scorer. Without this, proactive test cases can't be meaningfully scored.
- [ ] **MCP integration tests.** MCP tool interfaces are documented in detail above but the eval harness bypasses MCP entirely. Add a test path that exercises the actual MCP endpoints.
- [ ] **End-to-end `save_interaction()` test for Cognee.** The doc says it's the conversation-native method, but no code path exercises it.
- [ ] **Measure integration quality, not just retrieval quality.** Current eval measures whether the memory system returns the right data. A fuller benchmark would measure whether an LLM agent uses memory tools effectively (retrieval + synthesis + proactive invocation).
