"""Scoring functions for memory system evaluation.

Uses LiteLLM proxy (OpenAI-compatible) for LLM judge scoring.
"""

from typing import Any

JUDGE_MODEL = "gemini-flash"


def exact_contains(actual: str, expected: str) -> float:
    """Return 1.0 if expected is a substring of actual (case-insensitive), 0.0 otherwise."""
    if not expected or not actual:
        return 0.0
    return 1.0 if expected.lower() in actual.lower() else 0.0


def llm_judge(query: str, expected: str, actual: str, client: Any) -> float:
    """Use LLM to score how well *actual* answers *query* given *expected*.

    Returns a float in [0.0, 1.0].
    """
    prompt = (
        f"Query: {query}\n"
        f"Expected: {expected}\n"
        f"Actual response: {actual}\n\n"
        "Score 0.0-1.0: how well does the actual response answer the query, "
        "given the expected answer? Return ONLY a number."
    )
    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        score = float(raw)
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.0


def llm_judge_negation(query: str, expected: str, actual: str, client: Any) -> float:
    """Score 1.0 if the system correctly says it doesn't know / has no relevant info.

    Score is HIGH when the system refuses rather than hallucinating an answer.
    The *expected* parameter is accepted for API consistency but not used in the prompt.
    """
    prompt = (
        f"Query: {query}\n"
        "Expected: system should say it doesn't know\n"
        f"Actual: {actual}\n\n"
        "Does the system correctly say it doesn't know or has no relevant info? "
        "Return ONLY 1.0 (correct refusal) or 0.0 (hallucinated an answer)."
    )
    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.choices[0].message.content.strip()
        score = float(raw)
        return max(0.0, min(1.0, score))
    except Exception:
        return 0.0


def score_answer(
    actual: str,
    expected: str,
    method: str,
    query: str = "",
    client: Any = None,
) -> float:
    """Dispatch to the appropriate scorer based on *method*.

    Supported methods:
        "exact_contains"     -> exact_contains
        "llm_judge"          -> llm_judge  (requires OpenAI-compatible client)
        "llm_judge_negation" -> llm_judge_negation  (requires OpenAI-compatible client)
    """
    if method == "exact_contains":
        return exact_contains(actual, expected)
    if method == "llm_judge":
        if client is None:
            raise ValueError("llm_judge scoring method requires an OpenAI-compatible client")
        return llm_judge(query, expected, actual, client)
    if method == "llm_judge_negation":
        if client is None:
            raise ValueError("llm_judge_negation scoring method requires an OpenAI-compatible client")
        return llm_judge_negation(query, expected, actual, client)
    raise ValueError(f"Unknown scoring method: {method!r}")
