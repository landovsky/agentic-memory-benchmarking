#!/usr/bin/env python3
"""Summarize stripped sessions into topic inventories for test case curation.

Sends each session's dialogue to Claude and returns structured topics
tagged by benchmark dimension and memory type.

Usage:
    python session_summarizer.py --input hotdesk_sessions.json --output summaries.json
    python session_summarizer.py --input hotdesk_sessions.json --output summaries.json --max-sessions 5
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

MODEL = "claude-haiku-4-5-20251001"
RATE_LIMIT_SLEEP = 0.5
MAX_MESSAGES_PER_CHUNK = 50
CHUNK_OVERLAP = 5


def format_conversation(messages: list[dict[str, Any]]) -> str:
    """Format messages into a readable conversation string."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        header = f"[{role}]" + (f" ({ts})" if ts else "")
        lines.append(f"{header}\n{content}")
    return "\n\n".join(lines)


def chunk_messages(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Split messages into chunks with overlap for large sessions."""
    if len(messages) <= MAX_MESSAGES_PER_CHUNK:
        return [messages]

    chunks: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(messages):
        end = start + MAX_MESSAGES_PER_CHUNK
        chunks.append(messages[start:end])
        start = end - CHUNK_OVERLAP
    return chunks


def extract_topics_from_text(
    conversation_text: str, client: anthropic.Anthropic
) -> list[dict[str, Any]]:
    """Call Claude to extract topics from a conversation chunk."""
    prompt = SUMMARIZATION_PROMPT.format(conversation=conversation_text)

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

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        topics = json.loads(raw)
        if not isinstance(topics, list):
            print("    Unexpected response shape (not a list)", file=sys.stderr)
            return []
    except json.JSONDecodeError as exc:
        print(f"    JSON parse error: {exc}", file=sys.stderr)
        print(f"    Raw response snippet: {raw[:300]}", file=sys.stderr)
        return []

    return topics


def summarize_session(
    session: dict[str, Any], client: anthropic.Anthropic
) -> dict[str, Any]:
    """Extract topics from a single session, handling chunking."""
    messages = session.get("messages", [])
    if not messages:
        return {
            "session_id": session.get("session_id", "unknown"),
            "timestamp_range": [None, None],
            "topics": [],
        }

    chunks = chunk_messages(messages)
    all_topics: list[dict[str, Any]] = []

    for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
            print(f"      Chunk {i + 1}/{len(chunks)} ({len(chunk)} messages)", file=sys.stderr)
        conversation_text = format_conversation(chunk)
        if not conversation_text.strip():
            continue
        topics = extract_topics_from_text(conversation_text, client)
        all_topics.extend(topics)
        if i < len(chunks) - 1:
            time.sleep(RATE_LIMIT_SLEEP)

    # Deduplicate by fact text (rough dedup)
    seen: set[str] = set()
    unique_topics: list[dict[str, Any]] = []
    for topic in all_topics:
        fact = topic.get("fact", "").strip().lower()
        if fact and fact not in seen:
            seen.add(fact)
            unique_topics.append(topic)

    return {
        "session_id": session.get("session_id", "unknown"),
        "file": session.get("file", ""),
        "project_hash": session.get("project_hash"),
        "timestamp_range": [
            session.get("first_timestamp"),
            session.get("last_timestamp"),
        ],
        "message_count": session.get("message_count", 0),
        "topics": unique_topics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize stripped sessions into topic inventories."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        required=True,
        metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("summaries.json"),
        metavar="summaries.json",
        help="Output JSON file (default: summaries.json)",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N sessions (for testing)",
    )
    parser.add_argument(
        "--min-messages",
        type=int,
        default=3,
        metavar="N",
        help="Skip sessions with fewer than N messages (default: 3)",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Error: {args.input} does not exist", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    sessions: list[dict[str, Any]] = json.loads(
        args.input.read_text(encoding="utf-8")
    )

    # Filter tiny sessions
    sessions = [s for s in sessions if s.get("message_count", 0) >= args.min_messages]

    if args.max_sessions:
        sessions = sessions[: args.max_sessions]

    print(f"Processing {len(sessions)} session(s) ...", file=sys.stderr)

    summaries: list[dict[str, Any]] = []
    total_topics = 0

    for idx, session in enumerate(sessions, start=1):
        session_id = session.get("session_id", f"session_{idx}")
        msg_count = session.get("message_count", 0)
        print(
            f"  [{idx}/{len(sessions)}] Session {session_id} ({msg_count} messages) ...",
            file=sys.stderr,
        )

        summary = summarize_session(session, client)
        topic_count = len(summary["topics"])
        total_topics += topic_count
        print(f"    → {topic_count} topic(s) extracted.", file=sys.stderr)
        summaries.append(summary)

        if idx < len(sessions):
            time.sleep(RATE_LIMIT_SLEEP)

    args.output.write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"\nDone. {total_topics} total topic(s) from {len(summaries)} session(s). "
        f"Written to {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
