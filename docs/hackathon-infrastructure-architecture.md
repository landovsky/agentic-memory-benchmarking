# 🏗️ Hackathon Infrastructure Architecture
## Memory Systems Benchmark — Setup Guide pro vedoucího projektu

---

## 1. Síťová topologie

```
┌─────────────────────────────────────────────────────────────┐
│                    LOKÁLNÍ SÍŤ (LAN)                        │
│                                                             │
│  ┌──────────────────────────────────────┐                   │
│  │  🖥️ HOSTITELSKÝ STROJ (tvůj počítač) │                   │
│  │                                      │                   │
│  │  Docker Compose stack:               │                   │
│  │  ┌────────────┐  ┌───────────────┐   │                   │
│  │  │ PostgreSQL  │  │    Qdrant     │   │                   │
│  │  │  :5432      │  │    :6333      │   │                   │
│  │  └────────────┘  └───────────────┘   │                   │
│  │  ┌────────────┐  ┌───────────────┐   │                   │
│  │  │   Neo4j    │  │  Mem0 API     │   │                   │
│  │  │  :7474     │  │    :8080      │   │                   │
│  │  │  :7687     │  │               │   │                   │
│  │  └────────────┘  └───────────────┘   │                   │
│  │  ┌────────────┐  ┌───────────────┐   │                   │
│  │  │ Graphiti   │  │  Cognee API   │   │                   │
│  │  │ MCP :8050  │  │    :8000      │   │                   │
│  │  └────────────┘  └───────────────┘   │                   │
│  │                                      │                   │
│  │  ┌────────────────────────────────┐  │                   │
│  │  │  📁 Sdílený data server        │  │                   │
│  │  │  (HTTP :9000 nebo SMB/NFS)     │  │                   │
│  │  │  - test_data/                  │  │                   │
│  │  │  - eval_results/               │  │                   │
│  │  └────────────────────────────────┘  │                   │
│  └──────────────────────────────────────┘                   │
│           │          │           │          │                │
│     ┌─────┴──┐ ┌─────┴──┐ ┌─────┴──┐ ┌────┴───┐           │
│     │ Člen 1 │ │ Člen 2 │ │ Člen 3 │ │ Člen 4 │           │
│     │ (ty)   │ │        │ │        │ │        │           │
│     │ CC/OC  │ │ CC/OC  │ │ CC/OC  │ │ CC/OC  │           │
│     └────────┘ └────────┘ └────────┘ └────────┘           │
│     CC = Claude Code    OC = OpenClaw                       │
└─────────────────────────────────────────────────────────────┘
```

**Kritické:** Všechny DB služby musí naslouchat na `0.0.0.0`, ne jen `localhost`.

---

## 2. Docker Compose — centrální stack

```yaml
# docker-compose.yml — hostitelský stroj
version: "3.9"

services:
  # ══════════════════════════════════════
  # SDÍLENÁ INFRASTRUKTURA
  # ══════════════════════════════════════
  
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "0.0.0.0:5432:5432"
    environment:
      POSTGRES_USER: hackathon
      POSTGRES_PASSWORD: hackathon2025
      POSTGRES_DB: memory_benchmark
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hackathon"]
      interval: 5s
      retries: 5

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "0.0.0.0:6333:6333"
      - "0.0.0.0:6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

  neo4j:
    image: neo4j:5-community
    ports:
      - "0.0.0.0:7474:7474"   # Web UI
      - "0.0.0.0:7687:7687"   # Bolt
    environment:
      NEO4J_AUTH: neo4j/hackathon2025
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j_data:/data

  # ══════════════════════════════════════
  # MEMORY SYSTEM 1: Mem0 (OpenMemory)
  # ══════════════════════════════════════
  
  mem0-api:
    image: mem0ai/mem0:latest  # ověřit přesný tag před akcí!
    ports:
      - "0.0.0.0:8080:8080"
    environment:
      DATABASE_URL: postgresql://hackathon:hackathon2025@postgres:5432/mem0
      QDRANT_URL: http://qdrant:6333
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy
      qdrant:
        condition: service_started

  # ══════════════════════════════════════
  # MEMORY SYSTEM 2: Graphiti (Zep OSS)
  # ══════════════════════════════════════
  
  graphiti-mcp:
    build:
      context: ./graphiti-mcp
      dockerfile: Dockerfile
    ports:
      - "0.0.0.0:8050:8050"
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: hackathon2025
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    depends_on:
      - neo4j

  # ══════════════════════════════════════
  # MEMORY SYSTEM 3: Cognee
  # ══════════════════════════════════════
  
  cognee-api:
    build:
      context: ./cognee-service
      dockerfile: Dockerfile
    ports:
      - "0.0.0.0:8000:8000"
    environment:
      DATABASE_URL: postgresql://hackathon:hackathon2025@postgres:5432/cognee
      LLM_API_KEY: ${OPENAI_API_KEY}
    depends_on:
      postgres:
        condition: service_healthy

  # ══════════════════════════════════════
  # UTILITA: jednoduchý HTTP file server
  # ══════════════════════════════════════
  
  fileserver:
    image: halverneus/static-file-server:latest
    ports:
      - "0.0.0.0:9000:8080"
    volumes:
      - ./shared-data:/web
    environment:
      FOLDER: /web

volumes:
  pg_data:
  qdrant_data:
  neo4j_data:
```

