#!/usr/bin/env python3
"""Load conversation sessions into Mem0.

Sends whole messages to Mem0 with infer=True, letting Mem0's own LLM
extract memories from the conversation.

Usage:
    python load_mem0.py --sessions sessions.json [--user-id hackathon] [--host localhost]
    python load_mem0.py --sessions sessions.json --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "claude-3-5-haiku-20241022"


def build_config(qdrant_host: str) -> dict[str, Any]:
    return {
        "llm": {
            "provider": "anthropic",
            "config": {
                "model": MODEL,
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


def flatten_messages(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten sessions into a list of messages, each tagged with session_id."""
    messages: list[dict[str, Any]] = []
    for session in sessions:
        session_id = session.get("session_id", "unknown")
        for msg in session.get("messages", []):
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("timestamp"),
                "session_id": session_id,
            })
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="Load conversation sessions into Mem0.")
    parser.add_argument(
        "--sessions",
        type=Path,
        required=True,
        metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    parser.add_argument(
        "--user-id",
        default="hackathon",
        help="Mem0 user_id namespace (default: hackathon)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Qdrant host (overrides QDRANT_HOST env var; default: localhost)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be loaded without actually loading",
    )
    args = parser.parse_args()

    if not args.sessions.is_file():
        print(f"Error: {args.sessions} does not exist", file=sys.stderr)
        sys.exit(1)

    qdrant_host = args.host or os.environ.get("QDRANT_HOST", "localhost")

    sessions: list[dict[str, Any]] = json.loads(
        args.sessions.read_text(encoding="utf-8")
    )
    messages = flatten_messages(sessions)
    print(f"Loaded {len(sessions)} session(s), {len(messages)} message(s) from {args.sessions}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would send {len(messages)} message(s) to Mem0")
        print(f"  Qdrant host : {qdrant_host}:6333")
        print(f"  user_id     : {args.user_id}")
        for i, msg in enumerate(messages, start=1):
            role = msg["role"]
            sid = msg["session_id"][:8]
            content = msg["content"][:60]
            print(f"  [{i:3d}] session:{sid} | {role:9s} | {content}")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        from mem0 import Memory  # type: ignore[import]
    except ImportError:
        print("Error: mem0ai is not installed. Run: pip install mem0ai", file=sys.stderr)
        sys.exit(1)

    config = build_config(qdrant_host)
    print(f"\nConnecting to Mem0 (Qdrant at {qdrant_host}:6333) ...")
    try:
        m = Memory.from_config(config)
    except Exception as exc:
        print(f"Error: Failed to initialise Mem0: {exc}", file=sys.stderr)
        sys.exit(1)

    successes = 0
    failures = 0

    for i, msg in enumerate(messages, start=1):
        role = msg["role"]
        content = msg["content"]
        sid = msg["session_id"][:8]

        print(f"[{i:3d}/{len(messages)}] session:{sid} | {role:9s} | {content[:60]}")

        try:
            m.add(
                [{"role": role, "content": content}],
                user_id=args.user_id,
                metadata={"session_id": msg["session_id"]},
            )
            successes += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures += 1

    print(f"\nDone. {successes} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
