import { useState } from "react";

const systems = [
  {
    name: "Mem0",
    tagline: "Hybrid embeddings + graph memory layer",
    approach: "Vector + Graph",
    license: "Apache 2.0",
    github: "mem0ai/mem0",
    stars: "25k+",
    funding: "YC-backed, $24M Series A (Oct 2025)",
    mcp: "✅ Official MCP server + OpenMemory (local-first)",
    selfHosted: "✅ Docker (Qdrant + Postgres) or Cloud API",
    languages: "Python, JS/TS SDKs",
    storage: "Qdrant, Chroma, Milvus, pgvector, Redis",
    memoryTypes: ["Preferences", "Episodic", "Semantic"],
    strengths: [
      "Nejjednodušší setup — 1 řádek kódu pro přidání paměti",
      "Framework-agnostic (LangChain, CrewAI, LlamaIndex)",
      "OpenMemory = plně lokální, žádná data do cloudu",
      "Atomic memories s metadata (user, session, app scope)",
      "Verzování a TTL na paměti",
    ],
    weaknesses: [
      "Graf (Mem0g) jen v Pro tier ($249/měsíc)",
      "49% na LongMemEval — nejslabší z hlavních systémů",
      "Kontroverzní self-reported LOCOMO výsledky (Letta zpochybnila)",
      "Vyžaduje LLM pro funkci (default GPT-4.1-nano)",
    ],
    hackathonFit: 4,
    benchmarkScore: "49% LongMemEval, 68.5% LOCOMO (sporné)",
    setupComplexity: "Nízká",
    dataIngestion: "API: memory.add(messages, user_id=...)",
    color: "#6C5CE7",
  },
  {
    name: "Zep / Graphiti",
    tagline: "Temporal knowledge graph pro agenty",
    approach: "Knowledge Graph (Neo4j)",
    license: "Apache 2.0 (Graphiti OSS) / Cloud (Zep)",
    github: "getzep/graphiti",
    stars: "20k+",
    funding: "Komerční platforma + OSS Graphiti",
    mcp: "✅ Graphiti MCP server (Docker + Neo4j)",
    selfHosted: "✅ Graphiti (Neo4j + Docker) / ☁️ Zep Cloud",
    languages: "Python SDK",
    storage: "Neo4j (graf) + vector embeddings",
    memoryTypes: ["Episodic", "Semantic", "Temporal facts"],
    strengths: [
      "Temporal awareness — fakta mají platnost v čase",
      "Extrahuje entity, relace a fakta z konverzací",
      "Invaliduje starší fakta místo mazání",
      "71.2% na LongMemEval — solidní výkon",
      "Silná akademická práce (Zep paper)",
    ],
    weaknesses: [
      "Neo4j dependency = těžší setup na hackathonu",
      "Pokročilé funkce za paywallem Zep Cloud",
      "Hodně API calls = vyšší náklady na LLM",
      "MemCP (community fork) hlásí vysoké náklady na generování grafu",
    ],
    hackathonFit: 3,
    benchmarkScore: "71.2% LongMemEval, 80% LOCOMO",
    setupComplexity: "Střední–Vysoká (Neo4j)",
    dataIngestion: "Episodes API — konverzace po session",
    color: "#00B894",
  },
  {
    name: "Letta (MemGPT)",
    tagline: "LLM-as-OS — agent si sám řídí paměť",
    approach: "Tiered memory (core/recall/archival)",
    license: "Apache 2.0",
    github: "letta-ai/letta",
    stars: "15k+",
    funding: "Komerční platforma + OSS framework",
    mcp: "✅ Memory MCP (Smithery) — user memory + vector DB",
    selfHosted: "✅ Docker (letta/letta:latest)",
    languages: "Python, TypeScript SDKs",
    storage: "Postgres (built-in), vlastní agent state DB",
    memoryTypes: [
      "Core (always in-context)",
      "Recall (conversation)",
      "Archival (long-term)",
    ],
    strengths: [
      "Unikátní architektura — agent sám edituje svou paměť",
      "Core memory = vždy v kontextu, okamžitý přístup",
      "74% na LOCOMO s prostým filesystem přístupem (!)",
      "Letta Code = memory-first coding agent",
      "DeepLearning.AI kurz — silná edukace",
    ],
    weaknesses: [
      "Není navržen pro backfill historických dat (JSONL)",
      "Vyžaduje spolehlivý tool-calling od modelu",
      "Složitější mentální model pro evaluaci",
      "Nativní MCP memory je cloud-only (API key)",
    ],
    hackathonFit: 2,
    benchmarkScore: "74% LOCOMO (filesystem), N/A LongMemEval nativně",
    setupComplexity: "Střední",
    dataIngestion: "Letta Filesystem (soubory) nebo API messages",
    color: "#E17055",
  },
  {
    name: "Cognee",
    tagline: "Knowledge engine — graf + vektory + kognitivní věda",
    approach: "Graph-Vector Hybrid + ECL pipeline",
    license: "Apache 2.0",
    github: "topoteretes/cognee",
    stars: "8k+",
    funding: "$7.5M seed (Pebblebed, OpenAI/FAIR founders)",
    mcp: "✅ Cognee MCP server + Claude integration",
    selfHosted: "✅ Plně lokální (Postgres/Neo4j + pgvector/Qdrant)",
    languages: "Python SDK, CLI",
    storage: "pgvector, Neo4j, Kuzu, LanceDB, Qdrant",
    memoryTypes: [
      "Session (krátkodobá)",
      "Permanent (dlouhodobá)",
      "Entity graph",
    ],
    strengths: [
      "14 režimů retrievalu (RAG → graph traversal)",
      "ECL pipeline: Extract → Cognify → Load",
      "Self-improving: memify() prořezává a zesiluje graf",
      "Multi-tenant isolation na úrovni grafu",
      "92.5% accuracy vs 60% tradiční RAG (vlastní eval)",
      "Integrace s OpenClaw — přímo relevantní!",
    ],
    weaknesses: [
      "Mladší projekt — API se ještě mění (v0.5.5)",
      "1 GB / 40 min s 100+ kontejnery = pomalé",
      "Chybí TypeScript SDK a mobile",
      "Menší komunita než Mem0/Zep",
    ],
    hackathonFit: 3,
    benchmarkScore: "92.5% vlastní eval (vs RAG 60%), žádný LongMemEval",
    setupComplexity: "Střední",
    dataIngestion: "cognee.add(data) → cognee.cognify() → cognee.search()",
    color: "#0984E3",
  },
  {
    name: "Supermemory",
    tagline: "Memory API — nejrychlejší, benchmark SOTA",
    approach: "Custom vector-graph engine + user profiles",
    license: "Open-source engine, cloud API",
    github: "supermemoryai/supermemory",
    stars: "7k+",
    funding: "YC AI Startup School, angel-funded",
    mcp: "✅ MCP 4.0 server + Claude Code / OpenClaw pluginy",
    selfHosted: "⚠️ Engine je open-source, ale primárně cloud API",
    languages: "TypeScript, Python SDKs",
    storage: "Custom vector-graph engine (vlastní)",
    memoryTypes: ["User profiles", "Episodic", "RAG documents", "Connectors"],
    strengths: [
      "#1 na LongMemEval, LOCOMO i ConvoMem",
      "Sub-300ms latence na query",
      "Automatické user profily z chování",
      "Knowledge updates, contradictions, auto-forgetting",
      "Claude Code + OpenClaw pluginy ready",
      "MemoryBench — open eval framework",
    ],
    weaknesses: [
      "Primárně cloud — self-hosted omezený",
      "Proprietární engine (ne plně OSS)",
      "Mladý startup (19yo founder, ASU)",
      "API key required i pro MCP",
    ],
    hackathonFit: 4,
    benchmarkScore:
      "#1 LongMemEval (95% Observational Memory), #1 LOCOMO, #1 ConvoMem",
    setupComplexity: "Velmi nízká (cloud API)",
    dataIngestion: "client.add(content=..., container_tags=[...])",
    color: "#FDCB6E",
  },
];

