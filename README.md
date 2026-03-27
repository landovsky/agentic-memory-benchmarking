# Agentic Memory Benchmarking — Hackathon 2026-03-27

Porovnáváme tři AI paměťové systémy: **Mem0**, **Graphiti**, **Cognee**. Cílem je zjistit, který systém nejlépe zvládá různé typy paměti v kontextu reálných projektů.

---

## Co benchmarkujeme a proč

AI asistenti s pamětí mohou pamatovat preference, projektové detaily, minulé události a cíle — ale každý systém to řeší jinak. Testujeme 7 dimenzí:

| Dimenze | Popis |
|---------|-------|
| **Recall** | Základní vybavení uložených faktů |
| **Temporal** | Rozpoznání aktualizací (co platí TEĎ vs. dřív) |
| **Hallucination** | Odolnost vůči vymýšlení neexistujících informací |
| **Isolation** | Oddělení paměti mezi projekty |
| **Proactive** | Aktivní využití relevantní minulé zkušenosti |
| **Scale** | Výkon při 100 vs. 1000 záznamech |
| **Type Distinction** | Rozlišení preference vs. epizodická paměť |

Testovací případy jsou v češtině a odrážejí reálné projekty (HřištěHrou, MedicMee, Pharmacy).

---

## Architektura

```
                    LAN (192.168.x.x)
                          |
         +----------------+----------------+
         |                |                |
   Participant A    Participant B    Participant C
   (Claude Code)   (Claude Code)   (Claude Code)
         |                |                |
         +----------------+----------------+
                          |
                    HOST MACHINE
                          |
          +---------------+---------------+
          |               |               |
     Mem0:8080      Graphiti:8050    Cognee:8000
          |               |               |
     PostgreSQL        Neo4j          PostgreSQL
      :5432             :7474           :5433
          |               |               |
          +---------------+---------------+
                          |
                    LLM Backend
              Anthropic Claude (primary)
              Gemini via Vertex AI (fallback)
```

---

## Prerequisites

- **Python 3.11+**
- **Claude Code** (`claude` CLI) — nainstalovaný a přihlášený
- Přístup do LAN sítě (být na stejné WiFi jako host)
- Git

---

## Quick Start (5 minut)

### 1. Klonuj repo

```bash
git clone <repo-url>
cd agentic-memory-benchmarking
```

### 2. Zkopíruj a uprav .env

```bash
cp .env.example .env
# Vyplň ANTHROPIC_API_KEY a RUNNER_NAME
# HOST_IP zjistíš od Tomáše (Člen 1)
```

### 3. Nakonfiguruj MCP servery

```bash
# Pouze Graphiti (výchozí)
bash bin/setup-mcp.sh 192.168.x.x

# Všechny tři systémy (Graphiti + Mem0 + Cognee)
bash bin/setup-mcp.sh --all 192.168.x.x

# Bez argumentu — skript se zeptá
bash bin/setup-mcp.sh

# Globálně (user scope místo project)
bash bin/setup-mcp.sh --scope user 192.168.x.x

# Odebrání MCP serverů
bash bin/setup-mcp.sh --remove
bash bin/setup-mcp.sh --all --remove
```

### 4. Ověř připojení

```bash
# Test health endpointů
curl http://<HOST_IP>:8080/health   # Mem0
curl http://<HOST_IP>:8050/health   # Graphiti
curl http://<HOST_IP>:8000/health   # Cognee

# Ověř MCP konfigurace v Claude Code
claude mcp list
```

Měl bys vidět: `mem0`, `graphiti`, `cognee` v seznamu.

### 5. Spusť eval harness

```bash
# Vytvoř virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Spusť testy pro jeden systém
python -m eval_harness run --system mem0 --runner your_name

# Nebo všechny najednou
python -m eval_harness run --system all --runner your_name
```

---

## Graphiti Memory Bench (TypeScript standalone)

`graphiti-memory-bench/` je samostatný TypeScript monorepo pro ingest Claude Code sessions a evaluaci Graphiti paměti. Lze spustit nezávisle na Python harnessu.

### Požadavky

- Node.js ≥ 22
- pnpm ≥ 9 (`npm install -g pnpm`)
- Docker + Docker Compose

### 1. Spusť infrastrukturu

