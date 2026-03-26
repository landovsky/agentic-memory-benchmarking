#!/usr/bin/env python3
"""DEPRECATED: This script is no longer part of the main data loading pipeline.

The loaders (load_mem0.py, load_graphiti.py, load_cognee.py) now accept
sessions.json directly and send whole messages to each memory system,
letting each system do its own extraction/indexing.

This script is kept for reference only.

Original usage:
    python memory_extractor.py --input sessions.json --output facts.json
    python memory_extractor.py --session-file session.jsonl  # direct from JSONL
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

EXTRACTION_PROMPT = """\
Analyze this coding session conversation and extract memory-worthy facts.

For EACH fact, classify it as one of:
- preference: Stable user preferences (tools, frameworks, coding style)
- episodic: Time-bound events (bugs fixed, decisions made, problems solved)
- semantic: Current project state (tech stack, architecture, configurations)
- goal: Long-term objectives (deadlines, milestones, roadmap items)

Return a JSON array (no other text, pure JSON):
[
  {{
    "type": "preference|episodic|semantic|goal",
    "fact": "concise statement of the fact",
    "project": "project name or null if global",
    "confidence": 0.0-1.0,
    "timestamp": "ISO timestamp from conversation or null"
  }}
]

Only extract facts that would be USEFUL to remember in future sessions.
Skip: greetings, debugging noise, tool outputs, generic coding patterns.

CONVERSATION:
{conversation}"""

MODEL = "claude-3-5-haiku-20241022"
RATE_LIMIT_SLEEP = 0.5


def format_conversation(messages: list[dict[str, Any]]) -> str:
    """Format a list of message dicts into a readable conversation string."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        header = f"[{role}]" + (f" ({ts})" if ts else "")
        lines.append(f"{header}\n{content}")
    return "\n\n".join(lines)


def extract_facts_from_session(
    session: dict[str, Any], client: anthropic.Anthropic
) -> list[dict[str, Any]]:
    """Call Claude to extract facts from a single session."""
    conversation_text = format_conversation(session.get("messages", []))
    if not conversation_text.strip():
        return []

    prompt = EXTRACTION_PROMPT.format(conversation=conversation_text)

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
        # Remove first and last fence lines
        raw = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()

    try:
        facts = json.loads(raw)
        if not isinstance(facts, list):
            print(f"    Unexpected response shape (not a list)", file=sys.stderr)
            return []
    except json.JSONDecodeError as exc:
        print(f"    JSON parse error: {exc}", file=sys.stderr)
        print(f"    Raw response snippet: {raw[:300]}", file=sys.stderr)
        return []

    # Attach session metadata to each fact
    session_id = session.get("session_id", "unknown")
    for fact in facts:
        fact.setdefault("session_id", session_id)

    return facts


def load_sessions_from_jsonl(path: Path) -> list[dict[str, Any]]:
    """Import the JSONL parser and parse a single file directly."""
    # Add data-loaders dir to path so we can import jsonl_parser
    sys.path.insert(0, str(path.parent))
    try:
        import importlib
        jsonl_parser = importlib.import_module("jsonl_parser")
    except ImportError:
        # Fall back: assume jsonl_parser.py is in the same directory
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jsonl_parser", Path(__file__).parent / "jsonl_parser.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot locate jsonl_parser.py")
        jsonl_parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(jsonl_parser)  # type: ignore[union-attr]

    session = jsonl_parser.parse_session_file(path)
    return [session] if session is not None else []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract memory-worthy facts from conversations using Claude."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--input",
        "-i",
        type=Path,
        metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    source_group.add_argument(
        "--session-file",
        type=Path,
        metavar="session.jsonl",
        help="Parse a single JSONL session file directly",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="facts.json",
        default=Path("facts.json"),
        help="Output JSON file for extracted facts (default: facts.json)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    if args.input:
        if not args.input.is_file():
            print(f"Error: {args.input} does not exist", file=sys.stderr)
            sys.exit(1)
        sessions: list[dict[str, Any]] = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        if not args.session_file.is_file():
            print(f"Error: {args.session_file} does not exist", file=sys.stderr)
            sys.exit(1)
        sessions = load_sessions_from_jsonl(args.session_file)

    print(f"Processing {len(sessions)} session(s) ...", file=sys.stderr)

    all_facts: list[dict[str, Any]] = []
    for idx, session in enumerate(sessions, start=1):
        session_id = session.get("session_id", f"session_{idx}")
        msg_count = session.get("message_count", 0)
        print(
            f"  [{idx}/{len(sessions)}] Session {session_id} ({msg_count} messages) ...",
            file=sys.stderr,
        )
        facts = extract_facts_from_session(session, client)
        print(f"    Extracted {len(facts)} fact(s).", file=sys.stderr)
        all_facts.extend(facts)

        if idx < len(sessions):
            time.sleep(RATE_LIMIT_SLEEP)

    args.output.write_text(json.dumps(all_facts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"\nTotal facts extracted: {len(all_facts)}. Written to {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
