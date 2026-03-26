#!/usr/bin/env python3
"""Run evaluation test cases against the live Graphiti knowledge graph.

Reads test cases from JSON, queries Graphiti (via graphiti-core + LiteLLM proxy),
scores answers, prints results, and optionally saves to PostgreSQL.

Usage:
    python eval-harness/run_graphiti.py
    python eval-harness/run_graphiti.py --test-cases shared-data/test-cases/test_cases.json
    python eval-harness/run_graphiti.py --host 192.168.0.44 --runner-name tomas
    python eval-harness/run_graphiti.py --no-db          # skip PostgreSQL persistence
    python eval-harness/run_graphiti.py --search-type facts   # search facts (default)
    python eval-harness/run_graphiti.py --search-type nodes   # search nodes instead
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_TEST_CASES = Path(__file__).parent.parent / "shared-data" / "test-cases" / "test_cases.json"
GROUP_ID = "hackathon"

# Map JSON scoring_method names to scorer dispatch keys
SCORING_METHOD_MAP = {
    "exact_contains": "exact",
    "llm_judge": "llm",
    "llm_judge_negation": "negation",
    # Also accept short names directly
    "exact": "exact",
    "llm": "llm",
    "negation": "negation",
}


# ---------------------------------------------------------------------------
# Graphiti client setup (reuses load_graphiti.py pattern: OpenAI client + LiteLLM)
# ---------------------------------------------------------------------------

def _patch_openai_client_for_litellm():
    """Patch graphiti's OpenAIClient for LiteLLM proxy compatibility.

    LiteLLM doesn't support the OpenAI Responses API. This redirects
    structured completions to chat.completions with JSON mode.
    """
    from graphiti_core.llm_client.openai_client import OpenAIClient

    class _UsageAdapter:
        def __init__(self, usage):
            self.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            self.output_tokens = getattr(usage, "completion_tokens", 0) or 0

    class _WrappedResponse:
        def __init__(self, chat_response):
            content = chat_response.choices[0].message.content if chat_response.choices else None
            self.output_text = content or "{}"
            self.usage = _UsageAdapter(chat_response.usage) if chat_response.usage else None

    async def _create_structured_completion(
        self, model, messages, temperature, max_tokens, response_model, **kwargs
    ):
        schema = response_model.model_json_schema()
        schema_instruction = (
            f"You MUST respond with a JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}\n"
            f"Return ONLY a valid JSON object, no markdown."
        )
        patched_messages = list(messages)
        if patched_messages and patched_messages[0].get("role") == "system":
            patched_messages[0] = {
                **patched_messages[0],
                "content": patched_messages[0]["content"] + "\n\n" + schema_instruction,
            }
        else:
            patched_messages.insert(0, {"role": "system", "content": schema_instruction})

        response = await self.client.chat.completions.create(
            model=model,
            messages=patched_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return _WrappedResponse(response)

    OpenAIClient._create_structured_completion = _create_structured_completion


async def create_graphiti_client(neo4j_host: str, neo4j_password: str, litellm_url: str):
    from graphiti_core import Graphiti
    from graphiti_core.llm_client.openai_client import OpenAIClient, LLMConfig
    from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
    from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

    _patch_openai_client_for_litellm()

    llm_config = LLMConfig(
        api_key="dummy",
        base_url=litellm_url,
        model="gemini-flash",
        small_model="gemini-flash",
    )

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
    return graphiti


async def query_graphiti(graphiti, query: str, search_type: str, num_results: int = 10) -> str:
    """Query Graphiti and return formatted results."""
    if search_type == "nodes":
        results = await graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=[GROUP_ID],
            search_type="node",
        )
        texts = []
        for node in results:
            name = getattr(node, "name", "")
            summary = getattr(node, "summary", "")
            texts.append(f"{name}: {summary}" if summary else name)
        return " | ".join(texts) if texts else "No results"
    else:
        # Default: search facts
        results = await graphiti.search(
            query=query,
            num_results=num_results,
            group_ids=[GROUP_ID],
        )
        facts = [edge.fact for edge in results if hasattr(edge, "fact")]
        return " | ".join(facts) if facts else "No results"


# ---------------------------------------------------------------------------
# Scoring (inline — avoids anthropic SDK dependency, uses httpx)
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, litellm_url: str) -> str:
    """Call LLM via LiteLLM proxy (OpenAI-compatible endpoint)."""
    import httpx

    resp = httpx.post(
        f"{litellm_url}/v1/chat/completions",
        headers={"content-type": "application/json"},
        json={
            "model": "gemini-flash",
            "max_tokens": 50000,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    if content is None:
        raise ValueError("LLM returned null content (max_tokens too low or reasoning consumed all tokens)")
    return content.strip()


def score_exact(actual: str, expected: str) -> float:
    if not expected or not actual:
        return 0.0
    return 1.0 if expected.lower() in actual.lower() else 0.0


def score_llm(query: str, expected: str, actual: str, litellm_url: str) -> float:
    prompt = (
        f"Query: {query}\n"
        f"Expected: {expected}\n"
        f"Actual response: {actual}\n\n"
        "Score 0.0-1.0: how well does the actual response answer the query, "
        "given the expected answer? Return ONLY a number."
    )
    try:
        raw = _call_llm(prompt, litellm_url)
        # Extract first float from response
        import re
        match = re.search(r"[0-9]+\.?[0-9]*", raw)
        if match:
            return max(0.0, min(1.0, float(match.group())))
        return 0.0
    except Exception as exc:
        print(f"  [score_llm error: {exc}]", file=sys.stderr)
        return 0.0


def score_negation(query: str, actual: str, litellm_url: str) -> float:
    prompt = (
        f"Query: {query}\n"
        "Expected: system should say it doesn't know\n"
        f"Actual: {actual}\n\n"
        "Does the system correctly say it doesn't know or has no relevant info? "
        "Return ONLY 1.0 (correct refusal) or 0.0 (hallucinated an answer)."
    )
    try:
        raw = _call_llm(prompt, litellm_url)
        import re
        match = re.search(r"[0-9]+\.?[0-9]*", raw)
        if match:
            return max(0.0, min(1.0, float(match.group())))
        return 0.0
    except Exception as exc:
        print(f"  [score_negation error: {exc}]", file=sys.stderr)
        return 0.0


def score_answer(actual: str, expected: str, method: str, query: str, litellm_url: str) -> float:
    m = SCORING_METHOD_MAP.get(method, method)
    if m == "exact":
        return score_exact(actual, expected)
    if m == "llm":
        return score_llm(query, expected, actual, litellm_url)
    if m == "negation":
        return score_negation(query, actual, litellm_url)
    raise ValueError(f"Unknown scoring method: {method!r}")


# ---------------------------------------------------------------------------
# DB helpers (optional — gracefully skips if unavailable)
# ---------------------------------------------------------------------------

def get_db_connection(postgres_host: str):
    import psycopg2
    return psycopg2.connect(
        host=postgres_host,
        port=5432,
        dbname="eval_results",
        user="postgres",
        password="hackathon2025",
    )


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eval_runs (
                id            SERIAL PRIMARY KEY,
                runner_name   TEXT,
                system_name   TEXT,
                test_case_id  TEXT,
                dimension     TEXT,
                query         TEXT,
                expected      TEXT,
                actual        TEXT,
                score         FLOAT,
                latency_ms    INT,
                scoring_method TEXT,
                run_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
    conn.commit()


def save_result(conn, runner_name: str, test_case_id: str, dimension: str,
                query: str, expected: str, actual: str, score: float,
                latency_ms: int, scoring_method: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO eval_runs
                (runner_name, system_name, test_case_id, dimension,
                 query, expected, actual, score, latency_ms, scoring_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (runner_name, "graphiti", test_case_id, dimension,
              query, expected, actual, score, latency_ms, scoring_method))
    conn.commit()


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def run_evaluation(args) -> list[dict[str, Any]]:
    test_cases: list[dict] = json.loads(args.test_cases.read_text(encoding="utf-8"))

    host = args.host or os.environ.get("HOST_IP", "localhost")
    neo4j_host = os.environ.get("NEO4J_HOST", host)
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "hackathon2025")
    litellm_url = os.environ.get("LITELLM_URL", f"http://{host}:4000")
    runner_name = args.runner_name or os.environ.get("RUNNER_NAME", "default")
    postgres_host = os.environ.get("POSTGRES_HOST", host)

    # Connect to Graphiti
    print(f"Connecting to Graphiti (Neo4j bolt://{neo4j_host}:7687, LiteLLM {litellm_url}) ...")
    graphiti = await create_graphiti_client(neo4j_host, neo4j_password, litellm_url)

    # Connect to PostgreSQL (optional)
    conn = None
    if not args.no_db:
        try:
            conn = get_db_connection(postgres_host)
            ensure_table(conn)
            print(f"PostgreSQL connected ({postgres_host})")
        except Exception as exc:
            print(f"Warning: PostgreSQL unavailable ({exc}) — results won't be persisted", file=sys.stderr)

    print(f"\n{'='*72}")
    print(f"  Graphiti Eval | Runner: {runner_name} | Cases: {len(test_cases)} | Search: {args.search_type}")
    print(f"{'='*72}")

    summary: list[dict[str, Any]] = []

    for tc in test_cases:
        tc_id = tc["id"]
        query = tc["query"]
        expected = tc.get("expected_answer", tc.get("expected", ""))
        dimension = tc.get("dimension", "recall")
        scoring_method = tc.get("scoring_method", "exact_contains")

        print(f"\n[{tc_id}] {query}")

        t0 = time.monotonic()
        try:
            actual = await query_graphiti(graphiti, query, args.search_type, args.num_results)
        except Exception as exc:
            actual = f"ERROR: {exc}"
        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            score = score_answer(actual, expected, scoring_method, query, litellm_url)
        except Exception as exc:
            print(f"  Scoring error: {exc}", file=sys.stderr)
            score = 0.0

        print(f"  Expected: {expected[:80]}")
        print(f"  Actual:   {actual[:120]}")
        print(f"  Score: {score:.2f}  Latency: {latency_ms}ms")

        if conn is not None:
            try:
                save_result(conn, runner_name, tc_id, dimension,
                            query, expected, actual, score, latency_ms, scoring_method)
            except Exception as exc:
                print(f"  DB save error: {exc}", file=sys.stderr)

        summary.append({
            "test_case_id": tc_id,
            "dimension": dimension,
            "query": query,
            "expected": expected,
            "actual": actual,
            "score": score,
            "latency_ms": latency_ms,
        })

    await graphiti.close()
    if conn is not None:
        conn.close()

    return summary


def print_summary(summary: list[dict[str, Any]]) -> None:
    if not summary:
        print("\nNo results.")
        return

    print(f"\n{'='*72}")
    print("  RESULTS SUMMARY")
    print(f"{'='*72}")
    print(f"{'ID':<8} {'Dim':<16} {'Score':>6} {'Latency':>8}  {'Actual':<40}")
    print("-" * 82)

    for r in summary:
        print(
            f"{r['test_case_id']:<8} "
            f"{r['dimension']:<16} "
            f"{r['score']:>6.2f} "
            f"{r['latency_ms']:>7d}ms"
            f"  {r['actual']:<40}"
        )

    avg_score = sum(r["score"] for r in summary) / len(summary)
    avg_lat = sum(r["latency_ms"] for r in summary) / len(summary)
    print("-" * 82)
    print(f"{'AVG':<8} {'':<16} {avg_score:>6.2f} {avg_lat:>7.0f}ms")

    # Per-dimension breakdown
    dims: dict[str, list[float]] = {}
    for r in summary:
        dims.setdefault(r["dimension"], []).append(r["score"])

    print(f"\n{'Dimension':<20} {'Avg Score':>10} {'Count':>6}")
    print("-" * 38)
    for dim, scores in sorted(dims.items()):
        print(f"{dim:<20} {sum(scores)/len(scores):>10.2f} {len(scores):>6}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run eval test cases against Graphiti.")
    parser.add_argument(
        "--test-cases", type=Path, default=DEFAULT_TEST_CASES,
        help=f"Path to test cases JSON (default: {DEFAULT_TEST_CASES})",
    )
    parser.add_argument("--host", default=None, help="Host IP for Neo4j/LiteLLM (default: from .env or localhost)")
    parser.add_argument("--runner-name", default=None, help="Runner identifier for DB")
    parser.add_argument("--no-db", action="store_true", help="Skip PostgreSQL persistence")
    parser.add_argument(
        "--search-type", choices=["facts", "nodes"], default="facts",
        help="Graphiti search type (default: facts)",
    )
    parser.add_argument("--num-results", type=int, default=10, help="Number of search results (default: 10)")
    parser.add_argument("--json-output", type=Path, default=None, help="Save results as JSON")
    parser.add_argument("--html-output", type=Path, default=None, help="Generate HTML report")
    args = parser.parse_args()

    if not args.test_cases.is_file():
        print(f"Error: test cases not found: {args.test_cases}", file=sys.stderr)
        sys.exit(1)

    summary = asyncio.run(run_evaluation(args))
    print_summary(summary)

    if args.json_output:
        args.json_output.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON results saved to {args.json_output}")

    if args.html_output:
        html = generate_html_report(summary)
        args.html_output.write_text(html, encoding="utf-8")
        print(f"HTML report saved to {args.html_output}")


# ---------------------------------------------------------------------------
# HTML report generation
# ---------------------------------------------------------------------------

def score_color(score: float) -> str:
    r = int(255 * (1 - score))
    g = int(200 * score)
    return f"rgb({r},{g},80)"


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate_html_report(summary: list[dict[str, Any]]) -> str:
    from datetime import datetime

    # Build dimension pivot
    dims: dict[str, list[dict]] = {}
    for r in summary:
        dims.setdefault(r["dimension"], []).append(r)

    dim_names = sorted(dims.keys())
    dim_avgs = {d: sum(r["score"] for r in rows) / len(rows) for d, rows in dims.items()}
    overall_avg = sum(r["score"] for r in summary) / len(summary) if summary else 0
    overall_lat = sum(r["latency_ms"] for r in summary) / len(summary) if summary else 0

    # Summary table
    summary_rows_html = ""
    for dim in dim_names:
        avg = dim_avgs[dim]
        bg = score_color(avg)
        cnt = len(dims[dim])
        summary_rows_html += (
            f'<tr><td>{_esc(dim)}</td><td>{cnt}</td>'
            f'<td style="background:{bg};font-weight:bold;text-align:center">{avg:.3f}</td></tr>\n'
        )
    summary_rows_html += (
        f'<tr style="border-top:2px solid #333"><td><strong>OVERALL</strong></td>'
        f'<td>{len(summary)}</td>'
        f'<td style="background:{score_color(overall_avg)};font-weight:bold;text-align:center">{overall_avg:.3f}</td></tr>'
    )

    # Detail table
    detail_rows_html = ""
    for r in summary:
        sc = r["score"]
        bg = score_color(sc)
        detail_rows_html += (
            f'<tr>'
            f'<td>{_esc(r["test_case_id"])}</td>'
            f'<td>{_esc(r["dimension"])}</td>'
            f'<td class="wrap">{_esc(r.get("query", ""))}</td>'
            f'<td class="wrap">{_esc(r.get("expected", ""))}</td>'
            f'<td class="wrap">{_esc(r.get("actual", ""))}</td>'
            f'<td style="background:{bg};text-align:center;font-weight:bold">{sc:.2f}</td>'
            f'<td style="text-align:right">{r["latency_ms"]}ms</td>'
            f'</tr>\n'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Graphiti Eval Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; color: #222; max-width: 1400px; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: .5rem; }}
  h2 {{ color: #0f3460; margin-top: 2rem; }}
  .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .stats {{ display: flex; gap: 2rem; margin: 1rem 0; }}
  .stat-card {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 1rem 1.5rem; text-align: center; }}
  .stat-card .value {{ font-size: 2rem; font-weight: bold; }}
  .stat-card .label {{ font-size: 0.85rem; color: #666; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; font-size: 0.85rem; }}
  th, td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }}
  th {{ background: #e9ecef; font-weight: 600; position: sticky; top: 0; }}
  tr:hover {{ background: #f8f9fa; }}
  td.wrap {{ max-width: 400px; word-break: break-word; white-space: normal; }}
  .pass {{ color: #155724; }} .fail {{ color: #721c24; }}
</style>
</head>
<body>
<h1>Graphiti Memory Evaluation Report</h1>
<p class="meta">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} &middot; System: graphiti &middot; {len(summary)} test cases</p>

<div class="stats">
  <div class="stat-card">
    <div class="value" style="color:{score_color(overall_avg)}">{overall_avg:.1%}</div>
    <div class="label">Overall Score</div>
  </div>
  <div class="stat-card">
    <div class="value">{overall_lat:.0f}ms</div>
    <div class="label">Avg Latency</div>
  </div>
  <div class="stat-card">
    <div class="value">{sum(1 for r in summary if r['score'] >= 0.5)}/{len(summary)}</div>
    <div class="label">Passed (&ge;0.5)</div>
  </div>
</div>

<h2>Score by Dimension</h2>
<table>
  <thead><tr><th>Dimension</th><th>Cases</th><th>Avg Score</th></tr></thead>
  <tbody>{summary_rows_html}</tbody>
</table>

<h2>Detailed Results</h2>
<table>
  <thead><tr><th>ID</th><th>Dimension</th><th>Query</th><th>Expected</th><th>Actual</th><th>Score</th><th>Latency</th></tr></thead>
  <tbody>{detail_rows_html}</tbody>
</table>
</body>
</html>"""


if __name__ == "__main__":
    main()
