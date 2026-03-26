#!/usr/bin/env python3
"""Generate benchmark test cases from session summaries.

Takes topic summaries produced by session_summarizer.py and generates
test cases per benchmark dimension.

Usage:
    python test_case_generator.py --input summaries.json --output test_cases_draft.json
    python test_case_generator.py --input summaries.json --output draft.json \
        --dimensions "temporal:4,hallucination:3,proactive:3,recall:4"
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-haiku-4-5-20251001"
RATE_LIMIT_SLEEP = 0.5

# Existing test cases as few-shot examples, grouped by dimension
EXAMPLES = {
    "recall": {
        "id": "TC-001",
        "dimension": "recall",
        "memory_type": "preference",
        "project_scope": "global",
        "setup_memory": "User prefers Tailwind over Bootstrap",
        "query": "What CSS framework do I prefer?",
        "expected_answer": "Tailwind",
        "scoring_method": "exact_contains",
        "notes": "Basic preference recall",
    },
    "temporal": {
        "id": "TC-003",
        "dimension": "temporal",
        "memory_type": "semantic",
        "project_scope": "hristehrou",
        "setup_memory": "January: HH uses Bootstrap. March: Switched to Tailwind.",
        "query": "What CSS framework does Hriste Hrou currently use?",
        "expected_answer": "Tailwind (switched from Bootstrap)",
        "scoring_method": "llm_judge",
        "notes": "Temporal - recognizing an update",
    },
    "hallucination": {
        "id": "TC-005",
        "dimension": "hallucination",
        "memory_type": "_",
        "project_scope": "global",
        "setup_memory": "(no memory about React)",
        "query": "What React version do I use?",
        "expected_answer": "I don't know / no info available",
        "scoring_method": "llm_judge_negation",
        "notes": "Anti-hallucination - system must NOT answer",
    },
    "proactive": {
        "id": "TC-006",
        "dimension": "proactive",
        "memory_type": "episodic",
        "project_scope": "medicmee",
        "setup_memory": "March 3: Fixed PostgreSQL timeout by increasing pool size to 25",
        "query": "I'm having DB connection timeout issues in MedicMee",
        "expected_answer": "Should proactively mention the previous fix (pool size 25)",
        "scoring_method": "llm_judge",
        "notes": "Proactive use of episodic memory",
    },
    "scale": {
        "id": "TC-008",
        "dimension": "scale",
        "memory_type": "semantic",
        "project_scope": "global",
        "setup_memory": "(100 memories loaded)",
        "query": "What is the deployment process for MedicMee?",
        "expected_answer": "Dokku on VPS",
        "scoring_method": "exact_contains",
        "notes": "Baseline - 100 records",
    },
    "type_distinction": {
        "id": "TC-010",
        "dimension": "type_distinction",
        "memory_type": "preference+episodic",
        "project_scope": "global",
        "setup_memory": "Preference: I like using Tailwind. Episodic: Yesterday I had to use Bootstrap for a legacy client.",
        "query": "What CSS framework do I prefer?",
        "expected_answer": "Tailwind (even though yesterday he used Bootstrap - that was an exception)",
        "scoring_method": "llm_judge",
        "notes": "Distinguishing preference vs. episodic",
    },
}

GENERATION_PROMPT = """\
You are generating benchmark test cases for an AI memory system evaluation.

Given the extracted topics from real coding sessions, generate test cases \
for the dimension: {dimension}.

Each test case must follow this exact JSON schema:
{{
  "id": "TC-{start_id:03d}",
  "dimension": "{dimension}",
  "memory_type": "preference|episodic|semantic|goal",
  "project_scope": "hotdesk",
  "setup_memory": "What memory should exist in the system for this test",
  "query": "The question to ask the system (in English)",
  "expected_answer": "The expected response (in English)",
  "scoring_method": "exact_contains|llm_judge|llm_judge_negation",
  "notes": "Brief explanation of what this tests"
}}

## Dimension: {dimension}
{dimension_guidance}

## Example test case for this dimension:
{example}

## Available topics from real sessions:
{topics}

Generate exactly {count} test cases. Use the real topics above as the basis \
for each test case. Test cases must be grounded in the actual session data - \
do not invent facts that aren't in the topics.

{special_instructions}

