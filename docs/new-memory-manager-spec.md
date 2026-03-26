# Specification: Graphiti Memory Benchmarking (v2)

## Overview

A clean TypeScript monorepo that ingests Claude Code session JSONL files into Graphiti (Neo4j knowledge graph), exposes memory via the standard Graphiti MCP server, evaluates recall quality with a golden test dataset, and produces HTML reports.

---

## Repo Structure

```
graphiti-memory-bench/
├── packages/
│   ├── ingest/          # CLI: parse JSONL → load into Graphiti
│   ├── eval/            # CLI: run test cases, score, persist, generate report
│   └── shared/          # Types, DB client, scorer
├── data/
│   ├── sessions/        # Drop .jsonl files here
│   └── test-cases/      # test_cases.json
├── infra/
│   ├── docker-compose.yml
│   └── graphiti-config.yaml
├── reports/             # Generated HTML output
├── package.json         # workspace root
└── .env.example
```

MCP server = the stock `zepai/knowledge-graph-mcp` Docker image, zero custom code.

---

## Infrastructure

Four services (vs. six previously — Mem0, Cognee, and Qdrant are gone):

| Service | Port | Role |
|---------|------|------|
| Neo4j 5 | 7474 / 7687 | Graphiti graph DB |
| Graphiti MCP | 8050 | Standard MCP server |
| LiteLLM proxy | 4000 | OpenAI-compatible gateway → Gemini via GCP ADC |
| PostgreSQL | 5432 | Eval results storage |

**LiteLLM proxy is kept** for Graphiti's internal LLM calls (entity extraction, embeddings). Graphiti's MCP container requires an OpenAI-compatible endpoint; LiteLLM handles that and transparently authenticates to Gemini/Vertex AI using `GOOGLE_APPLICATION_CREDENTIALS_JSON` (a mounted service-account JSON string — no plain API key needed).

The TypeScript packages (`ingest`, `eval`) use the Anthropic SDK directly for scoring — no LiteLLM involved there.

---

## Neo4j Schema (Entity Types)

Graphiti extracts entities automatically from episode text using these type hints registered in `graphiti-config.yaml`:

| Entity | Key Properties | Purpose |
|--------|---------------|---------|
| `Project` | id (slug), name, path_hash, language, framework, status | Top-level namespace; maps to `project_hash` from JSONL path |
| `Session` | id (UUID), file_path, message_count, first/last_timestamp | Provenance anchor for everything extracted |
| `Decision` | title, rationale, alternatives[], status, decided_at | Arch/design choices — the hardest thing to recover from code alone |
| `Bug` | title, description, root_cause, fix_description, status, severity | Recurring problems; "have we seen this before?" |
| `Feature` | name, description, status, acceptance_criteria | Product capability / user story |
| `Task` | title, description, status, session_mentioned | TODO items surfaced in conversations |
| `File` | path, language, purpose | Source files discussed or modified |
| `Dependency` | name, version, dependency_type, added_at | External libs/services |
| `Person` | name, role | Developer, colleague, stakeholder |
| `Concept` | name, definition, domain | Project-specific vocabulary and domain terms |
| `Configuration` | key, value, scope, is_secret | Settings, flags, conventions |
| `Other` | name, summary | Catch-all for entities that don't fit the above types |

**Key relationships:**
```
Session  -[:BELONGS_TO]->      Project
Session  -[:PRODUCED]->        Decision
Session  -[:MENTIONED]->       Bug | Feature | Task
Session  -[:TOUCHED]->         File
Decision -[:SUPERSEDES]->      Decision  { at, reason }
Bug      -[:FOUND_IN]->        File
Bug      -[:BLOCKS]->          Task
Task     -[:PART_OF]->         Feature
Task     -[:MODIFIES]->        File
Project  -[:USES]->            Dependency
Person   -[:PARTICIPATED_IN]-> Session
```

Temporality is handled by Graphiti's native bi-temporal model (`valid_at` / `invalid_at` on edges). Nodes carry `status` + timestamp pairs instead of being deleted, preserving history.

---

## Package: `ingest`

