#!/usr/bin/env python3
"""Inject Claude Code JSONL sessions into Mem0 via REST API.

Usage:
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --dry-run
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --progress progress.json
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --concurrency 10
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import aiohttp

# ── Constants ────────────────────────────────────────────────────────────────
MEM0_URL = "http://localhost:8181"
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "openmemory"
USER_ID = "hackathon"


# ── JSONL Parsing ────────────────────────────────────────────────────────────
def extract_content(content: Any) -> str:
    """Extract text from a message content field.

    User messages have a plain string content.
    Assistant messages have a list of blocks — only 'text' blocks are kept.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def extract_messages(directory: Path) -> list[dict[str, str]]:
    """Recursively scan directory for *.jsonl files and extract user/assistant messages.

    Returns a flat list of dicts with keys: uuid, session_id, role, content, timestamp.
    Sorted by timestamp across all files.
    """
    messages: list[dict[str, str]] = []
    jsonl_files = sorted(directory.rglob("*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL file(s) under {directory}", file=sys.stderr)

    for path in jsonl_files:
        # Skip macOS resource fork files
        if "/__MACOSX/" in str(path):
            continue

        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type", "")
                if entry_type not in ("user", "assistant"):
                    continue

                raw_content = entry.get("message", {}).get("content", "")
                content = extract_content(raw_content)
                if not content:
                    continue

                messages.append({
                    "uuid": entry.get("uuid", ""),
                    "session_id": entry.get("sessionId", path.stem),
                    "role": entry_type,
                    "content": content,
                    "timestamp": entry.get("timestamp", ""),
                })

    messages.sort(key=lambda m: m["timestamp"])
    print(f"Extracted {len(messages)} message(s) from {len(jsonl_files)} file(s)", file=sys.stderr)
    return messages


# ── API Calls ────────────────────────────────────────────────────────────────
async def send_to_mem0(session: aiohttp.ClientSession, role: str, content: str) -> dict[str, Any] | None:
    """Send a message to Mem0 REST API with infer=true.

    Returns the response JSON dict (contains 'id' field) or None if Mem0
    returned null (deduplicated/merged).
    """
    text = f"{role}: {content}"
    async with session.post(
        f"{MEM0_URL}/api/v1/memories/",
        json={
            "user_id": USER_ID,
            "text": text,
            "app": "openmemory",
            "infer": True,
        },
        timeout=aiohttp.ClientTimeout(total=120),
    ) as resp:
        resp.raise_for_status()
        body = await resp.json()
        if body is None:
            return None
        return body


async def patch_qdrant_timestamp(session: aiohttp.ClientSession, mem0_id: str, timestamp: str) -> None:
    """Patch created_at and updated_at in Qdrant for a given point.

    Uses POST (set_payload / merge) — NOT PUT which replaces the entire payload.
    """
    async with session.post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
        json={
            "points": [mem0_id],
            "payload": {
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        },
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        resp.raise_for_status()


# ── Progress Tracking ────────────────────────────────────────────────────────
def load_progress(path: Path | None) -> dict[str, str | None]:
    """Load progress file. Returns dict mapping message UUID -> mem0 ID (or None)."""
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path | None, progress: dict[str, str | None]) -> None:
    """Write progress file."""
    if path is None:
        return
    path.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Async Worker ─────────────────────────────────────────────────────────────
async def process_message(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    msg: dict[str, str],
    index: int,
    total: int,
) -> tuple[str, str | None, str]:
    """Process a single message: send to Mem0, patch Qdrant.

    Returns (uuid, mem0_id_or_None, status) where status is one of:
    'success', 'null', 'error'.
    """
    uuid = msg["uuid"]
    session_short = msg["session_id"][:8]
    role = msg["role"]
    ts = msg["timestamp"]
    content = msg["content"]

    async with semaphore:
        # Send to Mem0
        try:
            result = await send_to_mem0(session, role, content)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            print(f"[{index:4d}/{total}] session:{session_short} | {role:9s} | {ts} | ERROR: {exc}",
                  file=sys.stderr)
            return (uuid, None, "error")

        if result is None:
            print(f"[{index:4d}/{total}] session:{session_short} | {role:9s} | {ts} | "
                  f"WARNING: null response — possibly deduplicated/merged")
            return (uuid, None, "null")

        mem0_id = result.get("id", "")

        # Patch Qdrant timestamp
        try:
            await patch_qdrant_timestamp(session, mem0_id, ts)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            print(f"[{index:4d}/{total}] session:{session_short} | {role:9s} | {ts} | "
                  f"QDRANT PATCH ERROR: {exc}", file=sys.stderr)

        print(f"[{index:4d}/{total}] session:{session_short} | {role:9s} | {ts} | mem0_id: {mem0_id}")
        return (uuid, mem0_id, "success")


# ── Main Loop ────────────────────────────────────────────────────────────────
async def inject(messages: list[dict[str, str]], *, dry_run: bool = False,
                 progress_path: Path | None = None, concurrency: int = 5) -> None:
    """Send messages to Mem0 and patch Qdrant timestamps."""
    progress = load_progress(progress_path)
    total = len(messages)
    skipped = 0
    successes = 0
    failures = 0
    nulls = 0

    # Filter out already-processed messages
    pending: list[tuple[int, dict[str, str]]] = []
    for i, msg in enumerate(messages, start=1):
        if msg["uuid"] in progress:
            skipped += 1
        elif dry_run:
            session_short = msg["session_id"][:8]
            print(f"[{i:4d}/{total}] session:{session_short} | {msg['role']:9s} | {msg['timestamp']} | {msg['content'][:60]}")
        else:
            pending.append((i, msg))

    if dry_run or not pending:
        if skipped:
            print(f"\nSkipped {skipped} already-processed message(s).", file=sys.stderr)
        if dry_run:
            return
        if not pending:
            print(f"\nDone. {successes} succeeded, {nulls} null responses, "
                  f"{failures} failed, {skipped} skipped (already processed).", file=sys.stderr)
            return

    print(f"Processing {len(pending)} message(s) with concurrency={concurrency} "
          f"({skipped} skipped)...", file=sys.stderr)

    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession() as session:
        # Process in batches for progress saving
        batch_size = concurrency * 2
        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start:batch_start + batch_size]

            tasks = [
                process_message(session, semaphore, msg, idx, total)
                for idx, msg in batch
            ]
            results = await asyncio.gather(*tasks)

            # Update progress after each batch
            for uuid, mem0_id, status in results:
                if status == "success":
                    successes += 1
                    progress[uuid] = mem0_id
                elif status == "null":
                    nulls += 1
                    progress[uuid] = None
                else:
                    failures += 1

            save_progress(progress_path, progress)

    print(f"\nDone. {successes} succeeded, {nulls} null responses, "
          f"{failures} failed, {skipped} skipped (already processed).", file=sys.stderr)
    if nulls > 0:
        print(f"WARNING: {nulls} message(s) returned null from Mem0. "
              f"These were likely deduplicated or merged with existing memories.",
              file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inject Claude Code JSONL sessions into Mem0 via REST API."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        required=True,
        metavar="DIRECTORY",
        help="Recursively scan for *.jsonl files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without calling APIs",
    )
    parser.add_argument(
        "--progress",
        type=Path,
        metavar="FILE",
        help="JSON file tracking processed message UUIDs for resume support",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        metavar="N",
        help="Number of concurrent requests (default: 5)",
    )
    args = parser.parse_args()

    if not args.dir.is_dir():
        print(f"Error: {args.dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    messages = extract_messages(args.dir)
    if not messages:
        print("No messages found.", file=sys.stderr)
        sys.exit(0)

    asyncio.run(inject(messages, dry_run=args.dry_run, progress_path=args.progress,
                        concurrency=args.concurrency))


if __name__ == "__main__":
    main()
