#!/usr/bin/env python3
"""Parse Claude Code JSONL session files into clean conversation format.

Usage:
    python jsonl_parser.py --dir /path/to/sessions [--output sessions.json]
    python jsonl_parser.py --file session.jsonl
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def extract_content(content: Any) -> str:
    """Extract text content from a message content field.

    Content can be a plain string or a list of content blocks.
    For assistant messages, only 'text' blocks are extracted.
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


def parse_session_file(path: Path) -> dict[str, Any] | None:
    """Parse a single JSONL session file.

    Returns a session dict or None if the file yields no messages.
    """
    messages: list[dict[str, Any]] = []
    session_id: str | None = None
    timestamps: list[str] = []

    # Attempt to infer project_hash from path
    # Expected layout: ~/.claude/projects/{project_hash}/sessions/{session_id}.jsonl
    project_hash: str | None = None
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "projects" and i + 2 < len(parts):
            project_hash = parts[i + 1]
            break

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

            # Capture session_id from first valid entry
            if session_id is None:
                session_id = entry.get("sessionId")

            ts = entry.get("timestamp")
            if ts:
                timestamps.append(ts)

            raw_content = entry.get("message", {}).get("content", "")
            content = extract_content(raw_content)
            if not content:
                continue

            messages.append(
                {
                    "role": entry_type,
                    "content": content,
                    "timestamp": ts,
                }
            )

    if not messages:
        return None

    return {
        "session_id": session_id or path.stem,
        "file": str(path),
        "project_hash": project_hash,
        "messages": messages,
        "message_count": len(messages),
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
    }


def scan_directory(directory: Path) -> list[dict[str, Any]]:
    """Recursively scan a directory for *.jsonl files and parse each one."""
    sessions: list[dict[str, Any]] = []
    jsonl_files = sorted(directory.rglob("*.jsonl"))
    print(f"Found {len(jsonl_files)} JSONL file(s) under {directory}", file=sys.stderr)
    for path in jsonl_files:
        print(f"  Parsing {path} ...", file=sys.stderr)
        session = parse_session_file(path)
        if session is not None:
            sessions.append(session)
        else:
            print(f"    Skipped (no messages)", file=sys.stderr)
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Claude Code JSONL session files into clean conversation format."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dir",
        type=Path,
        metavar="DIRECTORY",
        help="Recursively scan for *.jsonl files",
    )
    group.add_argument(
        "--file",
        type=Path,
        metavar="FILE",
        help="Process a single JSONL file",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="FILE",
        help="Write JSON output to this file instead of stdout",
    )
    args = parser.parse_args()

    if args.dir:
        if not args.dir.is_dir():
            print(f"Error: {args.dir} is not a directory", file=sys.stderr)
            sys.exit(1)
        sessions = scan_directory(args.dir)
    else:
        if not args.file.is_file():
            print(f"Error: {args.file} does not exist", file=sys.stderr)
            sys.exit(1)
        session = parse_session_file(args.file)
        sessions = [session] if session is not None else []

    print(
        f"Parsed {len(sessions)} session(s) with "
        f"{sum(s['message_count'] for s in sessions)} total message(s).",
        file=sys.stderr,
    )

    output_data = json.dumps(sessions, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output_data, encoding="utf-8")
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output_data)


if __name__ == "__main__":
    main()