---

## 3. Init skripty — databáze

```sql
-- init-scripts/01_create_databases.sql
-- Postgres init: separátní DB pro každý systém

CREATE DATABASE mem0;
CREATE DATABASE cognee;
CREATE DATABASE eval_results;

-- pgvector extension ve všech DB
\c mem0
CREATE EXTENSION IF NOT EXISTS vector;

\c cognee
CREATE EXTENSION IF NOT EXISTS vector;

\c eval_results
CREATE EXTENSION IF NOT EXISTS vector;

-- Eval results tabulka pro ukládání výsledků
\c eval_results
CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    system_name TEXT NOT NULL,        -- 'mem0', 'graphiti', 'cognee'
    test_case_id TEXT NOT NULL,
    dimension TEXT NOT NULL,          -- 'recall', 'temporal', 'relevance'...
    memory_type TEXT,                 -- 'preference', 'episodic', 'semantic', 'goal'
    query TEXT NOT NULL,
    expected_answer TEXT,
    actual_answer TEXT,
    score NUMERIC(3,2),              -- 0.00 – 1.00
    latency_ms INTEGER,
    notes TEXT,
    run_timestamp TIMESTAMPTZ DEFAULT NOW(),
    runner TEXT                       -- kdo test spustil
);

CREATE INDEX idx_eval_system ON eval_runs(system_name);
CREATE INDEX idx_eval_dimension ON eval_runs(dimension);
```

---

## 4. Adresářová struktura repozitáře

```
memory-benchmark/
├── README.md                    # Quickstart pro účastníky
├── docker-compose.yml           # Hlavní stack
├── .env.example                 # Template pro API klíče
├── .env                         # (gitignored) skutečné klíče
│
├── init-scripts/
│   └── 01_create_databases.sql
│
├── shared-data/                 # HTTP server na :9000
│   ├── test-sessions/           # Anonymizované JSONL sessions
│   │   ├── project-hristehrou/  # Sessions z Hřiště Hrou
│   │   ├── project-medicmee/    # Sessions z MedicMee
│   │   └── project-pharmacy/    # Sessions z Pharmacy
│   ├── test-cases/
│   │   ├── test_cases.csv       # Master test case soubor
│   │   └── test_cases.json      # Alternativní JSON formát
│   └── eval-results/            # Výsledky evaluací (zapisují členové)
│
├── data-loaders/                # Skripty pro import dat
│   ├── jsonl_parser.py          # Parsuje CC JSONL → čistý formát
│   ├── memory_extractor.py      # LLM extrahuje memorizable fakta
│   ├── load_mem0.py             # Import do Mem0
│   ├── load_graphiti.py         # Import do Graphiti
│   └── load_cognee.py           # Import do Cognee
│
├── eval-harness/                # Evaluační framework
│   ├── runner.py                # Hlavní runner — čte CSV, spouští testy
│   ├── scorers.py               # LLM-as-judge + exact match scoring
│   ├── report.py                # Generuje HTML report z výsledků
│   └── templates/
│       └── report.html
│
├── mcp-configs/                 # Předpřipravené MCP konfigurace
│   ├── mem0.mcp.json
│   ├── graphiti.mcp.json
│   └── cognee.mcp.json
│
├── graphiti-mcp/                # Build context pro Graphiti
│   └── Dockerfile
├── cognee-service/              # Build context pro Cognee
│   └── Dockerfile
│
└── presentation/                # Finální prezentace
    └── findings.md
```

