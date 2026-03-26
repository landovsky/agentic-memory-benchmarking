# Vyhodnocení postupu projektu vs. Project Brief

> Stav ke dni: 2026-03-26

---

## Souhrnné hodnocení

**Celková připravenost: ~95 %** — Projekt je kódově kompletní a připravený k nasazení na hackathon. Všechny hlavní výstupy z briefu jsou splněny nebo překročeny. Chybí pouze realizace samotného hackathonu (spuštění evaluací, naplnění dat, srovnávací zjištění).

---

## Cíle projektu — plnění

### Primární cíl

> *Otestovat 2–3 open-source řešení AI paměti na reálných vzorcích používání.*

| Aspekt | Brief | Stav | Poznámka |
|--------|-------|------|----------|
| Počet systémů | 2–3 | **3 integrovány** | Mem0, Graphiti, Cognee |
| Přístup přes MCP | Ano | **Splněno** | Každý systém má vlastní MCP server |
| Reálné vzorce | JSONL z Claude Code | **Pipeline hotová** | `jsonl_parser.py` → `memory_extractor.py` → system loaders |

**Odchylka od briefu:** Místo původně zvažovaných Zep a Letta (MemGPT) byly zvoleny **Graphiti** a **Cognee**. Důvodem byla lepší MCP připravenost. Mem0 zůstalo jako jistota.

---

### Měřené dimenze — pokrytí test cases

| Dimenze z briefu | Pokryta? | Test case(s) |
|-------------------|----------|--------------|
| Vybavení (Recall) | **Ano** | TC-001, TC-002 |
| Proaktivní využití | **Ano** | TC-006 |
| Relevance | *Implicitně* | Pokryto přes recall a proactive |
| Odolnost vůči halucinacím | **Ano** | TC-005 |
| Rozlišení typu paměti | **Ano** | TC-010 |
| Časové uvažování | **Ano** | TC-003, TC-007 |
| Izolace mezi projekty | **Ano** | TC-004 |
| Škálovatelnost | **Ano** | TC-008 (100), TC-009 (1000) |

**Hodnocení:** 7 z 8 dimenzí pokryto explicitně, 1 (relevance) implicitně. Celkem 10 test cases.

---

### Typy paměti — pokrytí

| Typ z briefu | Testováno? | Příklady |
|--------------|-----------|----------|
| Preference | **Ano** | TC-001 (Tailwind), TC-010 |
| Epizodická | **Ano** | TC-006 (DB timeout debugging) |
| Sémantická | **Ano** | TC-002 (MedicMee stack), TC-008/009 |
| Cíle | **Ano** | TC-007 (HH ERP deadline) |

---

## Výstupy — plnění

### 1. Funkční integrace

| Požadavek | Stav | Detail |
|-----------|------|--------|
| Alespoň 1 systém připojený k Claude Code | **Překročeno — 3 systémy** | Mem0 (8181), Graphiti (8050), Cognee (8000) |
| MCP integrace | **Kompletní** | `setup-mcp.sh` automatizuje registraci |
| Docker orchestrace | **Kompletní** | 7 služeb v `docker-compose.yml` |

### 2. Evaluační rámec (harness)

| Požadavek | Stav | Detail |
|-----------|------|--------|
| Znovupoužitelná testovací sada | **Splněno** | `eval-harness/runner.py` — CSV-driven, rozšiřitelný |
| Skórovací metody | **3 implementovány** | `exact_contains`, `llm_judge`, `llm_judge_negation` |
| Ukládání výsledků | **Splněno** | PostgreSQL tabulka `eval_runs` |
| Reportování | **Splněno** | `report.py` — barevně kódovaná HTML pivot tabulka |

### 3. Srovnávací zjištění

| Požadavek | Stav | Detail |
|-----------|------|--------|
| Dokumentované silné stránky a omezení | **Čeká na hackathon** | Infrastruktura pro sběr dat hotová, výsledky dosud nenasbírány |

### 4. Prezentace

| Požadavek | Stav | Detail |
|-----------|------|--------|
| 5minutová prezentace | **Šablona existuje** | Adresář `presentation/` připraven |

---

## Příprava před akcí — checklist vedoucího

