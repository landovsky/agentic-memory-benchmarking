# Graphiti Smoke Test

Working smoke test of the eval harness against Graphiti (Neo4j). This was the first end-to-end run and contains fixes not yet ported to the main repo.

## Prerequisites

- Docker services running on the host machine (`docker compose up -d` from repo root)
- Neo4j reachable at `localhost:7687` (or `HOST_IP:7687`)
- PostgreSQL reachable at `localhost:5432`
- LiteLLM proxy reachable at `localhost:4000`
- Python 3.11+ with venv

## Setup

```bash
cd smoke-tests/graphiti

# Create and activate venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r eval-harness/requirements.txt
```

The scripts read `.env` from `smoke-tests/graphiti/.env` (via `python-dotenv`). Symlink it to the main project's `.env` so you don't duplicate secrets:

```bash
ln -sf ../../.env .env
```

## Quick start

```bash
./run.sh              # smoke suite (3 cases): load → eval → report
./run.sh --full       # full suite (10 cases)
./run.sh --skip-load  # skip loading if facts are already in Neo4j
./run.sh --dry-run    # preview what would be loaded
```

## Running step by step

### Step 1: Load facts into Graphiti

```bash
# Dry run — see what would be loaded
python data-loaders/load_graphiti.py \
  --facts shared-data/test-data/facts_test.json \
  --dry-run

# Load for real (5 facts into Neo4j via LiteLLM proxy)
python data-loaders/load_graphiti.py \
  --facts shared-data/test-data/facts_test.json \
  --group-id hackathon
```

The loader uses LiteLLM proxy (`LITELLM_URL`, default `http://localhost:4000`) to route LLM calls. It patches Graphiti's OpenAI client to work with LiteLLM (which doesn't support the OpenAI Responses API).

### Step 2: Run the eval harness

```bash
# Smoke test — 3 cases, fast
python eval-harness/runner.py \
  --system graphiti \
  --test-cases shared-data/test-cases/test_cases_smoke.csv \
  --runner-name <your-name>

# Full suite — 10 cases
python eval-harness/runner.py \
  --system graphiti \
  --test-cases shared-data/test-cases/test_cases.csv \
  --runner-name <your-name>
```

Results are printed to terminal and saved to PostgreSQL (`eval_results.eval_runs` table).

### Step 3: Generate HTML report

```bash
python eval-harness/report.py --output report.html
```

Open `report.html` in a browser — shows a color-coded pivot table (systems x dimensions) and detailed per-case results.

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_URL` | `http://localhost:4000` | LiteLLM proxy URL |
| `NEO4J_HOST` | `localhost` | Neo4j host |
| `NEO4J_PASSWORD` | `hackathon2025` | Neo4j password |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `RUNNER_NAME` | `default` | Identifier stored with results |

All can be overridden via `.env` or CLI flags (use `--help` on any script).

## Key differences from main repo

| Area | Main repo | This smoke test |
|------|-----------|-----------------|
| LLM client | Anthropic SDK / Gemini SDK direct | OpenAI-compatible via LiteLLM proxy |
| Scorer | `client.messages.create()` (Anthropic) | `client.chat.completions.create()` (LiteLLM) |
| Scoring method names | `"exact"`, `"llm"`, `"negation"` | `"exact_contains"`, `"llm_judge"`, `"llm_judge_negation"` (matches CSV) |
| CSV column | `row.get("expected")` (bug) | `row.get("expected_answer")` (correct) |
| DB user | `postgres` | `hackathon` |
| DB schema | `expected`, `actual`, `run_at` | `expected_answer`, `actual_answer`, `run_timestamp` |
| Graphiti client | Gemini SDK direct | OpenAI client + LiteLLM + structured completion patch |

## Results (2026-03-26)

3 smoke cases (TC-001, TC-002, TC-004):

| Test case | Dimension | Score | Latency |
|-----------|-----------|-------|---------|
| TC-001 (recall/preference) | recall | 1.000 | 1033ms |
| TC-002 (recall/semantic) | recall | 0.000 | 323ms |
| TC-004 (isolation) | isolation | 1.000 | 396ms |

TC-002 scored 0.0 because Graphiti returned facts individually ("MedicMee uses PostgreSQL", "MedicMee uses Hotwire") but missed "Rails 7.1" — the LLM judge scored it as incomplete.

## Files

- `eval-harness/` - Fixed runner, scorers, report generator
- `data-loaders/load_graphiti.py` - Graphiti loader with LiteLLM patch
- `shared-data/test-cases/` - Smoke (3) and full (10) CSV test suites
- `shared-data/test-data/` - Facts and session data used for loading
- `report.html` - Generated HTML report from the smoke run