---

## 5. Test Cases — formát a distribuce

### CSV formát (Google Sheet → Published CSV)

```csv
id,dimension,memory_type,project_scope,setup_memory,query,expected_answer,scoring_method,notes
TC-001,recall,preference,global,"Uživatel preferuje Tailwind před Bootstrapem","Jaký CSS framework mám rád?","Tailwind",exact_contains,Základní preference recall
TC-002,recall,semantic,medicmee,"MedicMee používá Rails 7.1 s PostgreSQL a Hotwire","Jaký tech stack používá MedicMee?","Rails 7.1, PostgreSQL, Hotwire",llm_judge,Semantická paměť - projektové fakta
TC-003,temporal,semantic,hristehrou,"V lednu: HH používá Bootstrap. V březnu: Přešli na Tailwind.","Jaký CSS framework aktuálně používá Hřiště Hrou?","Tailwind (přešli z Bootstrap)",llm_judge,Temporal - rozpoznání aktualizace
TC-004,isolation,preference,pharmacy,"Pharmacy: deploy přes K3s. MedicMee: deploy přes Dokku.","Jak deployujeme Pharmacy?","K3s",exact_contains,Izolace projektů
TC-005,hallucination,_,global,"(žádná paměť o Reactu)","Jakou React verzi používám?","Nevím / nemám info",llm_judge_negation,Anti-halucinace - systém NEMÁ odpovídat
TC-006,proactive,episodic,medicmee,"3. března: Řešili jsme timeout PostgreSQL - opraveno zvýšením pool size na 25","Mám problém s timeouty DB připojení v MedicMee","Měl by proaktivně zmínit předchozí řešení (pool size 25)",llm_judge,Proaktivní využití epizodické paměti
TC-007,temporal,goal,hristehrou,"Q1: Cíl vydat HH ERP do konce Q2. Konec Q1: Posun cíle na Q3.","Kdy má být hotový HH ERP?","Q3 (původně Q2, posunuto)",llm_judge,Temporal - aktualizace cíle
TC-008,scale,semantic,global,"(100 memories loaded)","Jaký je deployment postup pro MedicMee?","Dokku na VPS",exact_contains,Baseline - 100 záznamů
TC-009,scale,semantic,global,"(1000 memories loaded)","Jaký je deployment postup pro MedicMee?","Dokku na VPS",exact_contains,Scale test - 1000 záznamů
TC-010,type_distinction,preference+episodic,global,"Preference: Rád používám Tailwind. Epizodická: Včera jsem musel použít Bootstrap kvůli legacy klientovi.","Jaký CSS framework preferuji?","Tailwind (i když včera použil Bootstrap - to byla výjimka)",llm_judge,Rozlišení preference vs. epizodická
```

### Distribuce test cases

**Varianta A: GitHub (tech-savvy tým)**
```
shared-data/test-cases/test_cases.csv  →  v repozitáři
```
Členové pullnou repo, runner.py čte lokální soubor.

**Varianta B: Google Sheet (mixed tým)**
```
Google Sheet → File → Share → Publish to Web → CSV
URL: https://docs.google.com/spreadsheets/d/SHEET_ID/export?format=csv
```
Runner.py stáhne CSV přes HTTP — žádný git potřeba:
```python
import requests, csv, io

SHEET_URL = "https://docs.google.com/spreadsheets/d/SHEET_ID/export?format=csv"

def load_test_cases():
    response = requests.get(SHEET_URL)
    reader = csv.DictReader(io.StringIO(response.text))
    return list(reader)
```

**Varianta C: HTTP file server (fallback)**
```
http://HOST_IP:9000/test-cases/test_cases.csv
```

---

## 6. Claude Code JSONL — datová pipeline

### Struktura CC JSONL session souborů