const dimensions = [
  {
    key: "recall",
    label: "Recall",
    icon: "🔍",
    desc: "Vyhledá známý fakt na dotaz?",
  },
  {
    key: "proactive",
    label: "Proaktivita",
    icon: "🧠",
    desc: "Sám pozná, kdy načíst paměť?",
  },
  {
    key: "relevance",
    label: "Relevance",
    icon: "🎯",
    desc: "Správný kontext pro úkol?",
  },
  {
    key: "hallucination",
    label: "Anti-halucinace",
    icon: "🛡️",
    desc: "Nevymýšlí neexistující?",
  },
  {
    key: "typeAware",
    label: "Typy paměti",
    icon: "📂",
    desc: "Rozliší preference vs epizodickou?",
  },
  {
    key: "temporal",
    label: "Temporální",
    icon: "⏳",
    desc: "Aktuální vs zastaralé?",
  },
  {
    key: "isolation",
    label: "Izolace",
    icon: "🔒",
    desc: "Projekt A vs Projekt B?",
  },
  {
    key: "scale",
    label: "Škálovatelnost",
    icon: "📈",
    desc: "100 → 10k záznamů?",
  },
];

function StarRating({ value, max = 5, color }) {
  return (
    <div style={{ display: "flex", gap: 2 }}>
      {Array.from({ length: max }, (_, i) => (
        <div
          key={i}
          style={{
            width: 10,
            height: 10,
            borderRadius: 2,
            background: i < value ? color : "rgba(255,255,255,0.1)",
            transition: "background 0.3s",
          }}
        />
      ))}
    </div>
  );
}

