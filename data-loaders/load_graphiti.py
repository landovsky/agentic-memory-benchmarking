#!/usr/bin/env python3
"""Load conversation sessions into Graphiti.

Sends whole messages as episodes to Graphiti, letting it build its own
knowledge graph (entity/relation extraction) from the conversation.

Usage:
    python load_graphiti.py --sessions sessions.json [--group-id hackathon] [--neo4j-host localhost]
    python load_graphiti.py --sessions sessions.json --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

EPISODE_SLEEP = 0.2


def parse_timestamp(ts: str | None) -> datetime:
    """Parse an ISO timestamp string, falling back to now(UTC)."""
    if ts:
        try:
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


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


async def load_messages(
    messages: list[dict[str, Any]],
    group_id: str,
    neo4j_host: str,
    neo4j_password: str,
    google_api_key: str,
    dry_run: bool,
) -> tuple[int, int]:
    if dry_run:
        print(f"\n[DRY RUN] Would send {len(messages)} message(s) to Graphiti")
        print(f"  Neo4j host : bolt://{neo4j_host}:7687")
        print(f"  group_id   : {group_id}")
        for i, msg in enumerate(messages, start=1):
            role = msg["role"]
            ts = msg.get("timestamp", "now")
            sid = msg["session_id"][:8]
            print(f"  [{i:3d}] session:{sid} | {role:9s} | {ts} | {msg['content'][:60]}")
        return 0, 0

    try:
        from graphiti_core import Graphiti  # type: ignore[import]
        from graphiti_core.nodes import EpisodeType  # type: ignore[import]
        from graphiti_core.llm_client.gemini_client import GeminiClient, LLMConfig  # type: ignore[import]
        from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig  # type: ignore[import]
        from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient  # type: ignore[import]
    except ImportError:
        print(
            "Error: graphiti-core is not installed. "
            'Run: pip install "graphiti-core[google-genai]"',
            file=sys.stderr,
        )
        sys.exit(1)

    llm_config = LLMConfig(api_key=google_api_key, model="gemini-2.0-flash")

    print(f"\nConnecting to Graphiti (Neo4j at bolt://{neo4j_host}:7687) ...")
    try:
        graphiti = Graphiti(
            f"bolt://{neo4j_host}:7687",
            "neo4j",
            neo4j_password,
            llm_client=GeminiClient(config=llm_config),
            embedder=GeminiEmbedder(
                config=GeminiEmbedderConfig(
                    api_key=google_api_key,
                    embedding_model="text-embedding-004",
                )
            ),
            cross_encoder=GeminiRerankerClient(config=llm_config),
        )
    except Exception as exc:
        print(f"Error: Failed to create Graphiti client: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Building indices and constraints ...")
    try:
        await graphiti.build_indices_and_constraints()
    except Exception as exc:
        print(f"Warning: build_indices_and_constraints failed: {exc}", file=sys.stderr)

    successes = 0
    failures = 0

    for i, msg in enumerate(messages, start=1):
        role = msg["role"]
        content = msg["content"]
        ts = parse_timestamp(msg.get("timestamp"))
        sid = msg["session_id"][:8]

        episode_name = f"msg_{i:04d}_{role}"
        print(f"[{i:3d}/{len(messages)}] session:{sid} | {role:9s} | {content[:60]}")

        try:
            await graphiti.add_episode(
                name=episode_name,
                episode_body=f"{role}: {content}",
                source=EpisodeType.text,
                source_description=f"{role} message from session {msg['session_id']}",
                reference_time=ts,
                group_id=group_id,
            )
            successes += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures += 1

        if i < len(messages):
            await asyncio.sleep(EPISODE_SLEEP)

    await graphiti.close()
    return successes, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Load conversation sessions into Graphiti.")
    parser.add_argument(
        "--sessions",
        type=Path,
        required=True,
        metavar="sessions.json",
        help="JSON file produced by jsonl_parser.py",
    )
    parser.add_argument(
        "--group-id",
        default="hackathon",
        help="Graphiti group_id namespace (default: hackathon)",
    )
    parser.add_argument(
        "--neo4j-host",
        default=None,
        help="Neo4j host (overrides NEO4J_HOST env var; default: localhost)",
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

    neo4j_host = args.neo4j_host or os.environ.get("NEO4J_HOST", "localhost")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "hackathon2025")
    google_api_key = os.environ.get("GOOGLE_API_KEY", "")

    if not args.dry_run and not google_api_key:
        print("Error: GOOGLE_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    sessions: list[dict[str, Any]] = json.loads(
        args.sessions.read_text(encoding="utf-8")
    )
    messages = flatten_messages(sessions)
    print(f"Loaded {len(sessions)} session(s), {len(messages)} message(s) from {args.sessions}")

    successes, failures = asyncio.run(
        load_messages(
            messages=messages,
            group_id=args.group_id,
            neo4j_host=neo4j_host,
            neo4j_password=neo4j_password,
            google_api_key=google_api_key,
            dry_run=args.dry_run,
        )
    )

    if not args.dry_run:
        print(f"\nDone. {successes} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
