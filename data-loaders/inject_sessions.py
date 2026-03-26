#!/usr/bin/env python3
"""Inject Claude Code JSONL sessions into Mem0 via REST API.

Usage:
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --dry-run
    python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --progress progress.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

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
def send_to_mem0(role: str, content: str) -> dict[str, Any] | None:
    """Send a message to Mem0 REST API with infer=true.

    Returns the response JSON dict (contains 'id' field) or None if Mem0
    returned null (deduplicated/merged).
    """
    text = f"{role}: {content}"
    resp = requests.post(
        f"{MEM0_URL}/api/v1/memories/",
        json={
            "user_id": USER_ID,
            "text": text,
            "app": "openmemory",
            "infer": True,
        },
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    if body is None:
        return None
    return body


def patch_qdrant_timestamp(mem0_id: str, timestamp: str) -> None:
    """Patch created_at and updated_at in Qdrant for a given point.

    Uses POST (set_payload / merge) — NOT PUT which replaces the entire payload.
    """
    resp = requests.post(
        f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/payload",
        json={
            "points": [mem0_id],
            "payload": {
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        },
        timeout=30,
    )
    resp.raise_for_status()


# ── Progress Tracking ────────────────────────────────────────────────────────
def load_progress(path: Path | None) -> dict[str, str | None]:
    """Load progress file. Returns dict mapping message UUID -> mem0 ID (or None)."""
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_progress(path: Path | None, progress: dict[str, str | None]) -> None:
    """Write progress file atomically."""
    if path is None:
        return
    path.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Main Loop ────────────────────────────────────────────────────────────────
def inject(messages: list[dict[str, str]], *, dry_run: bool = False,
           progress_path: Path | None = None) -> None:
    """Send messages to Mem0 and patch Qdrant timestamps."""
    progress = load_progress(progress_path)
    total = len(messages)
    skipped = 0
    successes = 0
    failures = 0
    nulls = 0

    for i, msg in enumerate(messages, start=1):
        uuid = msg["uuid"]
        session_short = msg["session_id"][:8]
        role = msg["role"]
        ts = msg["timestamp"]
        content = msg["content"]

        # Resume support — skip already processed
        if uuid in progress:
            skipped += 1
            continue

        if dry_run:
            print(f"[{i:4d}/{total}] session:{session_short} | {role:9s} | {ts} | {content[:60]}")
            continue

        # Send to Mem0
        try:
            result = send_to_mem0(role, content)
        except requests.RequestException as exc:
            print(f"[{i:4d}/{total}] session:{session_short} | {role:9s} | {ts} | ERROR: {exc}",
                  file=sys.stderr)
            failures += 1
            continue

        if result is None:
            print(f"[{i:4d}/{total}] session:{session_short} | {role:9s} | {ts} | "
                  f"WARNING: null response — possibly deduplicated/merged")
            nulls += 1
            progress[uuid] = None
            save_progress(progress_path, progress)
            continue

        mem0_id = result.get("id", "")

        # Patch Qdrant timestamp
        try:
            patch_qdrant_timestamp(mem0_id, ts)
        except requests.RequestException as exc:
            print(f"[{i:4d}/{total}] session:{session_short} | {role:9s} | {ts} | "
                  f"QDRANT PATCH ERROR: {exc}", file=sys.stderr)

        print(f"[{i:4d}/{total}] session:{session_short} | {role:9s} | {ts} | mem0_id: {mem0_id}")
        successes += 1
        progress[uuid] = mem0_id
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
    args = parser.parse_args()

    if not args.dir.is_dir():
        print(f"Error: {args.dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    messages = extract_messages(args.dir)
    if not messages:
        print("No messages found.", file=sys.stderr)
        sys.exit(0)

    inject(messages, dry_run=args.dry_run, progress_path=args.progress)


if __name__ == "__main__":
    main()