```
~/.claude/projects/<project-hash>/sessions/<session-id>.jsonl
```

Každý řádek je JSON objekt:
```json
{"type":"user","message":{"role":"user","content":"Fix the auth bug"},"timestamp":"2026-03-20T10:00:01Z","sessionId":"a1b2c3d4-..."}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"..."},{"type":"tool_use","id":"tu_1","name":"Read","input":{"file_path":"src/auth.ts"}}]},"timestamp":"...","sessionId":"..."}
{"type":"tool_result","tool_use_id":"tu_1","content":"export function validateToken...","timestamp":"...","sessionId":"..."}
```

### Pipeline: JSONL → Memory-worthy facts

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐
│  CC JSONL     │────▶│  jsonl_parser.py  │────▶│ memory_extractor│────▶│  load_*.py   │
│  sessions     │     │  (čistí, filtruje │     │  (LLM extrahuje │     │  (importuje  │
│  (~/.claude/) │     │   user+assistant) │     │   fakta, prefs,  │     │   do Mem0,   │
└──────────────┘     └──────────────────┘     │   rozhodnutí)    │     │   Graphiti,  │
                                               └─────────────────┘     │   Cognee)    │
                                                                        └──────────────┘
```

### Krok 1: jsonl_parser.py — extrakce konverzací

```python
#!/usr/bin/env python3
"""Parsuje Claude Code JSONL sessions do čistého formátu."""

import json, glob, os
from pathlib import Path
from datetime import datetime

def parse_session(jsonl_path: str) -> dict:
    """Parsuje jeden JSONL session soubor."""
    messages = []
    session_id = None
    
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            msg_type = entry.get("type")
            timestamp = entry.get("timestamp")
            session_id = session_id or entry.get("sessionId")
            
            if msg_type == "user":
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, str) and content.strip():
                    messages.append({
                        "role": "user",
                        "content": content,
                        "timestamp": timestamp
                    })
            
            elif msg_type == "assistant":
                content_blocks = entry.get("message", {}).get("content", [])
                text_parts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif isinstance(block, str):
                        text_parts.append(block)
                
                if text_parts:
                    messages.append({
                        "role": "assistant",
                        "content": "\n".join(text_parts),
                        "timestamp": timestamp
                    })
    
    return {
        "session_id": session_id,
        "file": str(jsonl_path),
        "message_count": len(messages),
        "messages": messages,
        "first_timestamp": messages[0]["timestamp"] if messages else None,
        "last_timestamp": messages[-1]["timestamp"] if messages else None,
    }


def collect_all_sessions(claude_dir: str = "~/.claude/projects") -> list:
    """Sbírá všechny sessions ze všech projektů."""
    claude_dir = os.path.expanduser(claude_dir)
    sessions = []
    
    for jsonl_file in glob.glob(f"{claude_dir}/**/sessions/*.jsonl", recursive=True):
        session = parse_session(jsonl_file)
        if session["message_count"] > 0:
            # Extrahuj project hash z cesty
            parts = Path(jsonl_file).parts
            project_hash = parts[parts.index("projects") + 1] if "projects" in parts else "unknown"
            session["project_hash"] = project_hash
            sessions.append(session)
    
    return sorted(sessions, key=lambda s: s["first_timestamp"] or "")
```

### Krok 2: memory_extractor.py — LLM extrakce faktů

```python
#!/usr/bin/env python3
"""LLM-based extraction of memory-worthy facts from sessions."""

