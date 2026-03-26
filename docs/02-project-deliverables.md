# Project Deliverables

## Agentic system memory integration

### MCP Tool Interfaces

Each memory system exposes a different MCP interface, which determines how an agentic system interacts with it in practice. The following is grounded in the source code of each MCP server (as of 2026-03-26).

---

### Mem0 (OpenMemory MCP) — `mem0/openmemory-mcp`

5 tools. Designed for **short, fact-like statements**.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add_memories` | `text: str`, `infer: bool = True` | Store a memory. When `infer=True`, Mem0's LLM extracts facts from the text. |
| `search_memory` | `query: str` | Semantic search across stored memories. |
| `list_memories` | — | List all memories for the user. |
| `delete_memories` | `memory_ids: list[str]` | Delete specific memories by UUID. |
| `delete_all_memories` | — | Delete all memories. |

- **User/app context** (`user_id`, `client_name`) is injected via URL context variables, not as tool parameters.
- **Input model**: Individual short text statements. Not designed for bulk conversation ingestion. `infer=True` can handle slightly longer text and extract facts from it.

---

### Graphiti MCP (Zep) — `zepai/knowledge-graph-mcp`

9 tools. Designed for **conversation episodes** — the most conversation-native of the three.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `add_memory` | `name: str`, `episode_body: str`, `group_id: str \| None`, `source: "text" \| "json" \| "message"`, `source_description: str`, `uuid: str \| None` | Add an episode to the knowledge graph. Primary ingestion method. |
| `search_nodes` | `query: str`, `group_ids: list[str] \| None`, `max_nodes: int = 10`, `entity_types: list[str] \| None` | Search for entity nodes in the graph. |
| `search_memory_facts` | `query: str`, `group_ids: list[str] \| None`, `max_facts: int = 10`, `center_node_uuid: str \| None` | Search for facts (relationships/edges between entities). |
| `get_entity_edge` | `uuid: str` | Get a specific entity edge by UUID. |
| `get_episodes` | `group_ids: list[str] \| None`, `max_episodes: int = 10` | List recent episodes. |
| `delete_entity_edge` | `uuid: str` | Delete a specific entity edge. |
| `delete_episode` | `uuid: str` | Delete a specific episode. |
| `clear_graph` | `group_ids: list[str] \| None` | Clear all data for specified group IDs. |
| `get_status` | — | Check server and database connection status. |

- **Input model**: Episodes — full conversation chunks, JSON, or message-formatted content. `source="message"` is the conversation-native mode.
- Graphiti internally performs entity extraction, relationship detection, deduplication, and temporal tracking.

---

### Cognee MCP — `cognee/cognee-mcp`

7 tools. Designed for **documents, text blobs, and interaction logs**.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `cognify` | `data: str`, `graph_model_file: str \| None`, `graph_model_name: str \| None`, `custom_prompt: str \| None` | Transform data into a structured knowledge graph. Runs as a background task. Accepts raw text, file paths, CSV, JSON. |
| `save_interaction` | `data: str` | Log a user-agent interaction. Processes it into the knowledge graph and generates associated rules. Background task. |
| `search` | `search_query: str`, `search_type: str`, `top_k: int = 10` | Search the knowledge graph. `search_type` options: `GRAPH_COMPLETION`, `RAG_COMPLETION`, `CHUNKS`, `SUMMARIES`, `CODE`, `CYPHER`, `FEELING_LUCKY`. |
| `list_data` | `dataset_id: str \| None` | List all datasets and their data items. |
| `delete` | `data_id: str`, `dataset_id: str`, `mode: str = "soft"` | Delete specific data. Supports `"soft"` and `"hard"` modes. |
| `prune` | — | Reset the entire knowledge graph. |
| `cognify_status` | — | Check the status of a running cognify pipeline. |

- **Input model**: Raw text blobs, documents, file paths, or interaction logs. Processing is asynchronous — use `cognify_status` to check progress.
- `save_interaction` is specifically for user-agent Q&A pairs.
- `cognify` runs a full pipeline: document classification, text chunking, entity extraction, relationship detection, graph construction, summarization.

---

### Implications for data preparation

The three systems want fundamentally different input formats:

| System | Realistic input | What to feed it |
|--------|----------------|-----------------|
| **Mem0** | Individual statements/observations | Short fact-like strings, one at a time. `infer=True` can handle slightly longer text. |
| **Graphiti** | Conversation episodes | Whole conversation chunks with `source="message"`. Extracts entities/relations itself. |
| **Cognee** | Documents or interaction logs | Raw text blobs via `cognify()` or Q&A pairs via `save_interaction()`. |

The data preparation pipeline should produce **conversation segments** (the most natural form), with each system-specific loader adapting the format for its MCP interface. This ensures the benchmark reflects realistic usage rather than artificially pre-digesting the data.
