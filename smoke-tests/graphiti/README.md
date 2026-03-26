# Graphiti Smoke Test

Working smoke test of the eval harness against Graphiti (Neo4j). This was the first end-to-end run and contains fixes not yet ported to the main repo.

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