EXTRACTION_PROMPT = """Analyze this coding session conversation and extract memory-worthy facts.

For EACH fact, classify it as one of:
- preference: Stable user preferences (tools, frameworks, coding style)
- episodic: Time-bound events (bugs fixed, decisions made, problems solved)  
- semantic: Current project state (tech stack, architecture, configurations)
- goal: Long-term objectives (deadlines, milestones, roadmap items)

Return JSON array:
[
  {
    "type": "preference|episodic|semantic|goal",
    "fact": "concise statement of the fact",
    "project": "project name or null if global",
    "confidence": 0.0-1.0,
    "timestamp": "ISO timestamp from conversation or null"
  }
]

Only extract facts that would be USEFUL to remember in future sessions.
Skip: greetings, debugging noise, tool outputs, generic coding patterns.

CONVERSATION:
{conversation}
"""
```

### Krok 3: load_*.py — import do systémů

Každý systém potřebuje vlastní loader kvůli odlišnému API:

```python
# Mem0: memory.add(messages, user_id=..., metadata={...})
# Graphiti: client.add_episode(name=..., body=..., source_description=..., reference_time=...)
# Cognee: await cognee.add(text, dataset_name=...) → await cognee.cognify()
```

---

## 7. MCP konfigurace pro účastníky

Každý účastník si přidá do svého `.mcp.json` nebo Claude Code config:

```json
// mcp-configs/mem0.mcp.json
// Účastník nahradí HOST_IP za IP hostitelského stroje
{
  "mcpServers": {
    "mem0": {
      "transport": "sse",
      "url": "http://HOST_IP:8080/sse"
    }
  }
}
```

```json
// mcp-configs/graphiti.mcp.json
{
  "mcpServers": {
    "graphiti": {
      "transport": "sse", 
      "url": "http://HOST_IP:8050/sse"
    }
  }
}
```

**Tip:** Přichystej `setup.sh` skript, který nahradí HOST_IP automaticky:

```bash
#!/bin/bash
# setup-mcp.sh — spustí účastník na svém stroji
HOST_IP="${1:-192.168.1.100}"  # argument nebo default

mkdir -p ~/.claude/mcp-configs/
for config in mem0 graphiti cognee; do
  sed "s/HOST_IP/$HOST_IP/g" "mcp-configs/${config}.mcp.json" \
    > ~/.claude/mcp-configs/${config}.json
  echo "✅ ${config} MCP configured → ${HOST_IP}"
done

echo ""
echo "Přidej do svého .mcp.json nebo spusť:"
echo "  claude mcp add --transport sse mem0 http://${HOST_IP}:8080/sse"
echo "  claude mcp add --transport sse graphiti http://${HOST_IP}:8050/sse"
```

---

## 8. Co ještě zvážit — checklist

### 🔑 API klíče a náklady
- [ ] **OpenAI API klíč** — všechny 3 systémy ho potřebují pro embeddings + LLM extraction
- [ ] **Rozpočet:** Mem0 default = GPT-4.1-nano (levný). Graphiti = HODNĚ API calls (varovat tým!). Cognee = konfigurovatelný LLM
- [ ] **Alternativa:** Cognee podporuje Ollama (lokální, zdarma) — zvážit pro snížení nákladů
- [ ] **Jeden sdílený klíč** na .env hostitelského stroje, nebo každý účastník vlastní?
- [ ] **Anthropic API klíč** — pokud budete eval runner dělat přes Claude jako judge

### 🗃️ Anonymizace dat
- [ ] **PŘED hackathhonem:** Projít JSONL sessions a anonymizovat:
  - Jména klientů, URLs, API klíče, DB credentials
  - Interní firemní informace z Pharmacy
  - Osobní údaje pacientů pokud jsou v MedicMee datech
- [ ] Skript na anonymizaci: `sed`, `jq`, nebo Python regex
- [ ] **Alternativa:** Syntetická data — vygenerovat realistické sessions místo použití skutečných

### 🌐 Síť a konektivita
- [ ] **Zjistit IP** hostitelského stroje: `ip addr show` / `ifconfig`
- [ ] **Firewall:** Otevřít porty 5432, 6333, 7474, 7687, 8000, 8050, 8080, 9000
- [ ] **DNS/mDNS:** Alternativně hostname místo IP (jednodušší pokud se změní)
- [ ] **Backup:** Hotspot z telefonu pokud LAN selže
- [ ] **Test konektivity:** `curl http://HOST_IP:8080/health` z jiného stroje

### 🧪 Eval harness — jak členové zapisují výsledky
- [ ] **Varianta 1 (jednoduchá):** Google Sheet — každý člen má svůj sheet/tab
- [ ] **Varianta 2 (robustní):** Python runner zapisuje do sdílené PostgreSQL `eval_results` DB
- [ ] **Varianta 3 (hybrid):** Runner zapisuje do DB + exportuje CSV do Google Sheet
- [ ] Runner musí zaznamenat: **systém, test_case_id, query, odpověď, skóre, latence, čas**

