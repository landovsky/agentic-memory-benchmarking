#!/usr/bin/env python3
"""Load memory facts into Mem0.

Usage:
    python load_mem0.py --facts facts.json [--user-id hackathon] [--host localhost]
    python load_mem0.py --facts facts.json --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

MIN_CONFIDENCE = 0.5
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Load memory facts into Mem0.")
    parser.add_argument(
        "--facts",
        type=Path,
        required=True,
        metavar="facts.json",
        help="JSON file produced by memory_extractor.py",
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

    if not args.facts.is_file():
        print(f"Error: {args.facts} does not exist", file=sys.stderr)
        sys.exit(1)

    qdrant_host = args.host or os.environ.get("QDRANT_HOST", "localhost")

    facts: list[dict[str, Any]] = json.loads(args.facts.read_text(encoding="utf-8"))
    print(f"Loaded {len(facts)} fact(s) from {args.facts}")

    # Filter low-confidence facts
    filtered = [f for f in facts if float(f.get("confidence", 1.0)) >= MIN_CONFIDENCE]
    skipped = len(facts) - len(filtered)
    if skipped:
        print(f"Skipping {skipped} fact(s) with confidence < {MIN_CONFIDENCE}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would load {len(filtered)} fact(s) into Mem0")
        print(f"  Qdrant host : {qdrant_host}:6333")
        print(f"  user_id     : {args.user_id}")
        for i, fact in enumerate(filtered, start=1):
            project = fact.get("project") or "global"
            ftype = fact.get("type", "unknown")
            conf = fact.get("confidence", "?")
            print(f"  [{i:3d}] [{ftype}] [{project}] (conf={conf}) {fact.get('fact', '')[:80]}")
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

    for i, fact in enumerate(filtered, start=1):
        fact_text = fact.get("fact", "")
        ftype = fact.get("type", "unknown")
        project = fact.get("project") or "global"
        conf = fact.get("confidence", "?")

        print(f"[{i:3d}/{len(filtered)}] [{ftype}] [{project}] (conf={conf}) {fact_text[:80]}")

        try:
            m.add(
                [{"role": "user", "content": fact_text}],
                user_id=args.user_id,
                metadata={"type": ftype, "project": project},
            )
            successes += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures += 1

    print(f"\nDone. {successes} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