```bash
cd graphiti-memory-bench/infra
cp .env.example ../.env   # nebo viz níže
```

Vytvoř `.env` v `graphiti-memory-bench/`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=hackathon2025

POSTGRES_URL=postgres://hackathon:hackathon2025@localhost:5432/eval

GRAPHITI_MCP_URL=http://localhost:8050

ANTHROPIC_API_KEY=sk-ant-...          # pro scoring
GOOGLE_APPLICATION_CREDENTIALS_JSON='{"type":"service_account",...}'  # GCP SA pro Gemini/Vertex AI

RUNNER_NAME=your_name
```

```bash
docker compose up -d   # spustí Neo4j, LiteLLM proxy, Graphiti MCP, PostgreSQL
docker compose ps      # ověř healthy stav
```

### 2. Sestav projekt

```bash
cd graphiti-memory-bench
pnpm install
pnpm build
```

### 3. Nakonfiguruj MCP v Claude Code

```bash
claude mcp add --transport http graphiti http://localhost:8050/mcp
claude mcp list   # měl bys vidět: graphiti ✓ Connected
```

### 4. Ingestuj Claude Code sessions

```bash
# Jeden soubor
pnpm ingest -- --file /path/to/session.jsonl --group-id global

# Celý adresář (rekurzivně)
pnpm ingest -- --dir ~/.claude/projects/ --group-id global

# Náhled bez zápisu
pnpm ingest -- --dir ./data/sessions/ --dry-run
```

JSONL soubory jsou ve formátu Claude Code (`~/.claude/projects/<hash>/<session-id>.jsonl`).

### 5. Spusť evaluaci

```bash
# Všechny test cases
pnpm eval -- run --runner your_name --group-id global

# Filtrovat dimenze nebo priority
pnpm eval -- run --runner your_name --dimension recall,temporal --priority critical,high

# Vygeneruj HTML report (čte z PostgreSQL)
pnpm eval -- report --output ./reports/report.html
```

### Struktura

```
graphiti-memory-bench/
├── packages/
│   ├── shared/      # GraphitiClient (MCP), typy, DB utils, scorers
│   ├── ingest/      # CLI: parsuje JSONL → posílá episodes do Graphiti
│   └── eval/        # CLI: spouští test cases, skóruje, ukládá do PG
├── infra/
│   ├── docker-compose.yml     # Neo4j, LiteLLM proxy, Graphiti MCP, PG
│   ├── graphiti-config.yaml   # Graphiti: LLM + embedder přes LiteLLM
│   └── litellm-config.yaml    # LiteLLM: Vertex AI Gemini 2.5 Flash + embeddings
├── data/
│   ├── test-cases/            # test_cases.json (19 případů)
│   └── sessions/              # ukázkové JSONL sessions
└── .env.example
```

### Klíčové detaily

- **MCP transport**: `StreamableHTTPClientTransport` na `/mcp` (ne SSE)
- **add_memory je asynchronní** — extrakce entit probíhá na pozadí; po ingestu čekej ~2s
- **LiteLLM proxy** → Vertex AI Gemini 2.5 Flash (LLM) + text-embedding-004 (embeddings)
- **`GOOGLE_APPLICATION_CREDENTIALS_JSON`** — celý JSON GCP service accountu jako string (ne cesta k souboru)
- **group_id** odděluje paměti různých projektů nebo runnerů

---

## Struktura projektu

```
agentic-memory-benchmarking/
├── shared-data/
│   ├── test-cases/
│   │   ├── test_cases.csv       # 10 testovacích případů
│   │   └── test_cases.json      # stejná data jako JSON
│   ├── test-sessions/           # sem ukládá harness výsledky
│   │   ├── project-hristehrou/
│   │   ├── project-medicmee/
│   │   └── project-pharmacy/
│   └── eval-results/            # finální výsledky po evaluaci
├── mcp-configs/
│   ├── mem0.mcp.json
│   ├── graphiti.mcp.json
│   └── cognee.mcp.json
├── presentation/
│   └── findings.md              # šablona pro výsledky
├── bin/
│   ├── setup-mcp.sh             # konfigurace MCP na participant stroji
│   ├── preflight.sh             # health check všech služeb
│   └── setup-credentials.sh    # zapíše GCP SA JSON do credentials/
├── .env.example                 # template pro .env
└── README.md                    # tento soubor
```

---

## Kam ukládat výsledky

- **Surové výsledky testů** → `shared-data/test-sessions/<projekt>/`
- **Finální eval skóre** → `shared-data/eval-results/`
- **Závěry a prezentace** → `presentation/findings.md`

Formát výsledků: JSON soubory pojmenované `<system>_<runner>_<timestamp>.json`

---

## Rozdělení rolí

| Člen | Role | Odpovědnost |
|------|------|-------------|
| Tomas (Člen 1) | Infra lead | Host machine, Docker, MCP servery, síťování |
| Člen 2 | Eval engineer | Eval harness, scoring logic, výsledky |
| Člen 3 | Test runner | Spouštění testů, dokumentace výsledků |
| Člen 4 | Analyst | Analýza výsledků, prezentace findings |

---

## LLM Konfigurace

Projekt používá:
1. **Anthropic Claude** (primární) — nastav `ANTHROPIC_API_KEY` v `.env`
2. **Gemini via Vertex AI** (fallback) — nastav `GOOGLE_CLOUD_PROJECT` a `GOOGLE_APPLICATION_CREDENTIALS`

**Pozor:** Nepoužíváme OpenAI.

---

## Troubleshooting

### MCP server se nepřipojí
```bash
# Ověř, že jsi na správné síti
ping <HOST_IP>

