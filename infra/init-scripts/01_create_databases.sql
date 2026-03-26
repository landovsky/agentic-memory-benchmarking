-- Postgres init: separate DB per system + eval results
-- Runs automatically on first container start

CREATE DATABASE mem0;
CREATE DATABASE cognee;
CREATE DATABASE eval_results;

-- pgvector extension in all DBs
\c mem0
CREATE EXTENSION IF NOT EXISTS vector;

\c cognee
CREATE EXTENSION IF NOT EXISTS vector;

\c eval_results
CREATE EXTENSION IF NOT EXISTS vector;

-- Eval results schema
\c eval_results
CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    system_name TEXT NOT NULL,
    test_case_id TEXT NOT NULL,
    dimension TEXT NOT NULL,
    memory_type TEXT,
    query TEXT NOT NULL,
    expected_answer TEXT,
    actual_answer TEXT,
    score NUMERIC(3,2),
    latency_ms INTEGER,
    notes TEXT,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    runner TEXT
);

CREATE INDEX idx_eval_system ON eval_runs(system_name);
CREATE INDEX idx_eval_dimension ON eval_runs(dimension);
CREATE INDEX idx_eval_test_case ON eval_runs(test_case_id);
