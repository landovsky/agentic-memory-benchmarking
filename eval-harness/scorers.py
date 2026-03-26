"""Scoring functions for memory system evaluation."""

from typing import Any


def exact_contains(actual: str, expected: str) -> float:
    """Return 1.0 if expected is a substring of actual (case-insensitive), 0.0 otherwise."""
    if not expected or not actual:
        return 0.0
    return 1.0 if expected.lower() in actual.lower() else 0.0


def llm_judge(query: str, expected: str, actual: str, client: Any) -> float:
    """Use Claude to score how well *actual* answers *query* given *expected*.

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
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
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
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
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
        "exact"     -> exact_contains
        "llm"       -> llm_judge  (requires client)
        "negation"  -> llm_judge_negation  (requires client)
    """
    if method == "exact":
        return exact_contains(actual, expected)
    if method == "llm":
        if client is None:
            raise ValueError("llm scoring method requires an Anthropic client")
        return llm_judge(query, expected, actual, client)
    if method == "negation":
        if client is None:
            raise ValueError("negation scoring method requires an Anthropic client")
        return llm_judge_negation(query, expected, actual, client)
    raise ValueError(f"Unknown scoring method: {method!r}")