# Zkontroluj, zda porty jsou dostupné
nc -zv <HOST_IP> 8080
nc -zv <HOST_IP> 8050
nc -zv <HOST_IP> 8000
```

### `claude mcp list` neukazuje servery
```bash
# Znovu spusť setup skript
bash bin/setup-mcp.sh <HOST_IP>

# Nebo přidej manuálně
claude mcp add --transport sse mem0 "http://<HOST_IP>:8080/sse"
```

### Chyba autentizace Anthropic
```bash
# Ověř, že máš API klíč v .env
grep ANTHROPIC_API_KEY .env

# Nebo nastav jako env variable
export ANTHROPIC_API_KEY=sk-ant-...
```

### Eval harness padá na importech
```bash
# Ujisti se, že máš aktivní venv
source .venv/bin/activate
pip install -e .
```

### Paměťový systém vrací prázdné výsledky
- Ověř, že setup fáze (ukládání memories) proběhla před query fází
- Zkontroluj logy na host machine — zeptej se Tomáše (Člen 1)
- Některé systémy potřebují chvíli na indexaci — počkej 5-10 sekund

### Neo4j (Graphiti) nereaguje
- Port 7474 (HTTP UI) a 7687 (Bolt) musí být dostupné
- Zeptej se Tomáše (Člen 1) pro infra problémy

### Skórovací metoda `llm_judge_negation` vrací špatné výsledky
- Tato metoda kontroluje, že systém NEODPOVÍ (anti-halucinace test)
- Pokud systém odpovídá s konkrétní verzí Reactu = FAIL (0 bodů)
- Pokud systém říká "nevím" = PASS (1 bod)

---

## Testovací případy (přehled)

| ID | Dimenze | Projekt | Co testuje |
|----|---------|---------|------------|
| TC-001 | recall | global | Základní preference (Tailwind vs Bootstrap) |
| TC-002 | recall | medicmee | Tech stack recall (Rails, PostgreSQL, Hotwire) |
| TC-003 | temporal | hristehrou | Rozpoznání aktualizace CSS frameworku |
| TC-004 | isolation | pharmacy | Oddělení deploy info mezi projekty |
| TC-005 | hallucination | global | Anti-halucinace — React verze neexistuje |
| TC-006 | proactive | medicmee | Proaktivní zmínka předchozího DB řešení |
| TC-007 | temporal | hristehrou | Aktualizace Q2 → Q3 deadline |
| TC-008 | scale | global | Baseline recall při 100 záznamech |
| TC-009 | scale | global | Scale test při 1000 záznamech |
| TC-010 | type_dist. | global | Preference vs. epizodická paměť |

Plný popis v `shared-data/test-cases/test_cases.csv` a `test_cases.json`.

---

## Kontakt

Problémy s infrastrukturou (Docker, sítě, MCP servery nereagují)?
**Ptej se Tomáše (Člen 1).**