Return a JSON array only (no other text)."""

DIMENSION_GUIDANCE = {
    "recall": (
        "Test whether the system can retrieve a known fact when asked directly. "
        "Use exact_contains for single-word/phrase answers, llm_judge for nuanced ones."
    ),
    "temporal": (
        "Test whether the system recognizes that a fact was updated over time. "
        "The setup_memory must describe TWO states: the old one and the new one, "
        "with timestamps. The query asks about the CURRENT state. "
        "Use llm_judge scoring."
    ),
    "hallucination": (
        "Test whether the system correctly refuses to answer when it has NO relevant "
        "memory. The setup_memory should be '(no memory about X)' where X is "
        "something plausible but not in the data. Use llm_judge_negation scoring. "
        "The expected_answer should be a refusal like 'I don't know / no info'."
    ),
    "proactive": (
        "Test whether the system proactively surfaces relevant past context when "
        "the user describes a similar problem. The query should describe a PROBLEM "
        "(not ask a direct question). The system should surface the past solution. "
        "Use llm_judge scoring."
    ),
    "scale": (
        "Test retrieval quality at different memory counts. Reuse a recall-type "
        "query but note in setup_memory the expected count: '(N memories loaded)'. "
        "Use exact_contains scoring."
    ),
    "type_distinction": (
        "Test whether the system distinguishes between different memory types. "
        "The setup_memory should contain a PREFERENCE and an EPISODIC fact that "
        "could be confused. The query should target the preference, and the system "
        "should recognize the episodic fact as an exception. "
        "Use llm_judge scoring. Set memory_type to 'preference+episodic'."
    ),
}

SPECIAL_INSTRUCTIONS = {
    "hallucination": (
        "IMPORTANT: For hallucination tests, the topics list shows what IS known. "
        "You must generate questions about things that are plausible for the hotdesk "
        "project but are NOT mentioned in any topic. For example, ask about features, "
        "tools, or configurations that don't exist in the project."
    ),
    "scale": (
        "Generate test cases that reuse a clear, unambiguous fact from the topics. "
        "Create one case at 100 memories, one at 1000. The query and expected_answer "
        "should be identical; only setup_memory changes."
    ),
}


def parse_dimensions(dim_string: str) -> dict[str, int]:
    """Parse 'temporal:4,hallucination:3' into a dict."""
    result: dict[str, int] = {}
    for pair in dim_string.split(","):
        pair = pair.strip()
        if ":" in pair:
            dim, count = pair.split(":", 1)
            result[dim.strip()] = int(count.strip())
        else:
            result[pair.strip()] = 3  # default count
    return result


def collect_topics(summaries: list[dict[str, Any]]) -> str:
    """Collect all topics into a formatted string for the prompt."""
    lines: list[str] = []
    for summary in summaries:
        for topic in summary.get("topics", []):
            fact = topic.get("fact", "")
            mtype = topic.get("memory_type", "unknown")
            dims = ", ".join(topic.get("dimension_candidates", []))
            confidence = topic.get("confidence", "?")
            lines.append(f"- [{mtype}] (conf={confidence}, dims={dims}) {fact}")
    return "\n".join(lines) if lines else "(no topics found)"


def generate_for_dimension(
    dimension: str,
    count: int,
    start_id: int,
    topics_text: str,
    client: anthropic.Anthropic,
) -> list[dict[str, Any]]:
    """Generate test cases for a single dimension."""
    example = EXAMPLES.get(dimension, EXAMPLES["recall"])
    example_text = json.dumps(example, indent=2, ensure_ascii=False)
    guidance = DIMENSION_GUIDANCE.get(dimension, "")
    special = SPECIAL_INSTRUCTIONS.get(dimension, "")

    prompt = GENERATION_PROMPT.format(
        dimension=dimension,
        dimension_guidance=guidance,
        example=example_text,
        topics=topics_text,
        count=count,
        start_id=start_id,
        special_instructions=special,
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
    except Exception as exc:
        print(f"    API error: {exc}", file=sys.stderr)
        return []

    # Strip markdown code fences
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        cases = json.loads(raw)
        if not isinstance(cases, list):
            print("    Unexpected response shape (not a list)", file=sys.stderr)
            return []
    except json.JSONDecodeError as exc:
        print(f"    JSON parse error: {exc}", file=sys.stderr)
        print(f"    Raw response snippet: {raw[:300]}", file=sys.stderr)
        return []

    # Reassign IDs sequentially
    for i, case in enumerate(cases):
        case["id"] = f"TC-{start_id + i:03d}"

    return cases


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate benchmark test cases from session summaries."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        metavar="summaries.json",
        help="JSON file produced by session_summarizer.py",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("test_cases_draft.json"),
        metavar="test_cases_draft.json",
        help="Output JSON file (default: test_cases_draft.json)",
    )
    parser.add_argument(
        "--dimensions",
        "-d",
        type=str,
        default="recall:4,temporal:4,hallucination:3,proactive:3,scale:2,type_distinction:2",
        help="Dimensions and counts, e.g. 'temporal:4,hallucination:3'",
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=20,
        help="Starting TC-NNN ID number (default: 20, since TC-001-019 exist)",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: {args.input} does not exist", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    summaries: list[dict[str, Any]] = json.loads(
        args.input.read_text(encoding="utf-8")
    )
    topics_text = collect_topics(summaries)

    topic_count = sum(len(s.get("topics", [])) for s in summaries)
    print(f"Loaded {topic_count} topic(s) from {len(summaries)} session(s).", file=sys.stderr)

    if topic_count == 0:
        print("Error: No topics found in summaries. Run session_summarizer.py first.", file=sys.stderr)
        sys.exit(1)

    dimensions = parse_dimensions(args.dimensions)
    total_target = sum(dimensions.values())
    print(
        f"Generating {total_target} test case(s) across {len(dimensions)} dimension(s): "
        f"{dimensions}",
        file=sys.stderr,
    )

    all_cases: list[dict[str, Any]] = []
    current_id = args.start_id

    for dim, count in dimensions.items():
        print(f"\n  [{dim}] Generating {count} case(s) ...", file=sys.stderr)
        cases = generate_for_dimension(dim, count, current_id, topics_text, client)
        print(f"    → Got {len(cases)} case(s).", file=sys.stderr)
        all_cases.extend(cases)
        current_id += len(cases)
        time.sleep(RATE_LIMIT_SLEEP)

    args.output.write_text(
        json.dumps(all_cases, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"\nDone. {len(all_cases)} test case(s) written to {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
