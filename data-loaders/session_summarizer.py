#!/usr/bin/env python3
"""Summarize stripped sessions into topic inventories for test case curation.

Uses Gemini on Vertex AI with async concurrent requests for speed.

Usage:
    python session_summarizer.py --input hotdesk_sessions.json --output summaries.json
    python session_summarizer.py --input hotdesk_sessions.json --output summaries.json --max-sessions 5
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from google import genai

VERTEX_PROJECT = "coworking-aggegator"
VERTEX_LOCATION = "europe-west3"
MODEL = "gemini-2.5-flash"
CONCURRENCY = 10
MAX_MESSAGES_PER_CHUNK = 50
CHUNK_OVERLAP = 5

SUMMARIZATION_PROMPT = """\
Analyze this coding session conversation and extract facts worth remembering \
for a long-term memory system.

For each fact, provide:
- fact: concise statement of what's worth remembering
- memory_type: one of: preference, episodic, semantic, goal
  - preference: stable user preferences (tools, frameworks, coding style)
  - episodic: time-bound events (bugs fixed, decisions made, problems solved)
  - semantic: current project state (tech stack, architecture, conventions)
  - goal: long-term objectives (deadlines, milestones, roadmap items)
- dimension_candidates: which benchmark dimensions this fact could test \
(list one or more): recall, temporal, proactive, hallucination, scale, type_distinction
  - recall: can the system retrieve this fact when asked directly?
  - temporal: did this fact replace/update an earlier fact?
  - proactive: would this fact be useful to surface when a similar problem recurs?
  - type_distinction: does this fact interact with another fact of a different type?
- confidence: 0.0-1.0 how certain you are this is worth remembering
- source_context: brief description of where in the conversation this appeared

Focus on:
- User preferences and conventions expressed
- Problems solved, bugs fixed, workarounds discovered
- Project architecture, tech stack, tool choices
- Goals, deadlines, milestones
- Things that CHANGED over time (old approach replaced by new)
- Solutions that would be useful if a similar problem recurs

Skip: greetings, tool outputs, generic coding patterns, file listings, \
system messages, skill preambles.

Return a JSON array only (no other text):
[
  {{
    "fact": "...",
    "memory_type": "preference|episodic|semantic|goal",
    "dimension_candidates": ["recall", ...],
    "confidence": 0.9,
    "source_context": "..."
  }}
]

If the conversation contains nothing worth remembering, return an empty array: []

CONVERSATION:
{conversation}"""


def format_conversation(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        header = f"[{role}]" + (f" ({ts})" if ts else "")
        lines.append(f"{header}\n{content}")
    return "\n\n".join(lines)


def chunk_messages(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if len(messages) <= MAX_MESSAGES_PER_CHUNK:
        return [messages]
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(messages):
        end = start + MAX_MESSAGES_PER_CHUNK
        chunks.append(messages[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


def parse_json_response(raw: str) -> list[dict[str, Any]]:
    """Parse JSON from LLM response, stripping code fences if needed."""
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


async def process_chunk(
    client: genai.Client,
    semaphore: asyncio.Semaphore,
    session_id: str,
    chunk_idx: int,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Process a single conversation chunk through Gemini."""
    conversation_text = format_conversation(messages)
    if not conversation_text.strip():
        return []

    prompt = SUMMARIZATION_PROMPT.format(conversation=conversation_text)

    async with semaphore:
        for attempt in range(3):
            try:
                response = await client.aio.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config={"max_output_tokens": 4096, "temperature": 0.1},
                )
                text = response.text
                if not text:
                    return []
                topics = parse_json_response(text.strip())
                return topics
            except Exception as exc:
                if attempt == 2:
                    print(
                        f"    [{session_id}] chunk {chunk_idx} failed: {exc}",
                        file=sys.stderr,
                    )
                    return []
                await asyncio.sleep(2**attempt)
    return []


async def process_session(
    client: genai.Client,
    semaphore: asyncio.Semaphore,
    session: dict[str, Any],
) -> dict[str, Any]:
    """Process all chunks of a session concurrently."""
    session_id = session.get("session_id", "unknown")
    messages = session.get("messages", [])

    if not messages:
        return {
            "session_id": session_id,
            "timestamp_range": [None, None],
            "topics": [],
        }

    chunks = chunk_messages(messages)
    tasks = [
        process_chunk(client, semaphore, session_id, i, chunk)
        for i, chunk in enumerate(chunks)
    ]
    chunk_results = await asyncio.gather(*tasks)

    # Flatten and deduplicate
    all_topics: list[dict[str, Any]] = []
    for topics in chunk_results:
        all_topics.extend(topics)

    seen: set[str] = set()
    unique_topics: list[dict[str, Any]] = []
    for topic in all_topics:
        fact = topic.get("fact", "").strip().lower()
        if fact and fact not in seen:
            seen.add(fact)
            unique_topics.append(topic)

    return {
        "session_id": session_id,
        "file": session.get("file", ""),
        "project_hash": session.get("project_hash"),
        "timestamp_range": [
            session.get("first_timestamp"),
            session.get("last_timestamp"),
        ],
        "message_count": session.get("message_count", 0),
        "topics": unique_topics,
    }


async def run(sessions: list[dict[str, Any]], concurrency: int) -> list[dict[str, Any]]:
    client = genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
    )
    semaphore = asyncio.Semaphore(concurrency)

    print(f"Processing {len(sessions)} session(s) with concurrency={concurrency} ...", file=sys.stderr)

    tasks = [process_session(client, semaphore, s) for s in sessions]
    summaries = await asyncio.gather(*tasks)

    total_topics = sum(len(s["topics"]) for s in summaries)
    print(f"\nDone. {total_topics} topic(s) from {len(summaries)} session(s).", file=sys.stderr)
    return list(summaries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize stripped sessions into topic inventories."
    )
    parser.add_argument(
        "--input", "-i", type=Path, required=True, metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("summaries.json"),
        metavar="summaries.json", help="Output JSON file (default: summaries.json)",
    )
    parser.add_argument(
        "--max-sessions", type=int, default=None, metavar="N",
        help="Process only the first N sessions (for testing)",
    )
    parser.add_argument(
        "--min-messages", type=int, default=3, metavar="N",
        help="Skip sessions with fewer than N messages (default: 3)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=CONCURRENCY, metavar="N",
        help=f"Max concurrent API requests (default: {CONCURRENCY})",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: {args.input} does not exist", file=sys.stderr)
        sys.exit(1)

    sessions: list[dict[str, Any]] = json.loads(
        args.input.read_text(encoding="utf-8")
    )
    sessions = [s for s in sessions if s.get("message_count", 0) >= args.min_messages]
    if args.max_sessions:
        sessions = sessions[: args.max_sessions]

    summaries = asyncio.run(run(sessions, args.concurrency))

    args.output.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Written to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
