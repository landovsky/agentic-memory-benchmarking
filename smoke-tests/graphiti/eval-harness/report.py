#!/usr/bin/env python3
"""Generate HTML report from eval_results PostgreSQL table.

Usage:
    python report.py [--host localhost] [--output report.html]
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def fetch_data(conn: Any) -> tuple[list[dict], list[dict]]:
    """Return (summary_rows, detail_rows) from the database."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # Summary: avg score per system × dimension
        cur.execute(
            """
            SELECT
                system_name,
                dimension,
                COUNT(*)        AS total,
                ROUND(AVG(score)::numeric, 3) AS avg_score
            FROM eval_runs
            GROUP BY system_name, dimension
            ORDER BY system_name, dimension
            """
        )
        summary_rows = [dict(r) for r in cur.fetchall()]

        # Detail: all individual runs
        cur.execute(
            """
            SELECT
                id,
                run_timestamp,
                runner,
                system_name,
                test_case_id,
                dimension,
                query,
                expected_answer,
                actual_answer,
                score,
                latency_ms,
                notes
            FROM eval_runs
            ORDER BY system_name, test_case_id, run_timestamp
            """
        )
        detail_rows = [dict(r) for r in cur.fetchall()]

    return summary_rows, detail_rows


def build_pivot(summary_rows: list[dict]) -> tuple[list[str], list[str], dict]:
    """Build a system × dimension pivot table.

    Returns (systems, dimensions, pivot) where pivot[(system, dim)] = avg_score.
    """
    systems: list[str] = sorted({r["system_name"] for r in summary_rows})
    dimensions: list[str] = sorted({r["dimension"] for r in summary_rows})
    pivot: dict[tuple[str, str], float] = {}
    for r in summary_rows:
        pivot[(r["system_name"], r["dimension"])] = float(r["avg_score"])
    return systems, dimensions, pivot


def best_scores_per_case(detail_rows: list[dict]) -> dict[str, float]:
    """Return the highest score for each test_case_id across all systems."""
    best: dict[str, float] = {}
    for r in detail_rows:
        tid = r["test_case_id"]
        score = float(r["score"] or 0)
        if tid not in best or score > best[tid]:
            best[tid] = score
    return best


def score_color(score: float) -> str:
    """Map a 0-1 score to a background colour (green good, red bad)."""
    r = int(255 * (1 - score))
    g = int(200 * score)
    return f"rgb({r},{g},80)"


def generate_html(summary_rows: list[dict], detail_rows: list[dict]) -> str:
    systems, dimensions, pivot = build_pivot(summary_rows)
    best = best_scores_per_case(detail_rows)

    # ------------------------------------------------------------------
    # Summary table
    # ------------------------------------------------------------------
    summary_header_cells = "".join(f"<th>{d}</th>" for d in dimensions)
    summary_body = ""
    for system in systems:
        cells = ""
        for dim in dimensions:
            score = pivot.get((system, dim))
            if score is not None:
                bg = score_color(score)
                cells += f'<td style="background:{bg}">{score:.3f}</td>'
            else:
                cells += "<td>—</td>"
        summary_body += f"<tr><td><strong>{system}</strong></td>{cells}</tr>\n"

    summary_table = f"""
<table>
  <thead>
    <tr>
      <th>System</th>
      {summary_header_cells}
    </tr>
  </thead>
  <tbody>
    {summary_body}
  </tbody>
</table>"""

    # ------------------------------------------------------------------
    # Detail table
    # ------------------------------------------------------------------
    detail_rows_html = ""
    for r in detail_rows:
        score = float(r.get("score") or 0)
        tid = r.get("test_case_id", "")
        is_best = abs(score - best.get(tid, -1)) < 1e-9
        bg = "background:#d4edda;" if is_best else ""
        query_trunc = str(r.get("query", ""))[:120]
        actual_trunc = str(r.get("actual_answer", ""))[:200]
        expected_trunc = str(r.get("expected_answer", ""))[:120]
        run_at = str(r.get("run_timestamp", ""))[:19]
        detail_rows_html += (
            f'<tr style="{bg}">'
            f"<td>{r.get('id')}</td>"
            f"<td>{run_at}</td>"
            f"<td>{r.get('runner', '')}</td>"
            f"<td>{r.get('system_name', '')}</td>"
            f"<td>{tid}</td>"
            f"<td>{r.get('dimension', '')}</td>"
            f"<td>{query_trunc}</td>"
            f"<td>{expected_trunc}</td>"
            f"<td>{actual_trunc}</td>"
            f"<td>{score:.3f}</td>"
            f"<td>{r.get('latency_ms', '')}</td>"
            f"<td>{r.get('notes', '')}</td>"
            "</tr>\n"
        )

    detail_table = f"""
<table>
  <thead>
    <tr>
      <th>ID</th><th>Run at</th><th>Runner</th><th>System</th>
      <th>Test case</th><th>Dimension</th><th>Query</th>
      <th>Expected</th><th>Actual</th><th>Score</th>
      <th>Latency ms</th><th>Method</th>
    </tr>
  </thead>
  <tbody>
    {detail_rows_html}
  </tbody>
</table>"""

    # ------------------------------------------------------------------
    # Full HTML document
    # ------------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Memory Benchmarking — Eval Results</title>
  <style>
    body {{
      font-family: sans-serif;
      margin: 2rem;
      color: #222;
    }}
    h1 {{ color: #333; }}
    h2 {{ color: #555; margin-top: 2rem; }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin-bottom: 1.5rem;
      font-size: 0.85rem;
    }}
    th, td {{
      border: 1px solid #ccc;
      padding: 6px 10px;
      text-align: left;
      word-break: break-word;
    }}
    th {{
      background: #f0f0f0;
      font-weight: bold;
    }}
    tr:hover {{ background: #fafafa; }}
    .best {{ background: #d4edda !important; }}
  </style>
</head>
<body>
  <h1>Memory Benchmarking — Evaluation Report</h1>
  <p>Generated: {__import__('datetime').datetime.now().isoformat(timespec='seconds')}</p>

  <h2>Summary — Average Score by System &times; Dimension</h2>
  <p>Green cells = higher score. Highlighted rows in detail table = best score for that test case.</p>
  {summary_table}

  <h2>Detailed Results</h2>
  {detail_table}
</body>
</html>"""

    return html


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate HTML report from eval_results PostgreSQL table."
    )
    parser.add_argument(
        "--host",
        default=None,
        help="PostgreSQL host (overrides POSTGRES_HOST env var; default: localhost)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("report.html"),
        help="Output HTML file (default: report.html)",
    )
    args = parser.parse_args()

    postgres_host = args.host or os.environ.get("POSTGRES_HOST", "localhost")

    print(f"Connecting to PostgreSQL at {postgres_host} ...")
    try:
        conn = psycopg2.connect(
            host=postgres_host,
            port=5432,
            dbname="eval_results",
            user="hackathon",
            password="hackathon2025",
        )
    except Exception as exc:
        print(f"Error: Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        summary_rows, detail_rows = fetch_data(conn)
    finally:
        conn.close()

    print(f"Fetched {len(summary_rows)} summary row(s) and {len(detail_rows)} detail row(s).")

    if not summary_rows and not detail_rows:
        print("No data found in eval_runs table. Is the database populated?", file=sys.stderr)

    html = generate_html(summary_rows, detail_rows)
    args.output.write_text(html, encoding="utf-8")
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
