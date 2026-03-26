# JSONL-to-Mem0 Injection Pipeline

## Overview

A single Python script (`data-loaders/inject_sessions.py`) that parses Claude Code JSONL session files, sends each user/assistant message to the Mem0 REST API with `infer: true`, and patches Qdrant timestamps to match the original session dates.

## Constants

```python
MEM0_URL = "http://localhost:8181"
QDRANT_URL = "http://localhost:6333"
QDRANT_COLLECTION = "openmemory"
USER_ID = "hackathon"
```

## Message Extraction Rules

- **Include:** JSONL entries with `type: "user"` or `type: "assistant"`
- **Skip:** `file-history-snapshot`, `progress`, `system`, `last-prompt`, `queue-operation`
- **User messages:** `entry.message.content` is a plain string — use directly
- **Assistant messages:** `entry.message.content` is a list of blocks — extract only `text` type blocks, join with newline. Skip `tool_use`, `thinking`, `signature` blocks.
- **Skip** messages with empty text after extraction
- **Include subagent sessions** — recurse into `subagents/` directories

## Per-Message Flow

```
JSONL entry (timestamp T, uuid U)
  → extract text content
  → POST {MEM0_URL}/api/v1/memories/
      { user_id: "hackathon", text: "<role>: <content>", app: "openmemory", infer: true }
  → response: { id: "uuid", ... } or null
  → if response is null:
      log WARNING: Mem0 returned null for message U — possibly deduplicated/merged
  → if id returned:
      POST {QDRANT_URL}/collections/openmemory/points/payload
        { points: ["<mem0_id>"], payload: { created_at: T, updated_at: T } }
```

### Message Text Format

Prefix with role: `"user: <content>"` or `"assistant: <content>"`

## CLI Interface

```bash
python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk
python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --dry-run
python data-loaders/inject_sessions.py --dir tmp/tom-session-data-hotdesk --progress inject_progress.json
```

Arguments:
- `--dir` (required) — directory to recursively scan for `*.jsonl` files
- `--dry-run` (optional) — print what would be sent without calling APIs
- `--progress` (optional) — path to JSON file tracking processed message UUIDs for resume support

## Resume Support

- Maintain a JSON progress file mapping processed message UUIDs to their Mem0 memory IDs (or `null`)
- On re-run, skip already-processed UUIDs
- Progress file is written incrementally after each successful API call

## Output Format

```
[  1/350] session:8538b676 | user    | 2026-03-03T06:53:27Z | mem0_id: abc123
[  2/350] session:8538b676 | assistant | 2026-03-03T06:54:36Z | mem0_id: def456
[  3/350] session:8538b676 | user    | 2026-03-03T06:55:31Z | WARNING: null response
```

## Error Handling

- HTTP errors from Mem0 or Qdrant: log error, continue to next message
- Null Mem0 response: log warning, skip Qdrant patch, continue
- Invalid JSONL lines: skip silently (same as existing `jsonl_parser.py`)

## API Details

- **Mem0 add:** `POST /api/v1/memories/` — returns `{id, content, created_at, ...}` or `null`
- **Qdrant patch:** `POST /collections/openmemory/points/payload` (merge, preserves existing fields). Must use POST not PUT — PUT replaces entire payload.

## Dependencies

- Python 3 stdlib + `requests` (no `mem0ai` SDK needed)
