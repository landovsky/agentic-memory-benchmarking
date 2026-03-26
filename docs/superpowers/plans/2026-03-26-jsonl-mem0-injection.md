# JSONL-to-Mem0 Injection Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a script that ingests Claude Code JSONL session files into Mem0 via REST API, then patches Qdrant timestamps to reflect original session dates.

**Architecture:** Single Python script with three phases: (1) scan & parse JSONL files into a flat message list, (2) send each message to Mem0 REST API with `infer: true`, (3) patch `created_at`/`updated_at` in Qdrant immediately after each insert. Resume support via a progress JSON file keyed by message UUID.

**Tech Stack:** Python 3, `requests`, Mem0 REST API (localhost:8181), Qdrant REST API (localhost:6333)

---

### Task 1: JSONL Parsing — `extract_messages()`

**Files:**
- Create: `data-loaders/inject_sessions.py`

This task builds the JSONL scanning and message extraction logic. Reuses the same `extract_content()` pattern from `data-loaders/jsonl_parser.py` but returns a flat list of messages with UUIDs and timestamps rather than grouped sessions.

- [ ] **Step 1: Create the script with constants, imports, and `extract_content()`**

```python
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
```

- [ ] **Step 2: Add `extract_messages()` that scans a directory and returns a flat message list**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 3: Verify parsing works with a quick dry-run test**

Run:

```bash
python3 -c "
import sys; sys.path.insert(0, 'data-loaders')
from inject_sessions import extract_messages
from pathlib import Path
msgs = extract_messages(Path('tmp/tom-session-data-hotdesk'))
print(f'Total messages: {len(msgs)}')
for m in msgs[:3]:
    print(f\"  {m['session_id'][:8]} | {m['role']:9s} | {m['timestamp']} | {m['content'][:60]}\")
"
```

Expected: prints total message count and first 3 messages with session, role, timestamp, content preview.

- [ ] **Step 4: Commit**

```bash
git add data-loaders/inject_sessions.py
git commit -m "feat: add JSONL parsing for inject_sessions pipeline"
```

---

### Task 2: Mem0 + Qdrant API Calls — `send_to_mem0()` and `patch_qdrant_timestamp()`

**Files:**
- Modify: `data-loaders/inject_sessions.py`

- [ ] **Step 1: Add `send_to_mem0()`**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 2: Add `patch_qdrant_timestamp()`**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add data-loaders/inject_sessions.py
git commit -m "feat: add Mem0 and Qdrant API functions for injection"
```

---

### Task 3: Progress File — `load_progress()` and `save_progress()`

**Files:**
- Modify: `data-loaders/inject_sessions.py`

- [ ] **Step 1: Add progress load/save functions**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add data-loaders/inject_sessions.py
git commit -m "feat: add progress file support for resume"
```

---

### Task 4: Main Loop and CLI — `inject()` and `main()`

**Files:**
- Modify: `data-loaders/inject_sessions.py`

- [ ] **Step 1: Add `inject()` — the main processing loop**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 2: Add `main()` with argparse**

Append to `inject_sessions.py`:

```python
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
```

- [ ] **Step 3: Verify dry-run works end-to-end**

Run:

```bash
python3 data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --dry-run 2>&1 | head -20
```

Expected: prints JSONL scan stats to stderr, then message lines like:
```
[   1/350] session:19339a86 | user      | 2026-03-03T... | message content preview...
```

- [ ] **Step 4: Verify resume support with a small test**

Run:

```bash
python3 data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --dry-run --progress /tmp/test_progress.json 2>&1 | tail -5
```

Expected: completes with summary line. `/tmp/test_progress.json` is NOT created (dry-run doesn't write progress).

- [ ] **Step 5: Commit**

```bash
git add data-loaders/inject_sessions.py
git commit -m "feat: complete inject_sessions.py with main loop and CLI"
```

---

### Task 5: Add `requests` to requirements and update CLAUDE.md

**Files:**
- Modify: `data-loaders/requirements.txt`

- [ ] **Step 1: Add `requests` to data-loaders requirements**

Add to `data-loaders/requirements.txt`:

```
requests>=2.31.0
```

- [ ] **Step 2: Commit**

```bash
git add data-loaders/requirements.txt
git commit -m "chore: add requests dependency for inject_sessions"
```

---

### Task 6: Live Smoke Test

No file changes — validate against the running Mem0 and Qdrant services.

- [ ] **Step 1: Run with a single small session to verify the full pipeline**

Pick the smallest session file (2124d0e5 has 9 messages). Create a temp directory with just that file:

```bash
mkdir -p /tmp/inject_test
cp tmp/tom-session-data-hotdesk/2124d0e5-804b-4064-9109-912d3ee19071.jsonl /tmp/inject_test/
python3 data-loaders/inject_sessions.py --dir /tmp/inject_test --progress /tmp/inject_test_progress.json
```

Expected: messages are sent to Mem0, each prints `mem0_id: <uuid>` or `WARNING: null response`. Progress file is created.

- [ ] **Step 2: Verify timestamps were patched in Qdrant**

```bash
# Pick a mem0_id from the output above and check its Qdrant payload
curl -s -X POST 'http://localhost:6333/collections/openmemory/points' \
  -H 'Content-Type: application/json' \
  -d '{"ids": ["<mem0_id_from_step_1>"], "with_payload": true, "with_vector": false}' | python3 -m json.tool
```

Expected: `created_at` and `updated_at` match the JSONL timestamp (2026-03-26T07:56:...), NOT the current time.

- [ ] **Step 3: Verify resume — re-run the same command**

```bash
python3 data-loaders/inject_sessions.py --dir /tmp/inject_test --progress /tmp/inject_test_progress.json
```

Expected: all messages are skipped (`X skipped (already processed)`), no new API calls.

- [ ] **Step 4: Clean up test data and commit**

```bash
rm -rf /tmp/inject_test /tmp/inject_test_progress.json
git add data-loaders/inject_sessions.py
git commit -m "test: verify inject_sessions pipeline end-to-end"
```

Only commit if any code fixes were needed during smoke testing. Skip this commit if no changes were made.