function Badge({ children, variant = "default" }) {
  const styles = {
    default: { background: "rgba(255,255,255,0.08)", color: "#ccc" },
    green: { background: "rgba(0,184,148,0.15)", color: "#00b894" },
    yellow: { background: "rgba(253,203,110,0.15)", color: "#fdcb6e" },
    red: { background: "rgba(225,112,85,0.15)", color: "#e17055" },
    blue: { background: "rgba(9,132,227,0.15)", color: "#0984e3" },
  };
  return (
    <span
      style={{
        ...styles[variant],
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: 0.3,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

export default function MemorySystemsComparison() {
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState("overview");

  const selectedSystem = systems.find((s) => s.name === selected);

  return (
    <div
      style={{
        fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
        background: "#0a0a0f",
        color: "#e0e0e0",
        minHeight: "100vh",
        padding: "24px 20px",
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div
          style={{
            fontSize: 11,
            color: "#666",
            letterSpacing: 2,
            textTransform: "uppercase",
            marginBottom: 4,
          }}
        >
          hackathon prep · memory systems benchmark
        </div>
        <h1
          style={{
            fontSize: 22,
            fontWeight: 800,
            margin: 0,
            background: "linear-gradient(135deg, #6C5CE7, #00B894, #FDCB6E)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            lineHeight: 1.2,
          }}
        >
          AI Agent Memory Systems
        </h1>
        <p
          style={{
            fontSize: 12,
            color: "#888",
            margin: "6px 0 0",
            lineHeight: 1.5,
          }}
        >
          5 kandidátů · MCP-ready · porovnání pro výběr 2–3 do benchmarku
        </p>
      </div>

      {/* View Toggle */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {[
          { key: "overview", label: "Přehled" },
          { key: "benchmark", label: "Benchmark" },
          { key: "recommend", label: "Doporučení" },
        ].map((v) => (
          <button
            key={v.key}
            onClick={() => setView(v.key)}
            style={{
              padding: "6px 14px",
              borderRadius: 4,
              border: "1px solid",
              borderColor: view === v.key ? "#6C5CE7" : "rgba(255,255,255,0.1)",
              background:
                view === v.key ? "rgba(108,92,231,0.15)" : "transparent",
              color: view === v.key ? "#a29bfe" : "#888",
              fontSize: 11,
              fontWeight: 600,
              cursor: "pointer",
              fontFamily: "inherit",
              letterSpacing: 0.5,
            }}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Overview View */}
      {view === "overview" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {systems.map((sys) => (
            <div
              key={sys.name}
              onClick={() =>
                setSelected(selected === sys.name ? null : sys.name)
              }
              style={{
                background:
                  selected === sys.name
                    ? "rgba(255,255,255,0.04)"
                    : "rgba(255,255,255,0.02)",
                border: `1px solid ${selected === sys.name ? sys.color + "66" : "rgba(255,255,255,0.06)"}`,
                borderRadius: 8,
                padding: 14,
                cursor: "pointer",
                transition: "all 0.2s",
                borderLeft: `3px solid ${sys.color}`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  marginBottom: 6,
                }}
              >
                <div>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "#fff" }}>
                    {sys.name}
                  </div>
                  <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                    {sys.tagline}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 4,
                    flexWrap: "wrap",
                    justifyContent: "flex-end",
                  }}
                >
                  <Badge
                    variant={
                      sys.setupComplexity.includes("Nízká") ||
                      sys.setupComplexity.includes("nízká")
                        ? "green"
                        : sys.setupComplexity.includes("Střední")
                          ? "yellow"
                          : "red"
                    }
                  >
                    Setup: {sys.setupComplexity}
                  </Badge>
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  gap: 6,
                  flexWrap: "wrap",
                  marginBottom: 8,
                }}
              >
                <Badge>{sys.approach}</Badge>
                <Badge>
                  {sys.license.split(" ")[0] === "Apache"
                    ? "Apache 2.0"
                    : sys.license.split(",")[0]}
                </Badge>
                <Badge variant="green">
                  {sys.mcp.startsWith("✅") ? "MCP ✓" : "MCP ⚠"}
                </Badge>
              </div>

              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
                <span style={{ color: "#666" }}>Hackathon fit:</span>{" "}
                <StarRating value={sys.hackathonFit} color={sys.color} />
              </div>

              {/* Expanded Detail */}
              {selected === sys.name && (
                <div
                  style={{
                    marginTop: 12,
                    paddingTop: 12,
                    borderTop: "1px solid rgba(255,255,255,0.06)",
                  }}
                >
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 8,
                      marginBottom: 12,
                    }}
                  >
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "#666",
                          textTransform: "uppercase",
                          letterSpacing: 1,
                          marginBottom: 4,
                        }}
                      >
                        Self-hosted
                      </div>
                      <div style={{ fontSize: 11, color: "#ccc" }}>
                        {sys.selfHosted}
                      </div>
                    </div>
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "#666",
                          textTransform: "uppercase",
                          letterSpacing: 1,
                          marginBottom: 4,
                        }}
                      >
                        Storage
                      </div>
                      <div style={{ fontSize: 11, color: "#ccc" }}>
                        {sys.storage}
                      </div>
                    </div>
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "#666",
                          textTransform: "uppercase",
                          letterSpacing: 1,
                          marginBottom: 4,
                        }}
                      >
                        Data Ingestion
                      </div>
                      <div style={{ fontSize: 11, color: "#ccc" }}>
                        {sys.dataIngestion}
                      </div>
                    </div>
                    <div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "#666",
                          textTransform: "uppercase",
                          letterSpacing: 1,
                          marginBottom: 4,
                        }}
                      >
                        Benchmark
                      </div>
                      <div style={{ fontSize: 11, color: "#ccc" }}>
                        {sys.benchmarkScore}
                      </div>
                    </div>
                  </div>

                  <div style={{ marginBottom: 10 }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#00b894",
                        textTransform: "uppercase",
                        letterSpacing: 1,
                        marginBottom: 4,
                      }}
                    >
                      ✅ Silné stránky
                    </div>
                    {sys.strengths.map((s, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 11,
                          color: "#aaa",
                          marginBottom: 2,
                          paddingLeft: 10,
                        }}
                      >
                        • {s}
                      </div>
                    ))}
                  </div>

                  <div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#e17055",
                        textTransform: "uppercase",
                        letterSpacing: 1,
                        marginBottom: 4,
                      }}
                    >
                      ⚠️ Slabiny
                    </div>
                    {sys.weaknesses.map((w, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 11,
                          color: "#888",
                          marginBottom: 2,
                          paddingLeft: 10,
                        }}
                      >
                        • {w}
                      </div>
                    ))}
                  </div>

                  <div style={{ marginTop: 10 }}>
                    <div
                      style={{
                        fontSize: 10,
                        color: "#666",
                        textTransform: "uppercase",
                        letterSpacing: 1,
                        marginBottom: 4,
                      }}
                    >
                      Typy paměti
                    </div>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {sys.memoryTypes.map((t) => (
                        <Badge key={t} variant="blue">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Benchmark View */}
      {view === "benchmark" && (
        <div>
          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 8,
              padding: 14,
              marginBottom: 12,
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#fff",
                marginBottom: 8,
              }}
            >
              LongMemEval (ICLR 2025)
            </div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 12 }}>
              500 otázek, ~115k tokenů konverzační historie, 5 typů paměťových
              schopností
            </div>
            {[
              {
                name: "Supermemory (Observational Memory)",
                score: 95,
                color: "#FDCB6E",
              },
              { name: "Emergence (RAG SOTA)", score: 86, color: "#ddd" },
              {
                name: "Oracle GPT-4o (gold standard)",
                score: 82.4,
                color: "#666",
              },
              { name: "EverMemOS", score: 83, color: "#ddd" },
              { name: "TiMem", score: 76.9, color: "#ddd" },
              { name: "Zep / Graphiti", score: 71.2, color: "#00B894" },
              { name: "Naive RAG", score: 52, color: "#888" },
              { name: "Mem0", score: 49, color: "#6C5CE7" },
            ].map((item) => (
              <div key={item.name} style={{ marginBottom: 6 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginBottom: 2,
                  }}
                >
                  <span style={{ fontSize: 11, color: item.color }}>
                    {item.name}
                  </span>
                  <span
                    style={{ fontSize: 11, color: item.color, fontWeight: 700 }}
                  >
                    {item.score}%
                  </span>
                </div>
                <div
                  style={{
                    height: 4,
                    background: "rgba(255,255,255,0.05)",
                    borderRadius: 2,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${item.score}%`,
                      background: item.color,
                      borderRadius: 2,
                      opacity: 0.6,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 8,
              padding: 14,
              marginBottom: 12,
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#fff",
                marginBottom: 6,
              }}
            >
              Evaluační dimenze pro hackathon
            </div>
            <div style={{ fontSize: 11, color: "#888", marginBottom: 10 }}>
              Co měřit u každého systému:
            </div>
            {dimensions.map((d) => (
              <div
                key={d.key}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 6,
                  padding: "4px 0",
                }}
              >
                <span style={{ fontSize: 14, width: 20 }}>{d.icon}</span>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#ccc" }}>
                    {d.label}
                  </div>
                  <div style={{ fontSize: 10, color: "#666" }}>{d.desc}</div>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              background: "rgba(253,203,110,0.05)",
              border: "1px solid rgba(253,203,110,0.15)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#FDCB6E",
                marginBottom: 6,
              }}
            >
              ⚠️ Benchmark Caveats
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              • LOCOMO benchmark má nespolehlivé F1 scoring — penalizuje správné
              ale rozvité odpovědi
              <br />
              • Mem0 self-reported LOCOMO výsledky byly zpochybněny Lettou
              <br />
              • LongMemEval je považován za nejlepší standard (ICLR 2025)
              <br />
              • Letta ukázala, že prostý filesystem search dosahuje 74% na
              LOCOMO — "Is a Filesystem All You Need?"
              <br />• Supermemory 95% je s Observational Memory architekturou
              (Mastra research)
            </div>
          </div>
        </div>
      )}

      {/* Recommendation View */}
      {view === "recommend" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div
            style={{
              background:
                "linear-gradient(135deg, rgba(108,92,231,0.1), rgba(0,184,148,0.1))",
              border: "1px solid rgba(108,92,231,0.2)",
              borderRadius: 8,
              padding: 16,
            }}
          >
            <div
              style={{
                fontSize: 13,
                fontWeight: 800,
                color: "#fff",
                marginBottom: 8,
              }}
            >
              🏆 Doporučení: 3 systémy do benchmarku
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.7 }}>
              Na základě: MCP readiness, self-hosted možnosti, architektonická
              rozmanitost, hackathon feasibility
            </div>
          </div>

          {/* Pick 1: Mem0 */}
          <div
            style={{
              background: "rgba(108,92,231,0.05)",
              border: "1px solid rgba(108,92,231,0.2)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 16 }}>1️⃣</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#6C5CE7" }}>
                Mem0 (OpenMemory)
              </span>
              <Badge variant="green">Baseline</Badge>
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              <strong style={{ color: "#ccc" }}>Proč:</strong> Nejpopulárnější,
              nejsnazší setup, reprezentuje "vector + flat memory" přístup.
              Skvělý baseline pro srovnání.
              <br />
              <strong style={{ color: "#ccc" }}>Setup:</strong> Docker compose
              (Qdrant + Postgres + API) → MCP do Claude Code.
              <br />
              <strong style={{ color: "#ccc" }}>Data loading:</strong> Iterovat
              přes JSONL sessions, volat memory.add() pro každou zprávu.
              <br />
              <strong style={{ color: "#ccc" }}>Očekávání:</strong> Dobrý na
              preference a jednoduché vyhledání. Slabý na temporální a
              multi-session reasoning.
            </div>
          </div>

          {/* Pick 2: Zep/Graphiti */}
          <div
            style={{
              background: "rgba(0,184,148,0.05)",
              border: "1px solid rgba(0,184,148,0.2)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 16 }}>2️⃣</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#00B894" }}>
                Graphiti (Zep OSS)
              </span>
              <Badge variant="yellow">Knowledge Graph</Badge>
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              <strong style={{ color: "#ccc" }}>Proč:</strong> Knowledge graph s
              temporalitou — přímo testuje "odlišení aktuálního od zastaralého".
              Architektonicky odlišný od Mem0.
              <br />
              <strong style={{ color: "#ccc" }}>Setup:</strong> Docker (Neo4j +
              Graphiti MCP). Větší nároky, ale Docker compose to zvládne.
              <br />
              <strong style={{ color: "#ccc" }}>Data loading:</strong> Episodes
              API — konverzace jako timestamped sessions.
              <br />
              <strong style={{ color: "#ccc" }}>Očekávání:</strong> Silný na
              temporal reasoning a knowledge updates. Může být pomalejší kvůli
              graph construction.
            </div>
          </div>

          {/* Pick 3: Cognee OR Supermemory */}
          <div
            style={{
              background: "rgba(9,132,227,0.05)",
              border: "1px solid rgba(9,132,227,0.2)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 16 }}>3️⃣</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#0984E3" }}>
                Cognee
              </span>
              <Badge variant="blue">Graph + Vector hybrid</Badge>
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              <strong style={{ color: "#ccc" }}>Proč:</strong> Graf + vektory +
              self-improving. Integrace s OpenClaw (relevantní pro hackathon).
              14 retrieval modes dává zajímavou testovací plochu.
              <br />
              <strong style={{ color: "#ccc" }}>Setup:</strong> pip install
              cognee + Postgres/pgvector. MCP server dostupný.
              <br />
              <strong style={{ color: "#ccc" }}>Data loading:</strong>{" "}
              cognee.add(text) → cognee.cognify() → cognee.search().
              <br />
              <strong style={{ color: "#ccc" }}>Očekávání:</strong> Nejbohatší
              retrieval options. ECL pipeline může být pomalá na velké datasety.
            </div>
          </div>

          {/* Alt pick */}
          <div
            style={{
              background: "rgba(253,203,110,0.05)",
              border: "1px dashed rgba(253,203,110,0.2)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 16 }}>🔄</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#FDCB6E" }}>
                Alternativa: Supermemory
              </span>
              <Badge>Cloud-first</Badge>
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              Pokud je cíl zahrnout "best-in-class" cloud řešení pro srovnání,
              Supermemory má nejlepší benchmark skóre a ready-made Claude Code +
              OpenClaw pluginy. Ale je primárně cloud → méně zajímavý pro
              self-hosted evaluaci.
            </div>
          </div>

          {/* Why not Letta */}
          <div
            style={{
              background: "rgba(225,112,85,0.05)",
              border: "1px dashed rgba(225,112,85,0.2)",
              borderRadius: 8,
              padding: 14,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
              }}
            >
              <span style={{ fontSize: 16 }}>❌</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#E17055" }}>
                Proč ne Letta?
              </span>
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.6 }}>
              Fascinující architektura, ale pro hackathon benchmark{" "}
              <strong style={{ color: "#ccc" }}>není vhodná</strong>: backfill
              historických JSONL dat je obtížný (sami přiznávají), MCP memory
              vyžaduje cloud API key, a je to spíš "agent framework" než "memory
              system" — těžko porovnatelná s ostatními 1:1. Stojí za zmínku v
              prezentaci jako reference point.
            </div>
          </div>

          <div
            style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 8,
              padding: 14,
              marginTop: 4,
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#fff",
                marginBottom: 8,
              }}
            >
              📋 Rozmanitost architektur
            </div>
            <div style={{ fontSize: 11, color: "#aaa", lineHeight: 1.7 }}>
              <span style={{ color: "#6C5CE7" }}>Mem0</span> = vektor + flat
              metadata (nejběžnější přístup)
              <br />
              <span style={{ color: "#00B894" }}>Graphiti</span> = knowledge
              graph + temporalita (structured reasoning)
              <br />
              <span style={{ color: "#0984E3" }}>Cognee</span> = graf + vektor
              hybrid + self-improving (nejkomplexnější)
              <br />
              <br />
              Tři architektonicky odlišné přístupy → smysluplné srovnání.
            </div>
          </div>
        </div>
      )}

      {/* Footer */}
      <div
        style={{
          marginTop: 20,
          padding: "12px 0",
          borderTop: "1px solid rgba(255,255,255,0.06)",
          fontSize: 10,
          color: "#555",
          textAlign: "center",
        }}
      >
        Compiled March 2026 · Sources: GitHub, LongMemEval (ICLR 2025),
        vectorize.io, Letta blog, Mastra research, ML Mastery
      </div>
    </div>
  );
}
