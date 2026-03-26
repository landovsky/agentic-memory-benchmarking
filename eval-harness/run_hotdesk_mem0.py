#!/usr/bin/env python3
"""Evaluate hotdesk test cases against Mem0 (Qdrant/openmemory collection).

Queries Mem0 via LiteLLM proxy for embeddings + Qdrant for vector search,
scores results, and outputs JSON report.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:4000")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "openmemory"
EMBED_MODEL = "text-embedding-004"
TOP_K = 5

TEST_CASES_PATH = Path(__file__).parent.parent / "shared-data" / "hotdesk_test_cases_draft.json"


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------
def embed_query(text: str) -> list[float]:
    """Get embedding via LiteLLM proxy (OpenAI-compatible endpoint)."""
    resp = requests.post(
        f"{LITELLM_URL}/embeddings",
        json={"model": EMBED_MODEL, "input": text},
        headers={"Authorization": "Bearer dummy"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# Qdrant search
# ---------------------------------------------------------------------------
def search_mem0(query: str) -> str:
    """Search openmemory collection in Qdrant using query embedding."""
    vector = embed_query(query)
    resp = requests.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
        json={
            "vector": vector,
            "limit": TOP_K,
            "with_payload": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("result", [])
    if not results:
        return "No results"
    memories = [r["payload"].get("data", "") for r in results if r["payload"].get("data")]
    return " | ".join(memories) if memories else "No results"


# ---------------------------------------------------------------------------
# Scoring (inline — mirrors eval-harness/scorers.py)
# ---------------------------------------------------------------------------
def llm_call(prompt: str, retries: int = 5) -> str:
    """Call LLM via LiteLLM proxy (OpenAI-compatible)."""
    for attempt in range(retries + 1):
        resp = requests.post(
            f"{LITELLM_URL}/chat/completions",
            json={
                "model": "gemini-flash",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "temperature": 0.5,
            },
            headers={"Authorization": "Bearer dummy"},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content")
        if content is not None:
            return content.strip()
    raise ValueError("LLM returned None content after retries")


def exact_contains(actual: str, expected: str) -> float:
    if not expected or not actual:
        return 0.0
    return 1.0 if expected.lower() in actual.lower() else 0.0


def llm_judge(query: str, expected: str, actual: str) -> float:
    prompt = (
        f"Query: {query}\n"
        f"Expected: {expected}\n"
        f"Actual response: {actual}\n\n"
        "Score 0.0-1.0: how well does the actual response answer the query, "
        "given the expected answer? Return ONLY a number."
    )
    try:
        raw = llm_call(prompt)
        score = float(raw)
        return max(0.0, min(1.0, score))
    except Exception as e:
        print(f"    llm_judge error: {e} (raw={raw!r})", file=sys.stderr)
        return 0.0


def llm_judge_negation(query: str, actual: str) -> float:
    prompt = (
        f"Query: {query}\n"
        "Expected: system should say it doesn't know\n"
        f"Actual: {actual}\n\n"
        "Does the system correctly say it doesn't know or has no relevant info? "
        "Return ONLY 1.0 (correct refusal) or 0.0 (hallucinated an answer)."
    )
    try:
        raw = llm_call(prompt)
        score = float(raw)
        return max(0.0, min(1.0, score))
    except Exception as e:
        print(f"    llm_judge_negation error: {e} (raw={raw!r})", file=sys.stderr)
        return 0.0


def score_answer(tc: dict, actual: str) -> float:
    method = tc["scoring_method"]
    if method == "exact_contains":
        return exact_contains(actual, tc["expected_answer"])
    elif method == "llm_judge":
        return llm_judge(tc["query"], tc["expected_answer"], actual)
    elif method == "llm_judge_negation":
        return llm_judge_negation(tc["query"], actual)
    else:
        raise ValueError(f"Unknown scoring method: {method}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Check LiteLLM proxy is up
    try:
        requests.get(f"{LITELLM_URL}/health", timeout=5)
    except Exception:
        print(f"ERROR: LiteLLM proxy not reachable at {LITELLM_URL}", file=sys.stderr)
        sys.exit(1)

    test_cases = json.loads(TEST_CASES_PATH.read_text())
    results = []

    print(f"\n{'='*70}")
    print(f"Mem0 Hotdesk Evaluation — {len(test_cases)} test cases")
    print(f"{'='*70}")

    for tc in test_cases:
        tc_id = tc.get("id", "?")
        query = tc["query"]
        dimension = tc.get("dimension", "?")
        print(f"\n[{tc_id}] ({dimension}) {query[:65]}")

        t0 = time.monotonic()
        try:
            actual = search_mem0(query)
        except Exception as exc:
            actual = f"ERROR: {exc}"
        latency_ms = int((time.monotonic() - t0) * 1000)

        try:
            score = score_answer(tc, actual)
        except Exception as exc:
            print(f"  Scoring error: {exc}", file=sys.stderr)
            score = 0.0

        print(f"  Score: {score:.2f}  Latency: {latency_ms}ms")
        print(f"  Actual: {actual[:120]}")

        results.append({
            "id": tc_id,
            "dimension": dimension,
            "memory_type": tc.get("memory_type", "?"),
            "query": query,
            "expected": tc.get("expected_answer", ""),
            "actual": actual,
            "score": score,
            "latency_ms": latency_ms,
            "scoring_method": tc.get("scoring_method", ""),
        })

    # Summary
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    print(f"\n{'='*70}")
    print(f"Average score: {avg_score:.2f}")
    print(f"{'='*70}")

    # Write JSON results
    out_path = Path(__file__).parent.parent / "hotdesk_mem0_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