| Úkol z briefu | Stav | Realizace |
|----------------|------|-----------|
| Výběr paměťových systémů | **Hotovo** | Mem0, Graphiti, Cognee |
| Stažení a otestování Docker obrazů | **Hotovo** | `docker-compose.yml` s health checks |
| Ověření MCP serverů | **Hotovo** | `preflight.sh` — 7 automatizovaných kontrol |
| Příprava datové pipeline | **Hotovo** | 5 skriptů v `data-loaders/` |
| Export ukázkových dat | **Částečně** | Pipeline hotová, ukázková data v `shared-data/test-cases/` |
| Vytvoření sdíleného repozitáře | **Hotovo** | README.md, CLAUDE.md, infra-ops.md, setup skripty |
| Příprava pitche | **TBD** | Nezjištěno |

---

## Co bylo postaveno navíc (nad rámec briefu)

1. **LiteLLM proxy** — fallback přes Vertex AI pro Gemini modely, řeší závislost na více LLM poskytovatelích.
2. **Tři skórovací metody** — brief zmiňoval jen měření; implementovány exact match, LLM judge i negation judge.
3. **File server** (port 9000) — HTTP distribuce testovacích dat účastníkům.
4. **Automatizovaný preflight** — zdravotní kontrola všech 7 služeb jedním příkazem.
5. **Infra-ops dokumentace** — provozní příručka pro hostitelský stroj.
6. **Init skripty pro PostgreSQL** — automatické vytvoření databází a tabulek při startu.

---

## Co chybí / otevřené body

| Oblast | Stav | Priorita |
|--------|------|----------|
| Skutečné výsledky evaluací | Čeká na hackathon | Kritická |
| Naplnění paměťových systémů daty | Pipeline hotová, data nenahrána | Kritická |
| Srovnávací report (HTML) | `report.py` hotový, výstup neexistuje | Vysoká |
| Testování škálovatelnosti (10 000 záznamů) | Brief zmiňuje, test cases pokrývají jen 100 vs. 1000 | Nízká |
| Dimenze "Relevance" | Nemá dedikovaný test case | Nízká |
| Týmové role | TBD v briefu, nespecifikováno | Nízká |
| Účastnické prerekvizity | TBD v briefu | Nízká |
| Pitch / prezentace | Šablona existuje, obsah chybí | Střední |

---

## Architektura — realizace vs. brief

Brief navrhoval jednoduchou architekturu s 2–3 systémy přes MCP. Realizace ji překročila:

```
┌─────────────────────────────────────────────────┐
│                   Host Machine                   │
│                                                  │
│  ┌──────────┐  ┌────────┐  ┌────────┐          │
│  │ PostgreSQL│  │ Qdrant │  │ Neo4j  │          │
│  │ (pgvector)│  │        │  │        │          │
│  │ :5432     │  │ :6333  │  │ :7474  │          │
│  └─────┬────┘  └───┬────┘  └───┬────┘          │
│        │           │           │                 │
│  ┌─────┴───┐  ┌────┴───┐  ┌───┴──────┐         │
│  │ Cognee  │  │ Mem0   │  │ Graphiti │         │
│  │ MCP     │  │ MCP    │  │ MCP      │         │
│  │ :8000   │  │ :8181  │  │ :8050    │         │
│  └─────────┘  └────────┘  └──────────┘         │
│                                                  │
│  ┌──────────┐  ┌──────────────────────┐         │
│  │ LiteLLM  │  │ File Server :9000   │         │
│  │ :4000    │  └──────────────────────┘         │
│  └──────────┘                                    │
└─────────────────────────────────────────────────┘
         ▲                    ▲
         │ MCP (SSE)          │ HTTP
         │                    │
┌────────┴────────────────────┴───────────┐
│           Participant Machine            │
│  ┌────────────┐  ┌───────────────────┐  │
│  │ Claude Code│  │ eval-harness/     │  │
│  │ + MCP      │  │ runner.py         │  │
│  └────────────┘  └───────────────────┘  │
└─────────────────────────────────────────┘
```

---

## Závěr

Projekt je **připraven k hackathonu**. Veškerá infrastruktura, evaluační rámec, datová pipeline a dokumentace jsou implementovány a funkční. Zbývající práce — naplnění systémů daty, spuštění evaluací a interpretace výsledků — je přesně to, co má hackathon pokrýt.

Hlavní riziko: spolehlivost MCP serverů třetích stran v Docker prostředí při reálné zátěži.
