#!/usr/bin/env python3
"""Load conversation sessions into Cognee.

Sends whole conversation text to Cognee and lets cognify() build its own
knowledge graph from the raw messages.

Usage:
    python load_cognee.py --sessions sessions.json [--dataset hackathon] [--host localhost]
    python load_cognee.py --sessions sessions.json --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def format_session_text(session: dict[str, Any]) -> str:
    """Format a session's messages into a conversation transcript."""
    lines: list[str] = []
    for msg in session.get("messages", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        header = f"[{role}]" + (f" ({ts})" if ts else "")
        lines.append(f"{header}\n{content}")
    return "\n\n".join(lines)


async def load_sessions(
    sessions: list[dict[str, Any]],
    base_dataset: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"\n[DRY RUN] Would load {len(sessions)} session(s) into Cognee")
        print(f"  dataset: {base_dataset}")
        for i, session in enumerate(sessions, start=1):
            sid = session.get("session_id", "unknown")[:8]
            msg_count = session.get("message_count", len(session.get("messages", [])))
            print(f"  [{i:3d}] session:{sid} | {msg_count} messages")
        return

    try:
        import cognee  # type: ignore[import]
    except ImportError:
        print("Error: cognee is not installed. Run: pip install cognee", file=sys.stderr)
        sys.exit(1)

    print(f"\nLoading {len(sessions)} session(s) into Cognee dataset '{base_dataset}' ...")

    for i, session in enumerate(sessions, start=1):
        sid = session.get("session_id", "unknown")
        msg_count = session.get("message_count", len(session.get("messages", [])))
        text = format_session_text(session)

        if not text.strip():
            print(f"  [{i:3d}/{len(sessions)}] session:{sid[:8]} | skipped (empty)")
            continue

        print(f"  [{i:3d}/{len(sessions)}] session:{sid[:8]} | {msg_count} messages | adding ...")
        try:
            await cognee.add(text, dataset_name=base_dataset)
        except Exception as exc:
            print(f"    ERROR adding: {exc}", file=sys.stderr)
            continue

    print(f"\n  Running cognify on dataset '{base_dataset}' (building knowledge graph) ...")
    try:
        await cognee.cognify([base_dataset])
    except Exception as exc:
        print(f"  ERROR cognifying: {exc}", file=sys.stderr)
        return

    print(f"  Dataset '{base_dataset}' done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load conversation sessions into Cognee.")
    parser.add_argument(
        "--sessions",
        type=Path,
        required=True,
        metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    parser.add_argument(
        "--dataset",
        default="hackathon",
        help="Base Cognee dataset name (default: hackathon)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Cognee service host (overrides COGNEE_HOST env var; default: localhost)",
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

    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    cognee_host = args.host or os.environ.get("COGNEE_HOST", "localhost")

    if not args.dry_run:
        if not anthropic_api_key:
            print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
            sys.exit(1)
        if not google_api_key:
            print("Error: GOOGLE_API_KEY environment variable is not set.", file=sys.stderr)
            sys.exit(1)

    # Configure Cognee via environment variables
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ["LLM_MODEL"] = "claude-3-5-haiku-20241022"
    os.environ["LLM_API_KEY"] = anthropic_api_key
    os.environ["EMBEDDING_PROVIDER"] = "gemini"
    os.environ["EMBEDDING_MODEL"] = "gemini/text-embedding-004"
    os.environ["EMBEDDING_API_KEY"] = google_api_key
    if cognee_host != "localhost":
        os.environ["COGNEE_HOST"] = cognee_host

    sessions: list[dict[str, Any]] = json.loads(
        args.sessions.read_text(encoding="utf-8")
    )
    print(f"Loaded {len(sessions)} session(s) from {args.sessions}")

    asyncio.run(load_sessions(sessions=sessions, base_dataset=args.dataset, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
