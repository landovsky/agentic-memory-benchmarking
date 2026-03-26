#!/usr/bin/env python3
"""Load memory facts into Graphiti.

Usage:
    python load_graphiti.py --facts facts.json [--group-id hackathon] [--neo4j-host localhost]
    python load_graphiti.py --facts facts.json --dry-run
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


def _patch_openai_client_for_litellm():
    """Patch graphiti's OpenAIClient to use chat.completions instead of responses API.

    LiteLLM proxy does not support the OpenAI Responses API (/v1/responses).
    Graphiti v0.28 uses responses.parse for structured completions. This patch
    redirects structured completions to chat.completions with JSON mode.
    """
    from graphiti_core.llm_client.openai_client import OpenAIClient

    async def _create_structured_completion(
        self, model, messages, temperature, max_tokens, response_model, **kwargs
    ):
        import json as _json
        # Inject the expected JSON schema so the LLM returns the right structure
        schema = response_model.model_json_schema()
        schema_instruction = (
            f"You MUST respond with a JSON object matching this schema:\n"
            f"{_json.dumps(schema, indent=2)}\n"
            f"Return ONLY a valid JSON object, no markdown."
        )
        patched_messages = list(messages)
        if patched_messages and patched_messages[0].get("role") == "system":
            patched_messages[0] = {
                **patched_messages[0],
                "content": patched_messages[0]["content"] + "\n\n" + schema_instruction,
            }
        else:
            patched_messages.insert(0, {"role": "system", "content": schema_instruction})

        response = await self.client.chat.completions.create(
            model=model,
            messages=patched_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        class _WrappedResponse:
            def __init__(self, chat_response):
                self.output_text = chat_response.choices[0].message.content
                self.usage = chat_response.usage
        return _WrappedResponse(response)

    OpenAIClient._create_structured_completion = _create_structured_completion


def parse_timestamp(ts: str | None) -> datetime:
    """Parse an ISO timestamp string, falling back to now(UTC)."""
    if ts:
        try:
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


async def load_facts(
    facts: list[dict[str, Any]],
    group_id: str,
    neo4j_host: str,
    neo4j_password: str,
    litellm_url: str,
    dry_run: bool,
) -> tuple[int, int]:
    if dry_run:
        print(f"\n[DRY RUN] Would load {len(facts)} fact(s) into Graphiti")
        print(f"  Neo4j host : bolt://{neo4j_host}:7687")
        print(f"  group_id   : {group_id}")
        for i, fact in enumerate(facts, start=1):
            ftype = fact.get("type", "unknown")
            ts = fact.get("timestamp", "now")
            print(
                f"  [{i:3d}] [{ftype}] (ts={ts}) {fact.get('fact', '')[:80]}"
            )
        return 0, 0

    try:
        from graphiti_core import Graphiti  # type: ignore[import]
        from graphiti_core.nodes import EpisodeType  # type: ignore[import]
        from graphiti_core.llm_client.openai_client import OpenAIClient, LLMConfig  # type: ignore[import]
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig  # type: ignore[import]
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient  # type: ignore[import]
    except ImportError:
        print(
            "Error: graphiti-core is not installed. "
            'Run: pip install "graphiti-core[openai]"',
            file=sys.stderr,
        )
        sys.exit(1)

    _patch_openai_client_for_litellm()

    llm_config = LLMConfig(
        api_key="dummy",
        base_url=litellm_url,
        model="gemini-flash",
        small_model="gemini-flash",
    )

    print(f"\nConnecting to Graphiti (Neo4j at bolt://{neo4j_host}:7687) ...")
    print(f"Using LiteLLM proxy at {litellm_url}")
    try:
        graphiti = Graphiti(
            f"bolt://{neo4j_host}:7687",
            "neo4j",
            neo4j_password,
            llm_client=OpenAIClient(config=llm_config),
            embedder=OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    api_key="dummy",
                    base_url=litellm_url,
                    embedding_model="text-embedding-004",
                    embedding_dim=768,
                )
            ),
            cross_encoder=OpenAIRerankerClient(config=llm_config),
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

    for i, fact in enumerate(facts, start=1):
        ftype = fact.get("type", "unknown")
        fact_text = fact.get("fact", "")
        ts = parse_timestamp(fact.get("timestamp"))

        episode_name = f"fact_{i:04d}_{ftype}"
        print(
            f"[{i:3d}/{len(facts)}] [{ftype}] {fact_text[:80]}"
        )

        try:
            await graphiti.add_episode(
                name=episode_name,
                episode_body=fact_text,
                source=EpisodeType.text,
                source_description=f"{ftype} memory from session",
                reference_time=ts,
                group_id=group_id,
            )
            successes += 1
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures += 1

        if i < len(facts):
            await asyncio.sleep(EPISODE_SLEEP)

    await graphiti.close()
    return successes, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Load memory facts into Graphiti.")
    parser.add_argument(
        "--facts",
        type=Path,
        required=True,
        metavar="facts.json",
        help="JSON file produced by memory_extractor.py",
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

    if not args.facts.is_file():
        print(f"Error: {args.facts} does not exist", file=sys.stderr)
        sys.exit(1)

    neo4j_host = args.neo4j_host or os.environ.get("NEO4J_HOST", "localhost")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "hackathon2025")
    litellm_url = os.environ.get("LITELLM_URL", "http://localhost:4000")

    facts: list[dict[str, Any]] = json.loads(args.facts.read_text(encoding="utf-8"))
    print(f"Loaded {len(facts)} fact(s) from {args.facts}")

    successes, failures = asyncio.run(
        load_facts(
            facts=facts,
            group_id=args.group_id,
            neo4j_host=neo4j_host,
            neo4j_password=neo4j_password,
            litellm_url=litellm_url,
            dry_run=args.dry_run,
        )
    )

    if not args.dry_run:
        print(f"\nDone. {successes} succeeded, {failures} failed.")


if __name__ == "__main__":
    main()
