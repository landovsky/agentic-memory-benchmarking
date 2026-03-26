#!/usr/bin/env python3
"""Load conversation sessions into Graphiti.

Sends whole messages as episodes to Graphiti, letting it build its own
knowledge graph (entity/relation extraction) from the conversation.

Usage:
    python load_graphiti.py --sessions sessions.json [--group-id hackathon] [--host <HOST_IP>]
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
MAX_CONTENT_CHARS = 4000


def _patch_openai_client_for_litellm():
    """Patch graphiti's OpenAIClient to use chat.completions instead of responses API.

    LiteLLM proxy does not support the OpenAI Responses API (/v1/responses).
    Graphiti v0.28 uses responses.parse for structured completions. This patch
    redirects structured completions to chat.completions with JSON mode.

    The _WrappedResponse bridges the gap between chat.completions response format
    and the Responses API format that _handle_structured_response expects:
    - output_text: from choices[0].message.content
    - usage.input_tokens / output_tokens: mapped from prompt_tokens / completion_tokens
    """
    from graphiti_core.llm_client.openai_client import OpenAIClient

    class _UsageAdapter:
        """Adapt chat.completions usage (prompt_tokens) to responses API (input_tokens)."""
        def __init__(self, usage):
            self.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            self.output_tokens = getattr(usage, "completion_tokens", 0) or 0

    class _WrappedResponse:
        def __init__(self, chat_response):
            content = chat_response.choices[0].message.content if chat_response.choices else None
            self.output_text = content or "{}"
            self.usage = _UsageAdapter(chat_response.usage) if chat_response.usage else None

    async def _create_structured_completion(
        self, model, messages, temperature, max_tokens, response_model, **kwargs
    ):
        import json as _json

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


def build_session_episodes(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build one episode per session by joining all messages into a conversation."""
    episodes: list[dict[str, Any]] = []
    for session in sessions:
        session_id = session.get("session_id", "unknown")
        msgs = session.get("messages", [])
        if not msgs:
            continue

        lines: list[str] = []
        for msg in msgs:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if len(content) > MAX_CONTENT_CHARS:
                content = content[:MAX_CONTENT_CHARS] + "\n[truncated]"
            lines.append(f"{role}: {content}")

        episode_body = "\n\n".join(lines)
        # Use earliest message timestamp as reference_time
        first_ts = msgs[0].get("timestamp")

        episodes.append({
            "session_id": session_id,
            "episode_body": episode_body,
            "timestamp": first_ts,
            "message_count": len(msgs),
        })
    return episodes


async def load_episodes(
    episodes: list[dict[str, Any]],
    group_id: str,
    neo4j_host: str,
    neo4j_password: str,
    litellm_url: str,
    dry_run: bool,
) -> tuple[int, int]:
    if dry_run:
        print(f"\n[DRY RUN] Would send {len(episodes)} session episode(s) to Graphiti")
        print(f"  Neo4j host : bolt://{neo4j_host}:7687")
        print(f"  LiteLLM    : {litellm_url}")
        print(f"  group_id   : {group_id}")
        for i, ep in enumerate(episodes, start=1):
            sid = ep["session_id"][:8]
            ts = ep.get("timestamp", "now")
            n = ep["message_count"]
            body_preview = ep["episode_body"][:80].replace("\n", " ")
            print(f"  [{i:3d}] session:{sid} | {n:3d} msgs | {ts} | {body_preview}")
        return 0, 0

    try:
        from graphiti_core import Graphiti
        from graphiti_core.nodes import EpisodeType
        from graphiti_core.llm_client.openai_client import OpenAIClient, LLMConfig
        from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
        from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
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

    for i, ep in enumerate(episodes, start=1):
        sid = ep["session_id"][:8]
        ts = parse_timestamp(ep.get("timestamp"))
        n = ep["message_count"]
        body_preview = ep["episode_body"][:60].replace("\n", " ")

        episode_name = f"session_{i:04d}_{sid}"
        print(f"[{i:3d}/{len(episodes)}] session:{sid} | {n:3d} msgs | {body_preview}")

        try:
            await graphiti.add_episode(
                name=episode_name,
                episode_body=ep["episode_body"],
                source=EpisodeType.message,
                source_description=f"Conversation session {ep['session_id']} ({n} messages)",
                reference_time=ts,
                group_id=group_id,
            )
            successes += 1
            print(f"  OK ({successes} done, {failures} failed)")
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failures += 1

        if i < len(episodes):
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
        help="JSON file with conversation sessions (from jsonl_parser.py)",
    )
    parser.add_argument(
        "--group-id",
        default="hackathon",
        help="Graphiti group_id namespace (default: hackathon)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host IP for Neo4j and LiteLLM (overrides env vars; default: localhost)",
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

    host = args.host or os.environ.get("HOST_IP", "localhost")
    neo4j_host = os.environ.get("NEO4J_HOST", host)
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "hackathon2025")
    litellm_url = os.environ.get("LITELLM_URL", f"http://{host}:4000")

    sessions: list[dict[str, Any]] = json.loads(
        args.sessions.read_text(encoding="utf-8")
    )
    episodes = build_session_episodes(sessions)
    total_msgs = sum(ep["message_count"] for ep in episodes)
    print(f"Loaded {len(sessions)} session(s), {total_msgs} message(s) → {len(episodes)} episode(s)")

    successes, failures = asyncio.run(
        load_episodes(
            episodes=episodes,
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