**Input:** one or more `.jsonl` session files (Claude Code format)
**Output:** episodes loaded into Graphiti

Session data shape:
```json
[{
  "session_id": "uuid",
  "file": "/path/to/project/session.jsonl",
  "project_hash": "-Users-tomas-git-hotdesk",
  "messages": [
    { "role": "user", "content": "...", "timestamp": "ISO8601" },
    { "role": "assistant", "content": "...", "timestamp": "ISO8601" }
  ]
}]
```

**Pipeline:**
1. **Parse** — `jsonl-parser.ts`: reads JSONL, extracts user/assistant messages (handles both plain strings and multi-block content arrays), returns typed `Session[]`
2. **Load** — `loader.ts`: for each session, calls Graphiti MCP HTTP API to add an episode:
   - `name`: `session_{project_hash}_{session_id_short}`
   - `episode_body`: messages formatted as `[role]: content\n\n`
   - `source`: `message`
   - `reference_time`: first message timestamp
   - `group_id`: project_hash (natural isolation per project)
3. **Progress** — tracks processed session IDs in a local state file to support resume on failure
4. **Logging** — after each episode is added, queries Graphiti for the entities and relationships that were extracted from it and logs them to stdout in a structured format:
   ```
   [session abc123] extracted 7 entities: Project("hotdesk"), File("src/api.ts"), Decision("use PostgreSQL"), ...
   [session abc123] extracted 4 edges: File -PART_OF-> Project, Decision -AFFECTS-> File, ...
   ```
   This makes it easy to verify extraction quality during development without opening Neo4j Browser.

**CLI:**
```bash
pnpm ingest --file ./data/sessions/project.jsonl
pnpm ingest --dir ./data/sessions/   # batch all files in directory
pnpm ingest --dry-run                # preview without API calls
```

---

## Package: `eval`

### Test Case Schema

```typescript
interface TestCase {
  id: string;                    // e.g. "SOFTDEV-001"
  dimension: Dimension;
  memory_type: MemoryType;
  project_scope: string;         // "global" or a project slug
  setup_memory: string;          // context that should be in memory; "(none)" for hallucination tests
  query: string;
  expected_answer: string;
  scoring_method: ScoringMethod;
  priority: "critical" | "high" | "medium" | "low";
  min_acceptable_score: number;  // default 0.5
  tags: string[];
  notes: string;
}

type Dimension =
  | "recall"           // exact fact retrieval (coding patterns, conventions)
  | "temporal"         // fact evolution over time (decisions that changed)
  | "isolation"        // per-project scoping (facts from project A don't leak to B)
  | "hallucination"    // system correctly says "I don't know" for unmentioned topics
  | "proactive"        // surfacing related context when a similar problem recurs
  | "context_boundary" // distinguishing architectural convention vs. one-time workaround
  | "scale"            // recall quality at 100 vs. 1000 ingested facts
  | "type_distinction" // separating preference/convention from episodic event

type MemoryType =
  | "semantic"
  | "episodic"
  | "preference"
  | "goal"
  | "procedural"
  | "semantic+episodic"
  | "preference+episodic"
  | "none"

type ScoringMethod = "exact_contains" | "llm_judge" | "llm_judge_negation"
```

**Example test case:**
```json
{
  "id": "SOFTDEV-001",
  "dimension": "recall",
  "memory_type": "semantic",
  "project_scope": "global",
  "setup_memory": "The pattern for database access control uses SQLAlchemy ORM with explicit get_locked_*() methods for row-level locks via with_for_update().",
  "query": "I need to update a user record safely. Should I use get_locked_user_by_id()?",
  "expected_answer": "Yes — use get_locked_user_by_id() which applies a row-level lock via with_for_update() to prevent concurrent modifications.",
  "scoring_method": "llm_judge",
  "priority": "critical",
  "min_acceptable_score": 0.8,
  "tags": ["golden-set", "concurrency"],
  "notes": "Tests recall of row-level locking convention for database updates"
}
```

### Scoring Methods

