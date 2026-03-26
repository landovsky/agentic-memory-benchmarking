#!/usr/bin/env python3
"""Evaluation harness runner.

Reads test cases from CSV, queries each memory system, scores answers,
saves results to PostgreSQL.

Usage:
    python runner.py --system mem0 [--host localhost] [--runner-name alice]
    python runner.py --system graphiti --host 192.168.1.100
    python runner.py --system cognee --test-cases ../shared-data/test-cases/test_cases.csv
    python runner.py --system all  # run all 3 systems sequentially
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import openai
import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_TEST_CASES = Path(__file__).parent.parent / "shared-data" / "test-cases" / "test_cases.csv"
SYSTEMS = ("mem0", "graphiti", "cognee")
MEM0_MODEL = "claude-3-5-haiku-20241022"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db_connection(postgres_host: str) -> Any:
    return psycopg2.connect(
        host=postgres_host,
        port=5432,
        dbname="eval_results",
        user="hackathon",
        password="hackathon2025",
    )


def ensure_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_runs (
                id              SERIAL PRIMARY KEY,
                system_name     TEXT NOT NULL,
                test_case_id    TEXT NOT NULL,
                dimension       TEXT NOT NULL,
                memory_type     TEXT,
                query           TEXT NOT NULL,
                expected_answer TEXT,
                actual_answer   TEXT,
                score           NUMERIC(3,2),
                latency_ms      INTEGER,
                notes           TEXT,
                run_timestamp   TIMESTAMPTZ DEFAULT NOW(),
                runner          TEXT
            )
            """
        )
    conn.commit()


def save_result(
    conn: Any,
    runner_name: str,
    system_name: str,
    test_case_id: str,
    dimension: str,
    memory_type: str,
    query: str,
    expected: str,
    actual: str,
    score: float,
    latency_ms: int,
    scoring_method: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval_runs
                (system_name, test_case_id, dimension, memory_type,
                 query, expected_answer, actual_answer, score, latency_ms,
                 notes, runner)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                system_name,
                test_case_id,
                dimension,
                memory_type,
                query,
                expected,
                actual,
                score,
                latency_ms,
                scoring_method,
                runner_name,
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Memory system query helpers
# ---------------------------------------------------------------------------

def query_mem0(query: str, mem0_host: str) -> str:
    from mem0 import Memory  # type: ignore[import]

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    qdrant_host = os.environ.get("QDRANT_HOST", mem0_host)

    config: dict[str, Any] = {
        "llm": {
            "provider": "anthropic",
            "config": {
                "model": MEM0_MODEL,
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "url": f"http://{qdrant_host}:6333",
                "collection_name": "hackathon_mem0",
            },
        },
    }
    m = Memory.from_config(config)
    results = m.search(query, user_id="hackathon", limit=5)
    hits = results.get("results", [])
    if hits:
        return hits[0].get("memory", "No results")
    return "No results"


async def query_graphiti_async(query: str, neo4j_host: str) -> str:
    from graphiti_core import Graphiti  # type: ignore[import]
    from graphiti_core.llm_client.openai_client import OpenAIClient, LLMConfig  # type: ignore[import]
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig  # type: ignore[import]
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient  # type: ignore[import]

    litellm_url = os.environ.get("LITELLM_URL", "http://localhost:4000")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "hackathon2025")

    llm_config = LLMConfig(api_key="dummy", base_url=litellm_url, model="gemini-flash")
    graphiti = Graphiti(
        f"bolt://{neo4j_host}:7687",
        "neo4j",
        neo4j_password,
        llm_client=OpenAIClient(config=llm_config),
        embedder=OpenAIEmbedder(
            config=OpenAIEmbedderConfig(
                api_key="dummy",
                base_url=litellm_url,
                embedding_model="text-embedding-004",
                embedding_dim=768,
            )
        ),
        cross_encoder=OpenAIRerankerClient(config=llm_config),
    )
    try:
        results = await graphiti.search(
            query=query,
            num_results=3,
            group_ids=["hackathon"],
        )
        facts = [edge.fact for edge in results if hasattr(edge, "fact")]
        return " | ".join(facts) if facts else "No results"
    finally:
        await graphiti.close()


def query_graphiti(query: str, neo4j_host: str) -> str:
    return asyncio.run(query_graphiti_async(query, neo4j_host))


async def query_cognee_async(query: str) -> str:
    import cognee  # type: ignore[import]
    from cognee import SearchType  # type: ignore[import]

    results = await cognee.search(
        query_text=query,
        query_type=SearchType.GRAPH_COMPLETION,
    )
    if not results:
        return "No results"
    # Results may be strings or dicts; extract text best-effort
    texts: list[str] = []
    for r in results:
        if isinstance(r, str):
            texts.append(r)
        elif isinstance(r, dict):
            texts.append(str(r.get("text", r.get("content", r))))
        else:
            texts.append(str(r))
    return " | ".join(texts) if texts else "No results"


def query_cognee(query: str, cognee_host: str) -> str:
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["LLM_MODEL"] = "claude-3-5-haiku-20241022"
    os.environ["LLM_API_KEY"] = anthropic_api_key
    os.environ["EMBEDDING_PROVIDER"] = "gemini"
    os.environ["EMBEDDING_MODEL"] = "gemini/text-embedding-004"
    os.environ["EMBEDDING_API_KEY"] = google_api_key
    if cognee_host != "localhost":
        os.environ["COGNEE_HOST"] = cognee_host
    return asyncio.run(query_cognee_async(query))