### 👥 Rozdělení práce na hackathonu
```
Člen 1 (ty):     Infra support, troubleshooting, data pipeline
Člen 2:          Mem0 — data loading + eval spouštění
Člen 3:          Graphiti — data loading + eval spouštění  
Člen 4:          Cognee — data loading + eval spouštění
Člen 5 (pokud):  Eval harness, reporting, prezentace
```

### ⏱️ Časový plán (1 den = ~8 hodin)
```
08:00-08:30  Intro, rozdělení, ověření konektivity
08:30-09:30  Data loading do všech 3 systémů (paralelně)
09:30-10:30  Spuštění prvních test cases (smoke test)
10:30-12:00  Systematické eval — recall, relevance, hallucination
12:00-13:00  OBĚD
13:00-14:30  Pokračování eval — temporal, isolation, scale
14:30-15:30  Sběr výsledků, porovnání, diskuze
15:30-16:30  Příprava prezentace + demo
16:30-17:00  5min prezentace + Q&A
```

### 🛡️ Věci co se pokazí (a jak se připravit)
- **Docker image se nestáhne:** Pre-pull VŠECHNY images den předem
- **Port konflikt:** Mít alternativní porty v docker-compose
- **Neo4j nechce nastartovat:** 2GB+ RAM minimum, APOC plugin chce stažení
- **Graphiti žere API kredity:** Nastavit budget alert na OpenAI
- **Účastník nemá Claude Code:** Mít OpenClaw jako fallback
- **WiFi nefunguje:** Ethernet kabel + switch jako záloha
- **Session data jsou příliš velká:** Předpřipravit 3 size varianty (small/medium/large)

### 📋 Pre-flight checklist (den před)
- [ ] `docker compose up -d` — vše startuje bez chyb
- [ ] `docker compose ps` — všechny services healthy
- [ ] Z jiného stroje: `curl http://HOST_IP:8080/health` — Mem0 odpovídá
- [ ] Z jiného stroje: Neo4j UI otevřen na `http://HOST_IP:7474`
- [ ] Test MCP připojení z Claude Code → Mem0
- [ ] JSONL data zparsovaná a ready k importu
- [ ] Test cases CSV dostupné přes HTTP/Google Sheet
- [ ] README v repo je jasné a kompletní
- [ ] Záložní .env soubor na USB flash

---

## 9. Eval Results — uložení a agregace

### PostgreSQL tabulka (automatický sběr)
```python
# eval-harness/runner.py (ukázka)
import psycopg2, time

def run_test_case(system_client, test_case, db_conn):
    start = time.time()
    actual = system_client.search(test_case["query"])
    latency = int((time.time() - start) * 1000)
    
    score = score_answer(
        actual, 
        test_case["expected_answer"],
        method=test_case["scoring_method"]
    )
    
    with db_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO eval_runs 
            (system_name, test_case_id, dimension, memory_type, 
             query, expected_answer, actual_answer, score, latency_ms, runner)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            system_client.name, test_case["id"], test_case["dimension"],
            test_case["memory_type"], test_case["query"], 
            test_case["expected_answer"], actual, score, latency,
            os.environ.get("RUNNER_NAME", "anonymous")
        ))
        db_conn.commit()
```

### Google Sheet fallback (manuální)
Pokud runner nefunguje, manuální zápis do sdíleného sheetu:

| system | test_id | dimension | query | expected | actual | score | latency_ms | notes | runner |
|--------|---------|-----------|-------|----------|--------|-------|------------|-------|--------|

---

## 10. Co NEŘEŠIT na hackathonu

Tyto věci jsou lákavé ale sežerou čas:

- ❌ **Autentizace/autorizace** na DB — jsme na LAN, stačí heslo
- ❌ **CI/CD pipeline** — pushujeme ručně
- ❌ **Hezké UI pro výsledky** — stačí tabulka / jednoduchý HTML report
- ❌ **Optimalizace výkonu** systémů — testujeme defaults
- ❌ **Více než 3 systémy** — lepší hloubka než šířka
- ❌ **Custom embedding modely** — používáme OpenAI defaults
- ❌ **Kubernetes** — Docker Compose stačí pro 1 den