| Method | Logic |
|--------|-------|
| `exact_contains` | Case-insensitive substring match of `expected` in `actual` |
| `llm_judge` | Claude (Haiku) grades whether `actual` answers `query` given `expected` → float 0–1 |
| `llm_judge_negation` | Claude checks that system correctly refuses an unknown query → 1.0 = correct refusal, 0.0 = hallucination |

### Eval Results Schema (PostgreSQL)

```sql
CREATE TABLE eval_runs (
  id              SERIAL PRIMARY KEY,
  run_id          UUID NOT NULL,
  runner_name     TEXT NOT NULL,
  run_at          TIMESTAMPTZ DEFAULT NOW(),
  test_case_id    TEXT NOT NULL,
  dimension       TEXT NOT NULL,
  memory_type     TEXT,
  query           TEXT NOT NULL,
  expected        TEXT,
  actual          TEXT,
  score           NUMERIC(4,3),    -- 0.000 to 1.000
  latency_ms      INTEGER,
  scoring_method  TEXT,
  passed          BOOLEAN,
  priority        TEXT,
  tags            TEXT[]
);

-- Summary view used by report
CREATE VIEW eval_summary AS
SELECT
  dimension,
  COUNT(*)                                                    AS total,
  SUM(CASE WHEN passed THEN 1 ELSE 0 END)                    AS passed,
  ROUND(AVG(score)::NUMERIC, 3)                              AS avg_score,
  ROUND(AVG(latency_ms)::NUMERIC, 0)                        AS avg_latency_ms
FROM eval_runs
GROUP BY dimension;
```

### CLI

```bash
pnpm eval run --runner tomas                # run all test cases
pnpm eval run --dimension recall,temporal   # filter by dimension
pnpm eval run --priority critical           # filter by priority
pnpm eval report --output reports/out.html  # generate HTML report from DB
```

### HTML Report

Two sections:
1. **Summary table** — dimension rows × avg score, color-coded (red < 0.5, yellow < 0.8, green ≥ 0.8), with pass rate and avg latency
2. **Detail table** — every run with query / expected / actual / score / latency / method

---

## Package: `shared`

- `types.ts` — all shared interfaces (`Session`, `Message`, `TestCase`, `EvalResult`, etc.)
- `db.ts` — PostgreSQL client (init schema, `saveResult()`, `queryForReport()`)
- `graphiti-client.ts` — typed wrapper around Graphiti MCP HTTP API (`addEpisode()`, `search()`)
- `scorers.ts` — `exactContains()`, `llmJudge()`, `llmJudgeNegation()`

---

## Environment & Configuration

All service locations are configured via environment variables (`.env` file at repo root), with sensible localhost defaults for local development:

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt URL |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | _(required)_ | Neo4j password |
| `POSTGRES_URL` | `postgres://localhost:5432/eval` | PostgreSQL connection string |
| `GRAPHITI_MCP_URL` | `http://localhost:8050` | Graphiti MCP HTTP endpoint |
| `ANTHROPIC_API_KEY` | _(required)_ | For scoring LLM calls |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | _(required)_ | GCP service account JSON (for LiteLLM → Gemini) |

The `infra/docker-compose.yml` sets these to the in-Docker service hostnames; running the TS packages against a remote or cloud-hosted stack is a matter of changing the env vars only.

---

## Tech Stack

| Concern | Choice |
|---------|--------|
| Language | TypeScript (strict) |
| Runtime | Node.js 22 |
| Package manager | pnpm workspaces |
| Graphiti integration | Graphiti MCP HTTP API (no Python dependency) |
| LLM for scoring | Anthropic SDK — `claude-3-5-haiku-20241022` |
| Database client | `pg` (node-postgres) |
| Infra | Docker Compose |

**Why MCP HTTP over the Python SDK:** The official Graphiti SDK is Python-only. Calling the Graphiti MCP server's HTTP API directly keeps the repo pure TypeScript, creates a clean boundary between infra and application code, and exercises the same interface that Claude Code participants use.

---

## Open / Deferred

- **Async background ingestion** — file watcher on `data/sessions/` that auto-ingests dropped files (deferred)
- **Test case generator** — LLM-assisted tool to extract Q&A pairs from sessions and draft new test cases (deferred)