def query_system(system: str, query: str, host: str) -> str:
    if system == "mem0":
        return query_mem0(query, host)
    if system == "graphiti":
        return query_graphiti(query, host)
    if system == "cognee":
        return query_cognee(query, host)
    raise ValueError(f"Unknown system: {system!r}")


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_evaluation(
    system: str,
    test_cases_path: Path,
    host: str,
    runner_name: str,
    postgres_host: str,
    llm_client: openai.OpenAI,
) -> list[dict[str, Any]]:
    from scorers import score_answer  # type: ignore[import]

    with test_cases_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    print(f"\n{'='*60}")
    print(f"System: {system} | Runner: {runner_name} | Cases: {len(rows)}")
    print(f"{'='*60}")

    try:
        conn = get_db_connection(postgres_host)
        ensure_table(conn)
    except Exception as exc:
        print(f"Warning: Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        conn = None

    summary: list[dict[str, Any]] = []

    for row in rows:
        test_case_id = row.get("id", "unknown")
        query = row.get("query", "")
        expected = row.get("expected_answer", "")
        dimension = row.get("dimension", "recall")
        memory_type = row.get("memory_type", "")
        scoring_method = row.get("scoring_method", "exact_contains")

        if not query:
            continue

        print(f"\n[{test_case_id}] {query[:60]}")

        t0 = time.monotonic()
        try:
            actual = query_system(system, query, host)
        except Exception as exc:
            actual = f"ERROR: {exc}"
        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            score = score_answer(
                actual=actual,
                expected=expected,
                method=scoring_method,
                query=query,
                client=llm_client if scoring_method in ("llm_judge", "llm_judge_negation") else None,
            )
        except Exception as exc:
            print(f"  Scoring error: {exc}", file=sys.stderr)
            score = 0.0

        print(f"  Score: {score:.2f}  Latency: {latency_ms}ms")
        print(f"  Actual: {actual[:100]}")

        if conn is not None:
            try:
                save_result(
                    conn=conn,
                    runner_name=runner_name,
                    system_name=system,
                    test_case_id=test_case_id,
                    dimension=dimension,
                    memory_type=memory_type,
                    query=query,
                    expected=expected,
                    actual=actual,
                    score=score,
                    latency_ms=latency_ms,
                    scoring_method=scoring_method,
                )
            except Exception as exc:
                print(f"  DB save error: {exc}", file=sys.stderr)

        summary.append(
            {
                "test_case_id": test_case_id,
                "score": score,
                "latency_ms": latency_ms,
                "actual": actual,
            }
        )

    if conn is not None:
        conn.close()

    return summary


def print_summary_table(summary: list[dict[str, Any]], system: str) -> None:
    print(f"\n{'='*60}")
    print(f"Summary: {system}")
    print(f"{'='*60}")
    col_id = 20
    col_score = 7
    col_lat = 10
    col_actual = 30
    header = (
        f"{'test_case_id':<{col_id}} "
        f"{'score':>{col_score}} "
        f"{'latency_ms':>{col_lat}} "
        f"{'actual':<{col_actual}}"
    )
    print(header)
    print("-" * len(header))
    for row in summary:
        tid = str(row["test_case_id"])[:col_id]
        actual_trunc = str(row["actual"])[:col_actual]
        print(
            f"{tid:<{col_id}} "
            f"{row['score']:>{col_score}.2f} "
            f"{row['latency_ms']:>{col_lat}d} "
            f"{actual_trunc:<{col_actual}}"
        )
    if summary:
        avg_score = sum(r["score"] for r in summary) / len(summary)
        avg_lat = sum(r["latency_ms"] for r in summary) / len(summary)
        print("-" * len(header))
        print(
            f"{'AVERAGE':<{col_id}} "
            f"{avg_score:>{col_score}.2f} "
            f"{avg_lat:>{col_lat}.0f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluation harness runner.")
    parser.add_argument(
        "--system",
        required=True,
        choices=list(SYSTEMS) + ["all"],
        help="Memory system to evaluate (or 'all')",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "Service host for the memory system "
            "(overrides per-system env vars; default: localhost)"
        ),
    )
    parser.add_argument(
        "--runner-name",
        default=None,
        help="Identifier stored in DB (overrides RUNNER_NAME env var)",
    )
    parser.add_argument(
        "--test-cases",
        type=Path,
        default=DEFAULT_TEST_CASES,
        metavar="test_cases.csv",
        help=f"Path to test cases CSV (default: {DEFAULT_TEST_CASES})",
    )
    args = parser.parse_args()

    runner_name = args.runner_name or os.environ.get("RUNNER_NAME", "default")
    postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
    host = args.host or "localhost"

    litellm_url = os.environ.get("LITELLM_URL", "http://localhost:4000")
    llm_client = openai.OpenAI(base_url=litellm_url, api_key="dummy")

    if not args.test_cases.is_file():
        print(f"Error: test cases file not found: {args.test_cases}", file=sys.stderr)
        sys.exit(1)

    systems_to_run = list(SYSTEMS) if args.system == "all" else [args.system]

    for system in systems_to_run:
        summary = run_evaluation(
            system=system,
            test_cases_path=args.test_cases,
            host=host,
            runner_name=runner_name,
            postgres_host=postgres_host,
            llm_client=llm_client,
        )
        print_summary_table(summary, system)


if __name__ == "__main__":
    main()
