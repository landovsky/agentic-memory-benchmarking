#!/usr/bin/env python3
"""Load memory facts into Cognee.

Usage:
    python load_cognee.py --facts facts.json [--dataset hackathon] [--host localhost]
    python load_cognee.py --facts facts.json --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def group_facts_by_project(
    facts: list[dict[str, Any]], base_dataset: str
) -> dict[str, list[dict[str, Any]]]:
    """Group facts by project, returning a dict of dataset_name -> facts list."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        project = fact.get("project")
        if project and project != "global":
            # Sanitise project name for use as a dataset name
            safe_project = project.lower().replace(" ", "_").replace("/", "_")
            dataset_name = f"{base_dataset}_{safe_project}"
        else:
            dataset_name = base_dataset
        groups[dataset_name].append(fact)
    return dict(groups)


async def load_dataset(dataset_name: str, facts: list[dict[str, Any]]) -> None:
    """Add and cognify a single dataset."""
    import cognee  # type: ignore[import]

    # Combine all facts into a single text blob
    lines = [f["fact"] for f in facts if f.get("fact")]
    text_blob = "\n".join(lines)

    print(f"  Adding {len(facts)} fact(s) to dataset '{dataset_name}' ...")
    await cognee.add(text_blob, dataset_name=dataset_name)

    print(f"  Running cognify on dataset '{dataset_name}' (building knowledge graph) ...")
    await cognee.cognify([dataset_name])
    print(f"  Dataset '{dataset_name}' done.")


async def run(
    facts: list[dict[str, Any]],
    base_dataset: str,
    dry_run: bool,
) -> None:
    groups = group_facts_by_project(facts, base_dataset)

    if dry_run:
        print(f"\n[DRY RUN] Would create {len(groups)} dataset(s):")
        for dataset_name, group_facts in groups.items():
            print(f"  Dataset '{dataset_name}' <- {len(group_facts)} fact(s)")
            for fact in group_facts:
                ftype = fact.get("type", "unknown")
                print(f"    [{ftype}] {fact.get('fact', '')[:80]}")
        return

    try:
        import cognee  # type: ignore[import]
    except ImportError:
        print("Error: cognee is not installed. Run: pip install cognee", file=sys.stderr)
        sys.exit(1)

    print(f"\nLoading {len(facts)} fact(s) into {len(groups)} Cognee dataset(s) ...")

    for dataset_name, group_facts in groups.items():
        try:
            await load_dataset(dataset_name, group_facts)
        except Exception as exc:
            print(f"  ERROR on dataset '{dataset_name}': {exc}", file=sys.stderr)

    print("\nAll datasets processed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load memory facts into Cognee.")
    parser.add_argument(
        "--facts",
        type=Path,
        required=True,
        metavar="facts.json",
        help="JSON file produced by memory_extractor.py",
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

    if not args.facts.is_file():
        print(f"Error: {args.facts} does not exist", file=sys.stderr)
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

    facts: list[dict[str, Any]] = json.loads(args.facts.read_text(encoding="utf-8"))
    print(f"Loaded {len(facts)} fact(s) from {args.facts}")

    asyncio.run(run(facts=facts, base_dataset=args.dataset, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
