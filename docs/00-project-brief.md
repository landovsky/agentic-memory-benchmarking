# Dlouhodobá paměť pro naše agenty — Project Brief

## Benchmark systémů pro správu paměti AI agentských systémů

---

## Problém

Když pracujete s AI asistenty pro kódování, jako je Claude Code, každá relace začíná od nuly. Agent si nepamatuje:

- Že dáváte přednost Tailwindu před Bootstrapem.
- Že jste přesně tuhle chybu připojení k Postgresu vyřešili před čtrnácti dny.
- Že váš „projekt lékárna" označuje agregátor skladových zásob, nikoliv maloobchodní prodejnu.
- Váš dlouhodobý cíl vydat MVP MedicMee do 3. čtvrtletí.

Pamětí se stáváte vy. Znovu vysvětlujete kontext, opakujete preference a popisujete své projekty — relaci po relaci. Tato kognitivní zátěž se s růstem projektů sčítá.

I když si důležitý kontext uložíte — do vyhrazených markdown souborů, do CLAUDE.md nebo do tabulek artefaktů — agent často nerozpozná, kdy by je měl načíst. Nakonec stejně ručně odkazujete na soubory, které jste už dříve připravili, což popírá smysl strukturované projektové paměti.

---

## Proč současná řešení selhávají

Většina platform pro agenty buď:

1. **Nemá žádnou trvalou paměť** — každá relace je bezstavová.
2. **Používá naivní úložiště** — prosté připisování do markdown/textových souborů s vyhledáváním podle klíčových slov nebo aktuálnosti.
3. **Vyžaduje ruční správu** — musíte agentovi explicitně říct, co si má zapamatovat.

Jak paměť roste, kvalita vyhledávání klesá. Agent předkládá nerelevantní kontext nebo přehlédne kritickou historii pohřbenou ve starších relacích.

---

## Příslib strukturované paměti

Paměťové systémy založené na databázích (vektorová úložiště, znalostní grafy, hybridní přístupy) se to snaží vyřešit pomocí:

- Ukládání vzpomínek s bohatými metadaty (projekt, časové razítko, typ, důležitost).
- Využití sémantické podobnosti pro vyhledávání, nikoliv jen klíčových slov.
- Plynulého škálování ze 100 na 100 000 záznamů.
- Vyvažování aktuálnosti s relevancí.

Ale opravdu fungují? To zkusíme zjistit.

---

## Cíle projektu

> Pracovní verze — rozsah může být upraven podle kapacit týmu

### Primární cíl

Otestovat (benchmark) 2–3 open-source řešení AI paměti na reálných vzorcích používání s využitím historických dat z relací Claude Code nebo jiných relevantních dat dodaných členy projektu.

### Co budeme měřit

| Dimenze | Otázka |
|---------|--------|
| **Vybavení (Recall)** | Dokáže systém vyhledat známý fakt, když je dotázán? |
| **Proaktivní využití** | Rozpozná agent sám, kdy načíst uložené vzpomínky, aniž by mu to někdo řekl? |
| **Relevance** | Předloží pro daný úkol ten správný kontext? |
| **Odolnost vůči halucinacím** | Vyvaruje se vymýšlení vzpomínek, které neexistují? |
| **Rozlišení typu paměti** | Přistupuje odlišně k preferencím, epizodické a sémantické paměti? |
| **Časové uvažování** | Dokáže odlišit „aktuální přístup" od „starého přístupu, který jsme opustili"? |
| **Izolace mezi projekty** | Neznečišťuje dotaz na Projekt A výsledky z Projektu B? |
| **Škálovatelnost** | Jak se mění výkon při 100 vs. 1 000 vs. 10 000 záznamech? |

### Typy paměti, které budeme testovat

Všechny typy paměti slouží jako kontext, ale chovají se odlišně:

| Typ | Charakteristika | Příklad |
|-----|----------------|---------|
| **Preference** | Trvalé, zřídka se mění | „Uživatel preferuje Tailwind před Bootstrapem" |
| **Epizodická** | Časová, záleží na pořadí | „3. března jsme ladili timeout připojení k Postgresu" |
| **Sémantická** | Aktualizovatelná, aktuální stav | „MedicMee používá Rails 7.1 s Postgresem" |
| **Cíle** | Dlouhodobé, sledování pokroku | „Vydat Hřiště Hrou ERP do konce 2. čtvrtletí" |

Dobrý paměťový systém by měl vyhledat všechny typy — ale benchmark prověří, zda je systémy rozlišují (např. poznají, že preference je stabilní, zatímco rozhodnutí bylo později revidováno).

---

## Výstupy (Realistické pro jeden den)

1. **Funkční integrace** — Alespoň jeden paměťový systém připojený ke Claude Code nebo OpenClaw.
2. **Evaluační rámec (harness)** — Znovupoužitelná testovací sada, kterou lze po hackathonu dále rozšiřovat.
3. **Srovnávací zjištění** — Zdokumentované silné stránky a omezení každého testovaného systému.
4. **5minutová prezentace** — Demo + klíčové poznatky pro skupinu.

### Jak vypadá úspěch

> „Rozumíme silným stránkám a omezením těchto systémů, integrovali jsme je do Claude Code nebo OpenClaw a máme evaluace, které lze znovu použít pro další práci."

---

## Kandidáti na paměťové systémy

> Pracovní verze — průzkum probíhá

Budeme hodnotit 2 open-source řešení, která se integrují přes MCP. Zvažované příklady:

| Systém | Přístup | Integrace | Proč ho zvážit |
|--------|---------|-----------|----------------|
| **Mem0** | Hybrid embeddingů a grafů | MCP server | Postaveno přímo pro agenty, aktivní komunita |
| **Zep** | Časově orientovaná, vnímá relace | MCP server | Silná v historii konverzací |
| **Letta (MemGPT)** | Samoeditační stupňovitá paměť | Nativní agent | Neotřelá architektura, zvládá dlouhý kontext |

Toto jsou příklady — finální výběr závisí na připravenosti pro MCP, náročnosti nastavení a zpětné vazbě týmu.

---

## Co budeme pravděpodobně muset postavit

Tyto systémy nejsou navrženy tak, aby samy o sobě zpracovaly historii relací Claude Code. Pravděpodobně budeme muset vytvořit datové loadery, které:

1. Zpracují exporty relací ve formátu JSONL.
2. Extrahují obsah hodný zapamatování (preference, rozhodnutí, vyřešené problémy).
3. Naformátují a nahrají data do API daného paměťového systému.

Toto je očekávaná součást práce, nikoliv překážka.

---

## Příprava

> Na jednodenním hackathonu není čas na ladění instalace. Vedoucí projektu připraví:

### Před akcí (Vedoucí projektu)

- [ ] Výběr paměťových systémů — finální výběr 2 kandidátů podle připravenosti MCP.
- [ ] Stažení a otestování Docker obrazů — oba systémy startují a odpovídají.
- [ ] Ověření MCP serverů — připojení ke Claude Code nebo OpenClaw jednoduchým testem.
- [ ] Příprava datové pipeline — skript pro převod JSONL relací do formátu pro import.
- [ ] Export ukázkových dat — podmnožina relací s anonymizovanými údaji.
- [ ] Vytvoření sdíleného repozitáře — README, skripty pro nastavení, složka s daty, šablona pro evaluace.
- [ ] Příprava pitche — 60sekundové představení pro nábor týmu.

### Účastníci by měli dorazit s

- [ ] *(TBD)*

---

## Týmové role

*(TBD)*

---

## Zdroje

*(TBD)*
