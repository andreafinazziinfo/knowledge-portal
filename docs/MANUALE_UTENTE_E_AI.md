# 📘 Manuale Operativo Knowledge Portal — Per Sviluppatori Umani e Agenti AI

> **Guida Integrata all'Uso, Navigazione Ergonomica e Protocollo Enterprise per Umani e Agenti AI (v3.0.0 Enterprise Edition)**

---

## 🎯 Panoramica e Filosofia di Design

Il **Knowledge Portal** è una piattaforma di intelligenza architetturale autonoma, progettata con un duplice obiettivo:
1. **Per lo Sviluppatore Umano**: Offrire un'esperienza di navigazione fluida, estetica e a zero attrito cognitivo. Permette di esplorare codebases complesse mediante grafi fisici interattivi (2D e 3D), documentazione markdown arricchita, schemi database relazionali e floorplan microserviziali.
2. **Per l'Agente AI (LLM / Copilot / Autonomous Coding Agent)**: Fornire una rappresentazione semantica strutturata, deterministica e ad alta densità informativa del sistema software. Questo elimina le allucinazioni, supera i limiti di context window e porta la comprensione del progetto a circa il **98%**.

---

# 👤 PARTE I: GUIDA PER LO SVILUPPATORE UMANO

## 1. Avvio Rapido & Modalità di Esecuzione

### A. Esecuzione con Docker (Consigliata per Team e CI/CD)
L'immagine Docker multi-architettura ufficiale è ospitata su GitHub Packages (GHCR), basata su Alpine Linux (< 50MB):

```bash
# Avvio istantaneo montando il repository locale
docker run -d --name knowledge-portal \
  -p 8000:8000 \
  -v $(pwd):/app/data \
  ghcr.io/andreafinazziinfo/knowledge-portal:latest
```

Il portale è immediatamente accessibile su `http://localhost:8000/dashboard.html`.

### B. Esecuzione Locale con CLI Python (Zero Dipendenze Esterne)
Non richiede framework pesanti: richiede esclusivamente **Python 3.10+ Standard Library**.

```bash
# 1. Scansione AST del codebase
python3 -m knowledge_portal.cli scan .

# 2. Compilazione del floorplan architetturale
python3 -m knowledge_portal.cli floorplan architecture.yaml

# 3. Avvio del server HTTP con live-reload SSE
python3 -m knowledge_portal.cli serve --port 8000
```

### C. Esportazione Statica per GitHub Pages o Consultazione Offline
Per generare un bundle statico 100% autonomo (eseguibile anche da file locale `file://` o pubblicato su GitHub Pages / Netlify):

```bash
python3 -m knowledge_portal.cli export . --output ./dist --name "My Project"
```

---

## 2. Navigazione & Ergonomia delle Viste

### 🧭 Vista 1: Grafo 2D AST (Vis.js Network)
- **Radar Minimap in Tempo Reale**: In basso a sinistra è sempre visibile una minimappa radar semi-trasparente. Mostra l'intera costellazione di nodi e traccia in tempo reale il rettangolo del viewport con il fattore di zoom corrente. È possibile cliccare su qualsiasi punto della minimap per saltare istantaneamente a quelle coordinate del grafo.
- **Isola Vicini (Ego-Network Filter)**: Cliccando su un nodo e premendo il pulsante `🎯 Isola Vicini`, il grafo nasconde temporaneamente tutti i nodi non correlati, mantenendo visibile esclusivamente la "community ego-centrica" (vicini a 1 hop e 2 hop). Questo elimina il disordine visivo nei codebases con migliaia di dipendenze.
- **Filtro per Livello e Community**: I pulsanti in alto permettono di filtrare per linguaggi (Python, TypeScript, SQL, Go, Rust, C++) o per cluster semantici modulari.
- **Ponte Diretto verso il Reader**: Cliccando su `📖 Apri nel Reader` nell'ispettore del nodo, il file sorgente o il modulo associato viene immediatamente caricato nella scheda del lettore markdown.

### 🌐 Vista 2: Grafo 3D WebGL (Three.js Force-Directed)
- **Nuovo HUD Analitico e Controlli**:
  - `🔴 Cicli`: Esegue l'algoritmo Depth-First Search (DFS) in tempo reale sul grafo tridimensionale. I nodi che formano dipendenze cicliche vengono evidenziati con luce rossa pulsante e ingranditi del 180%, mentre il resto del grafo viene attenuato.
  - `⚪ Orfani`: Identifica istantaneamente i nodi isolati privi di connessioni in ingresso o in uscita, evidenziandoli in arancione ambrato.
  - `↺ Reset Camera`: Riporta fluidamente la camera alla prospettiva panoramica ideale.
- **Camera Fly-To Fluid con Interpolazione Tween**: Cliccando su un nodo 3D, la camera si avvicina in volo morbido (Fly-To) posizionandosi all'angolo ottimale per ispezionare il nodo e le sue relazioni.
- **Card Ispettore Fluttuante**: Mostra identificativo univoco, percorso file, linea di codice sorgente, docstring e pulsanti rapidi per l'isolamento dei vicini 3D.

### 📖 Vista 3: Markdown Reader con Indice e Lightbox
- **📑 Indice dei Contenuti (TOC) Automatico**: Per documenti tecnici estesi con intestazioni `h1`, `h2`, `h3`, il portale genera automaticamente un indice sticky galleggiante sul lato destro. Ogni voce è cliccabile ed effettua uno scroll morbido verso la sezione corrispondente.
- **📋 Copia Rapida Snippet di Codice**: Ogni blocco di codice sorgente presenta in alto a destra un pulsante `Copia`. Con un click il frammento viene copiato negli appunti e il pulsante fornisce feedback immediato (`✓ Copiato!`).
- **🔍 Mermaid Modal Lightbox**: I diagrammi architetturali renderizzati con Mermaid possono essere ingranditi a schermo intero cliccando sull'icona o sul grafico. Si apre un lightbox vettoriale con controlli di zoom in/out e reset, richiudibile in qualsiasi momento premendo il tasto `ESC`.

### 🗄️ Vista 4: Database Lineage Explorer
- **Visualizzazione Tabellare e Relazionale**: Mappa tutte le tabelle del database, colonne, tipi di dato, chiavi primarie (PK) e vincoli di chiave esterna (FK).
- **📄 Generatore Istantaneo DDL SQL**: Cliccando su `📄 DDL SQL` su una qualsiasi tabella, il portale visualizza una finestra modale con la sintassi `CREATE TABLE` formattata, completa di colonne, vincoli di integrità e foreign keys. Include pulsante di copia negli appunti.
- **🔍 Generatore Automatico di Query JOIN**: Cliccando su `🔍 Query JOIN`, il sistema analizza i collegamenti foreign key della tabella selezionata e genera una query SQL `SELECT ... FROM table LEFT JOIN target ON ...` pronta per essere utilizzata nelle analisi di database.
- **📥 Esportazione Schema JSON**: Permette di scaricare con un click il file `db-schema.json` completo per l'integrazione con tool terzi o per la revisione offline.

### 🏗️ Vista 5: Architecture Floorplan (Mappa Microservizi)
- **🔍 Ricerca Microservizi in Tempo Reale**: In alto è presente una barra di ricerca reattiva (`🔍 Cerca microservizio...`). Digitando il nome, l'ID o le parole chiave della descrizione, i microservizi corrispondenti si illuminano con un contorno azzurro ciano, mentre i nodi non pertinenti vengono sfumati.
- **Filtro Interattivo a Pulsanti per Layer**: Ogni livello logico definito nel file `architecture.yaml` (es. Presentation, Gateway, Engine, Persistence) ha un pulsante dedicato. Cliccando su un livello è possibile nasconderlo o visualizzarlo selettivamente.
- **Badge di Stato del Ciclo di Vita**: Ogni servizio visualizza un badge cromatico che ne indica lo stato operativo:
  - `ACTIVE` (Verde smeraldo `#10b981`): Servizio in produzione pienamente operativo.
  - `DEV` (Ambra `#f59e0b`): Componente in corso di sviluppo.
  - `FROZEN` (Viola `#a855f7`): Componente congelato o versione LTS stabile.
  - `DEPRECATED` (Rosso `#f43f5e`): Servizio in dismissione.

### 🕸️ Vista 6: Unified Graph Studio (18 Modalità + `📷 Snapshot`)
- Riunisce in una singola barra veloce **18 visualizzazioni zero-CDN**: **Network** (*2D Graph, 3D Sphere, Particle Flow, Chord Matrix, Edge Bundling, Arc Diagram, Hive Plot*), **Arch** (*2D Canvas, 3D Z-Planes, CodeCity 3D, Sankey Flow*) e **Hierarchy** (*Tree, Treemap, Sunburst, Circle Pack, Icicle, Radial Tidy Tree, 3D Tree*).
- Supporta la persistenza del focus (`?focus=<nodeId>`) tra modalità e il pulsante **`📷 Snapshot`** per esportare in 1 click la vista attiva in `.svg` o `.png`.

### 🩺 Vista 7: Health & Audit Center 4.0+ (10 Tab · Deep Audit · Export & CI Gate — ADR-080)
- **Tab 1 (Overview & Fix Queue)**: Radar 6 assi, storico nel tempo e Top 12 ROI Fix Queue (`P0/P1/P2`).
- **Tab 2 (Architecture)**: Scatter Robert C. Martin (`I` vs `A`), Domain DSM Heatmap, Cicli Tarjan SCC e God-Files.
- **Tab 3 (Complexity, Git & Ownership)**: Hotspot Bubble Map, Parallel Coordinates, **CodeScene Risk Matrix**, Bus Factor e **Ownership & Conway's Law Map** (`CODEOWNERS` + 180g Git).
- **Tab 4 (Tests & Coverage)**: **Per-Domain Test-to-Code Ratio** (D3 bar chart), **Test Smells Audit** (`ASSERT_LESS_TEST`, `SKIPPED_TEST`, `SLEEP_IN_TEST`) e auto-ingestion `coverage.xml`/`lcov.info`.
- **Tab 5 (Security, SRE, API & DB)**: **Severity Breakdown Stacked Bar** + **OWASP Quick-Audit**, **Reliability AST**, **API Auth/Model Governance**, **DB N+1, Unbounded SELECT & TimescaleDB Hypertables/CAGGs**, **Observability Probes**, **Supply Chain (`pyproject.toml` + lockfile)**.
- **Tab 6 (AI Readiness & Orphans)**: Docstring/Type-Hint %, **AI Context Bombs (`>800 LOC`)** e drift `llms.txt`.
- **Tab 7 (Architecture Diff & Evolution)**: Diff tra snapshot + **selettore Git-Ref (`base..HEAD`)** con **Living Doc-Drift Detector**.
- **Tab 8 (IaC, Config & Compliance)**: Topologia Docker/Compose/Terraform/CI, matrice `.env` drift e evidenze di conformità.
- **Tab 9 (`🐛 Runtime Bugs & CI/CVE`)**: **Runtime Bugs v2** Python (`ASYNC_BLOCKING_IO`, `UNCLOSED_RESOURCE`, `LATE_BINDING_CLOSURE`, `SWALLOWED_EXCEPTION`) + Vue/TS (`VUE_VFOR_NO_KEY`, `JS_LEAKED_LISTENER_OR_TIMER`, `TS_FLOATING_PROMISE`), audit CI/CD & Compose e **CVE JSON Ingestion** (`pip-audit`, `npm-audit`, `osv-scanner`, `trivy`) correlata al CycloneDX 1.5 SBOM.
- **Tab 10 (`🧬 Deep Audit: Dead Code, Migrations, FE & Telemetry`)**: **Symbol-Level Dead Code** (`Python`, `JS/TS`, `Vue`), **Migration Safety & SRE Resilience** (`SQL_INDEX_WITHOUT_CONCURRENTLY`, `SQL_LOCK_TIMEOUT_MISSING`, `SRE_FSTRING_LOGGING`), **Frontend Hygiene & Static a11y** (Pinia/Vuex God-Stores, `A11Y_*`), **Quality Telemetry** (JUnit, Coverage, Ruff, Mypy, TSC) e **AST Semantic Clones** (rilevamento funzioni strutturalmente duplicate via fingerprint AST normalizzato).
- **Export & CI Gate**: Pulsanti `🖨️ Print / PDF`, `⬇ Markdown`, `⬇ SARIF 2.1` + CLI `knowledge-portal report --format md|sarif` e `knowledge-portal gate --min-score 75 --max-cycles 0 --max-critical 0`.

### ⚡ Vista 8: End-to-End Sequence Tracer & 💥 What-If Impact Simulator
- **Sequence Tracer (`views/sequence-tracer.html`)**: visualizza le catene di chiamata reali estratte via AST (`Route → Handler → Service Callees → DB Tables`) con diagramma sequenziale D3 cliccabile verso il Reader.
- **Impact Simulator (`views/impact-simulator.html`)**: digita qualsiasi file o simbolo per accendere i cerchi concentrici **`d=1` / `d=2` / `d=3`**, il badge di rischio e il comando `pytest` mirato da eseguire prima del commit.

### 🔌 Vista 9: Live API Catalog & CycloneDX 1.5 SBOM + Ergonomia Enterprise
- **Live API Explorer (`views/api-catalog.html`)**: estrazione polyglot automatica (FastAPI, Flask, Express, Go, OpenAPI 3.1) con filtri metodo/tag, auth badge e download `openapi.json`.
- **SBOM & Licenze (`views/stack-ecosystem.html`)**: inventario licenze (`Permissive`/`Copyleft`) e download 1-click **CycloneDX 1.5** (`data/sbom.cdx.json`).
- **UX Enterprise**: Command Palette universale **`Ctrl+K`** (viste + doc + endpoint API con frecce `↑/↓/Enter`), **Guided Onboarding Paths** nella Home, **Deep-Linking** (`?tab=reader&file=...`, `?tab=impact-simulator&target=...`) e toggle tema **`🌙 Dark / ☀️ Light`**.

### 🎛️ Vista 10: Control Hub OSS (4 Viste Air-Gapped — ADR-081)
- **Mission Control (`views/mission-control.html`)**: Cruscotto operativo unificato con KPI architetturali/Git/governance, radar anomalie `P0/P1/P2` e jump rapidi ai sottosistemi.
- **Git & PR DAG (`views/git-pr-dag.html`)**: Matrice completa dei Git worktree (`clean`, `dirty`, `stale`, `detached`, `locked`), igiene branch locali, workflow CI e grafi PR.
- **ADR & Runbook Hub (`views/adr-runbook-hub.html`)**: Grafo delle Architecture Decision Records (`Accepted`/`Proposed`/`Superseded`) e catalogo runbook operativi cliccabile verso il Reader.
- **AI Mission Launcher (`views/ai-mission-launcher.html`)**: Generatore interattivo di missioni AI con selezione scope, context-pack mirati e prompt pronti per agenti autonomi.

### ⚡ Vista 11: Cross-Stack Intelligence, Test Oracle & Data Contracts (ADR-082 — 40 Viste HTML Totali)
- **Vertical Slices (`views/vertical-slices.html`)**: traccia in end-to-end i collegamenti `UI Component / Store → REST API → Backend Handler → Worker → Database Table` con archi `FE_CALLS_API`.
- **Test-to-Code Reverse Oracle (`views/test-oracle.html`)**: mappa inversa `modulo/simbolo → test diretti veloci` e rilevamento automatico dei blind spot ad alto rischio privi di copertura.
- **Data Contracts & Runtime Modes (`views/data-contracts.html`)**: registro di schema drift Pydantic↔TypeScript, Error Taxonomy, matrice lettori/scrittori DB e matrice dei runtime mode (`offline/dev/paper/shadow/live`).
- **Viste Data-Driven 0-CDN Convertite**: `views/async-topology.html` (task Celery/Beat, chiavi Redis, Pub/Sub, WS/SSE), `views/worker-tasks.html`, `views/frontend-state.html` e `views/data-ingestion.html` — per un totale di **40 viste HTML interattive** in `template/views/`, 100% air-gapped senza CDN.

---

# 🤖 PARTE II: PROTOCOLLO OPERATIVO PER AGENTI AI

## 1. Perché il Portale è Essenziale per l'Agente AI

Nei progetti di grandi dimensioni, un agente AI incontra tre ostacoli fondamentali:
1. **Esaurimento del Context Window**: Non è possibile inserire centinaia di migliaia di righe di codice nel prompt.
2. **Perdita di Coerenza Architetturale**: L'AI può proporre modifiche sintatticamente corrette ma che violano la separazione a livelli (es. chiamare direttamente la persistenza dal presentation layer).
3. **Disconnessione tra Endpoint e Database**: Senza un tracciato esplicito, capire quali tabelle del database sono impattate da una rotta API richiede decine di grep ricorsivi.

Il Knowledge Portal pre-elabora deterministicamente l'intero grafo architetturale salvandolo in formati JSON compatti e standardizzati. L'agente AI può interrogare questi artefatti ottenendo risposte esatte in tempo $O(1)$.

---

## 2. Il Repository dei Dati Semantici (`/data`)

Tutti i file descrittivi risiedono nella cartella `data/` del portale:

| File | Scopo per l'AI Agent | Struttura Principale |
| :--- | :--- | :--- |
| `data/process-flows.json` | **Flussi di Processo End-to-End**: collega entrypoint API/CLI, call chain di funzioni interne e tabelle database coinvolte. | `flows`: `[{ id, name, category, route, method, entrypoint, call_chain, tables_accessed }]` |
| `data/db-schema.json` | **Catalogo Relazionale SQL**: definizioni esatte di tabelle, colonne, PK, FK e mapping relazionali. | `tables`: `[{ name, columns: [{ name, type, pk, nullable }], foreign_keys: [...] }]` |
| `data/graph.json` | **Grafo AST Polyglot**: tutti i simboli (classi, metodi, store, interfacce) e le dipendenze d'importazione. | `nodes`: `[{ id, label, type, lang, path, line, doc }]`, `edges`: `[{ source, target, type }]` |
| `views/data/omni-search-index.json` | **Indice Invertito di Ricerca**: permette il lookup istantaneo per parole chiave, concetti e documentazione. | `docs`: `[{ id, title, path, content, tags }]` |
| `data/views-manifest.json` | **Manifest delle Viste**: elenco delle viste e funzionalità attive nel portale. | `available_views`: `["home", "reader", "graph-studio", "arch-health", ...]` |
| `data/arch-health.json` | **Health Engine 4.0 (16 pilastri)**: score, radar, cicli, OWASP, SRE, DB N+1, API auth, CodeScene Risk, ROI Fix Queue. | `summary`, `radar`, `health_v4`, `fix_queue` |
| `data/call-graph.json` | **Symbol-Level Call Graph**: `caller → callee`, firme tipizzate, eccezioni, tabelle DB e catene `Route → DB`. | `summary`, `chains`, `symbols` |
| `data/api-catalog.json` | **Live API & OpenAPI 3.1**: tutti gli endpoint HTTP/WS con auth, handler `file:line` e `response_model`. | `summary`, `tags`, `endpoints`, `openapi` |
| `data/ownership.json` | **Ownership & Conway Map**: regole `CODEOWNERS`, Bus Factor e contributori 180g per dominio. | `codeowners_file`, `domains` |
| `data/sbom.cdx.json` | **CycloneDX 1.5 SBOM**: componenti software, PURL, classificazione licenze e `vulnerabilities[]`. | `bomFormat`, `specVersion`, `components`, `vulnerabilities` |
| `data/cve-report.json` | **CVE Ingestion (ADR-080)**: vulnerabilità da `pip-audit`, `npm-audit`, `osv-scanner`, `trivy` correlate all'SBOM. | `available`, `sources`, `summary`, `vulnerabilities` |
| `data/dead-code.json` | **Symbol-Level Dead Code (ADR-080)**: funzioni Python non chiamate, export JS/TS inutilizzati, componenti Vue orfani. | `summary`, `python_dead_symbols`, `js_unused_exports`, `vue_unused_components` |
| `data/quality-telemetry.json` | **Quality Telemetry (ADR-080)**: aggregatore locale Coverage, JUnit XML, Ruff, Mypy e TSC. | `summary`, `coverage`, `junit`, `ruff`, `typecheck` |
| `data/mission-control.json` | **Mission Control (ADR-081)**: KPI esecutivi, stato sottosistemi e lista anomalie prioritizzate. | `kpis`, `subsystems`, `anomalies`, `quick_jumps` |
| `data/git-dag.json` | **Git & PR DAG (ADR-081)**: inventario worktree, branch locali/stale/merged, PR e workflow CI. | `summary`, `worktrees`, `branches`, `prs`, `workflows` |
| `data/adr-graph.json` | **ADR & Runbook Graph (ADR-081)**: grafo decisioni architetturali, stati e runbook operativi. | `summary`, `adrs`, `edges`, `runbooks` |
| `data/module-cards.json` | **Compact Module Cards (ADR-082)**: schede compatte `≤180` token/file per slicing AI ad alta efficienza. | `cards`, `summary` |
| `data/test-oracle.json` | **Test-to-Code Reverse Oracle (ADR-082)**: mappa inversa file/simboli → test veloci e blind spot. | `summary`, `file_to_tests`, `blind_spots` |
| `data/agent-instructions-audit.json` | **Agent Instructions Audit (ADR-082)**: verifica token bloat e path morti in `CLAUDE.md`/`AGENTS.md`. | `summary`, `files`, `dead_paths`, `hygiene_score` |
| `data/sarif-findings.json` | **Universal SARIF 2.1.0 (ADR-082)**: findings normalizzati da CodeQL, Semgrep, Trivy, Ruff, Bandit. | `summary`, `runs`, `findings` |
| `data/vertical-slices.json` | **Cross-Stack Vertical Slices (ADR-082)**: slice 6-layer `UI → Store → API → Backend → Task → DB`. | `summary`, `slices`, `fe_calls_api` |
| `data/async-topology.json` | **Async Topology (ADR-082)**: worker task, Beat schedule, chiavi/lock Redis, Pub/Sub, WS/SSE. | `summary`, `tasks`, `schedules`, `channels` |
| `data/data-contracts.json` | **Data Contracts & Drift (ADR-082)**: schema drift Pydantic↔TS, Error Taxonomy e DB readers/writers. | `summary`, `schema_drift`, `error_taxonomy`, `db_rw` |
| `data/runtime-modes.json` | **Runtime Modes Matrix (ADR-082)**: matrice modalità operative, servizi richiesti e feature flags. | `modes`, `guards`, `feature_flags` |

### 🔌 Protocollo MCP v3 (37 Tool OSS · 22 Risorse `portal://` · Token-Budget Engine), Code Mode & CLI AI-Native
- **Server MCP Standard (`knowledge-portal mcp`)**: espone **37 tool OSS read-only** (35 standard + 2 tool Code Mode `portal_discover` e `portal_codemode`), governati dal **Token-Budget Engine (`-98,7%` payload, default `detail="summary"`)**, inclusi i tool ADR-081/082 (`portal_slice_for_task`, `portal_check_diff`, `portal_agent_instructions_audit`, `portal_handoff_pack`, `portal_test_oracle`, `portal_sarif_findings`, `portal_vertical_slice`, `portal_async_topology`, `portal_contract`, `portal_mission_control`, `portal_git_dag`, `portal_adr_graph`, `portal_deep_audit`, `portal_dead_code`, `portal_cve_report`, `portal_config_matrix`, `portal_iac_topology`, `portal_ai_registry`, `portal_compliance`, `portal_mission_pack`, `portal_call_chain`, `portal_validate_change`, `portal_pr_context`, `portal_api_catalog`, `portal_arch_diff`, `portal_health_audit`, `portal_impact`), **22 risorse `portal://`** (`portal://llms.txt`, `portal://health`, `portal://api-catalog`, `portal://arch-diff`, `portal://sbom`, `portal://invariants`, `portal://ownership`, `portal://compliance`, `portal://cve-report`, `portal://dead-code`, `portal://quality-telemetry`, `portal://git-dag`, `portal://adr-graph`, `portal://mission-control`, `portal://module-cards`, `portal://test-oracle`, `portal://agent-instructions-audit`, `portal://sarif-findings`, `portal://vertical-slices`, `portal://async-topology`, `portal://data-contracts`, `portal://runtime-modes`) e **prompt guidati** (`audit_pr_impact`, `onboard_module`).
- **Cloudflare-Style Code Mode (`knowledge-portal mcp --code-mode`)**: riduce lo schema MCP a 2 soli tool (`portal_discover` + `portal_codemode`) con interprete AST Python strettamente read-only per pipeline multi-step in un singolo round-trip.
- **Ricerca Ibrida & PR Bot**: `GET /api/search?q=...&expand=1` espande i risultati FTS5 BM25 con i vicini 1-hop del grafo; `knowledge-portal pr-comment --base main` genera un commento PR con **Doc-Drift** e test impattati.

---

## 3. Pattern di Interrogazione per l'Agente AI

### Scenario A: Determinare l'impatto di un endpoint API
Quando l'utente chiede: *"Cosa succede quando chiamo `POST /auth/login` o un endpoint ordini?"*

L'agente AI legge direttamente `data/process-flows.json`:
```python
import json
from pathlib import Path

flows = json.loads(Path("data/process-flows.json").read_text())["flows"]
target_flow = next((f for f in flows if f.get("route") == "/auth/login" or f.get("name") == "POST /auth/login"), None)

if target_flow:
    print(f"Entrypoint: {target_flow['entrypoint']['file']}:{target_flow['entrypoint']['line']}")
    print(f"Funzioni richiamate: {target_flow['call_chain']}")
    print(f"Tabelle database impattate: {target_flow['tables_accessed']}")
```
**Risultato per l'AI**: Risposta immediata, senza allucinazioni, con riferimento al file sorgente e alla riga esatta.

### Scenario B: Generare una migrazione o query SQL valida
Quando l'utente chiede: *"Crea una query per estrarre tutti gli ordini con il profilo utente"*

L'agente AI legge `data/db-schema.json`:
```python
schema = json.loads(Path("data/db-schema.json").read_text())
tables = {t["name"]: t for t in schema["tables"]}

# Trova la relazione FK tra orders e users
orders_tbl = tables.get("orders")
for fk in orders_tbl.get("foreign_keys", []):
    if fk["target_table"] == "users":
        print(f"JOIN corretto su: orders.{fk['column']} = users.id")
```
**Risultato per l'AI**: Zero nomi di colonna inventati; rispetto garantito dei tipi di dato e dei vincoli relazionali.

### Scenario C: Identificare le dipendenze upstream di un file prima del refactoring
Quando l'utente chiede: *"Voglio rifattorizzare `polyglot.py`, chi lo importa?"*

L'agente AI esegue una query su `data/graph.json`:
```python
graph = json.loads(Path("data/graph.json").read_text())
dependents = [e["source"] for e in graph["edges"] if "polyglot" in e["target"]]
print(f"Moduli dipendenti che richiedono aggiornamento: {dependents}")
```

---

## 4. Prompt Template Consigliato per Inizializzare un Agente AI

Quando si avvia una sessione di lavoro con un assistente AI sul progetto, è consigliabile fornire questo contesto iniziale:

```markdown
Sei connesso al repository tramite il suo Knowledge Portal.
Prima di ipotizzare l'architettura o inventare collegamenti:
1. Consulta `data/process-flows.json` per mappare i flussi di esecuzione (entrypoint -> call chain -> tabelle database).
2. Consulta `data/db-schema.json` per conoscere i nomi reali delle tabelle, colonne e relazioni FK.
3. Consulta `data/graph.json` per conoscere le classi e funzioni esistenti e le loro dipendenze.
4. Quando modifichi file markdown o codice sorgente, rispetta i livelli architetturali descritti in `architecture.yaml`.
```

---

## 5. Matrice di Sicurezza & Conformità OPSEC

Il Knowledge Portal include un gate di verifica continuo:
- **Zero Proprietary Data**: Eseguire regolarmente `python3 verify_sanitization.py .` prima di qualsiasi commit pubblico o push su repository aperti.
- **Air-Gapped Compliance**: Tutti gli asset (icone, font, librerie JS per grafi 3D e 2D, motori KaTeX) sono ospitati localmente nella cartella `template/vendor/` e `template/assets/`. Nessuna chiamata di rete esterna o CDN è permessa.
- **Zero Telemetria**: Nessun dato d'uso, IP o codice sorgente viene mai inviato verso server esterni.
- **Hardening Produzione**: Il server supporta `PORTAL_READ_ONLY=1` (blocco `403` sulle mutazioni), `PORTAL_API_TOKEN` (`X-Portal-Token` / `Authorization: Bearer`), path confinement rigoroso (`safe_resolve_under`) e security header HTTP (`nosniff`, `SAMEORIGIN`, `no-referrer`).

---

## 6. Design System Unificato, Telemetria Live & Scorciatoie

- **Design System Floorplan Carbon-Black**: Tutte le viste condividono canvas `#0f0f0f` con griglia a pallini, card `#191919` con bordo bianco su `:hover`, header trasparenti sfumati e controlli monocromatici.
- **Ergonomia da Tastiera (`portal-ui.js`)**: Premere `/` per focalizzare istantaneamente il campo di ricerca della vista attiva; premere `Esc` per svuotare il filtro o chiudere drawer/modali.
- **Vista `Live Telemetry & Auto-Sync`**: Interroga `/api/telemetry` per visualizzare CPU, RAM, Disco, avanzamento rebuild e stato watcher/servizi, degradando a `Static Snapshot` in modalità offline.
- **Comandi CLI (11 Subcomandi) & Server MCP Nativo (`stdio` JSON-RPC 2.0)**:
  - Subcomandi disponibili: `scan`, `export`, `serve`, `floorplan`, `audit`, `mcp`, `status`, `query`, `report`, `gate`, `pr-comment`.
  - `knowledge-portal status --json`: stato live `/api/telemetry` o snapshot statico.
  - `knowledge-portal query "<term>" --type search|flow|schema|stack`: query diretta sui JSON del portale.
  - `knowledge-portal mcp --dir . --url http://127.0.0.1:8000`: espone i **37 tool MCP OSS read-only** e le **22 risorse `portal://`** (oppure 2 tool con `--code-mode`) configurabili in qualsiasi client MCP:
    ```json
    {
      "mcpServers": {
        "knowledge-portal": {
          "command": "knowledge-portal",
          "args": ["mcp", "--dir", ".", "--url", "http://127.0.0.1:8000"]
        }
      }
    }
    ```

---

## ADR-069 / 070 / 071 / 072 / 073 — Graph Studio (18 Modalità), Health & Audit Center (8 Pilastri), AI Intelligence & Code Mode MCP

- **Graph Studio (`views/graph-studio.html`)**: unica vista unificata zero-dipendenze (60 FPS) con **18 modalità**:
  - *Network*: `2D Graph`, `3D Sphere`, `Particle Flow`, `Chord Matrix`, `Edge Bundling`, `Arc Diagram`, `Hive Plot`
  - *Arch*: `2D Canvas`, `3D Z-Planes`, `CodeCity 3D`, `Sankey Flow`
  - *Hierarchy*: `Tree` (Orizzontale/Verticale), `Treemap`, `Sunburst` (zoom 20x), `Circle Pack`, `Icicle / Flamegraph`, `3D Tree`
- **Pagina Dedicata `Health & Audit` (`views/arch-health.html`)**: 6 tab diagnostici su 8 pilastri (Radar 6 assi, Martin Main Sequence Scatter, DSM Heatmap, Cicli Tarjan SCC, Complessità McCabe/Cognitiva/MI, Parallel Coordinates, Git Hotspots & Temporal Coupling 90gg, Coverage `coverage.xml`/`lcov.info`, Perf/SQL/DB, AI Readiness, Trend Storico e Top 10 Fix Queue cliccabile).
- **Sidebar Full-Project (`📚 Docs | 💻 Source Code`)**: `/api/tree?scope=docs|code` con P4 Gate (`frozen/`, `.git/`, `.claude/`, `.env*` esclusi) + click-to-Reader diretto dalle viste.
- **Strip Visuali sulle Viste Dedicate (`portal-ui.js`)**: `ADR Timeline`, `24h Worker Gantt`, `Bipartite Store ↔ View Flow` e overlay universale `? Guida & AI` (`Copia AI Context`, `/llms.txt`, `Blast Radius` inline).
- **Nuovi endpoint AI read-only**:
  - `/api/context-pack?q=<topic>&max_tokens=4000`
  - `/api/impact?target=<symbol_or_file>&depth=3` (resolver file-level)
  - `/api/health-audit` (`data/arch-health.json`)
  - `/llms.txt` e `/llms-full.txt`
- **Cloudflare-Style Code Mode MCP**:
  - Avvio compatto (2 tool, ~1k token di schema): `knowledge-portal mcp --dir . --code-mode`
  - Espone `portal_discover` e `portal_codemode` (interprete AST Python read-only senza `eval`/`exec`, senza `import` e senza I/O).

---

## ADR-082 — Token-Budget Engine (`-98,7%`), Cross-Stack Intelligence & Viste 0-CDN

- **Token-Budget Engine (`-98,7%`)**: i tool MCP più pesanti restituiscono di default payload compatti (`detail="summary"`, `≤800` token) affiancati da `data/module-cards.json` (`/api/module-cards`, `≤180` tok/file), `portal_slice_for_task` (budget configurabile) e `portal_check_diff` per verificare l'impatto dei diff Git.
- **Test-to-Code Reverse Oracle (`views/test-oracle.html`, `/api/test-oracle`)**: mappa inversa `modulo/simbolo → test diretti veloci` e rilevamento automatico dei blind spot ad alto rischio (`portal_test_oracle`).
- **Agent Instructions Audit (`/api/agent-instructions-audit`)**: analizza file di istruzioni, regole e skill per agenti AI rilevando peso in token, path morti e hygiene score.
- **Universal SARIF 2.1.0 & CodeQL (`/api/sarif-findings`, `.github/workflows/codeql.yml`)**: ingestione unificata di report SARIF 2.1.0 (CodeQL, Semgrep, Trivy, Ruff, Bandit) nella dashboard di salute e sicurezza.
- **Vertical Slices Cross-Stack (`views/vertical-slices.html`, `/api/vertical-slices`)**: collega componenti UI e store frontend agli endpoint API, handler backend e tabelle DB (`portal_vertical_slice`).
- **Async Topology (`views/async-topology.html`, `/api/async-topology`)**: mappa worker task, job schedulati, chiavi/lock Redis, canali Pub/Sub, WebSocket e stream SSE (`portal_async_topology`).
- **Data Contracts & Runtime Modes (`views/data-contracts.html`, `/api/data-contracts`, `/api/runtime-modes`)**: rileva schema drift Pydantic↔TypeScript, rotte API non tipizzate, tassonomia errori, lettori/scrittori DB e matrice dei runtime mode (`portal_contract`).
- **6+ Viste Nuove/Convertite Data-Driven 0-CDN**: `vertical-slices.html`, `test-oracle.html`, `data-contracts.html`, `async-topology.html`, `worker-tasks.html`, `frontend-state.html` e `data-ingestion.html` — 100% air-gapped senza alcuna richiesta CDN esterna.
- **Server MCP Esteso**: **37 tool OSS** nativi e **22 risorse `portal://`** (estensibili a **43 tool** con plugin domain-hub opzionali), tutti read-only e governati dal Token-Budget Engine.
- **CI/CD & Sicurezza (3 Workflow GitHub Actions)**: `.github/workflows/ci.yml` (`CI Suite`: Ruff, Mypy, Bandit, `verify_sanitization.py`, Pytest, Playwright E2E), `.github/workflows/docker.yml` (`Docker Publish GHCR`) e `.github/workflows/codeql.yml` (`CodeQL Security Analysis`).

---

## ADR-083 — Parallel DAG Rebuild, True Air-Gap, Guardrail Attivi & Visuali SVG 0-CDN

- **Parallel DAG Rebuild & Incremental File-Hash Cache**: orchestratore parallelo a 3 onde (`knowledge_portal/orchestrator.py`) con cache incrementale per hash file (`.portal-cache.json`) — warm rebuild **`< 1s`** (**speedup 72×–118×**) e snapshot automatico `graph-prev.json`.
- **Freshness SLA & Omni-Search FTS5 Server-Side**: ogni artefatto JSON include l'envelope `_meta.git_head_sha` verificato tramite `/api/live-status` e `/api/meta/head`, con badge live **`FRESH` / `STALE`** in `portal-ui.js` e ricerca Omni-Search FTS5 lato server su `dashboard.html`.
- **100% True Air-Gap (0 CDN Ovunque)**: zero riferimenti CDN esterni in `dashboard.html`, CSS e tutte le 40 viste HTML, garantiti dal test bloccante `tests/unit/test_adr083_sprint2_airgap.py`.
- **Copertura Estesa & Guardrail Attivi**:
  - Nuovi parser per **Nginx** (`location` e security headers), **Shell Scripts** (`*.sh`), **Mobile Manifest** (`AndroidManifest.xml` / `build.gradle`) e **Protobuf** (`*.proto` wire contracts interrogabili con `portal_contract(kind="proto")`).
  - **Declarative `.arch-rules.json` Fitness Gate**: regole architetturali dichiarative bloccanti in `knowledge-portal gate` (`--rules`).
  - **CodeScene Risk & Hidden Coupling**: scoring `codescene_risk` e rilevamento **`hidden_temporal_coupling`** integrati nell'Health Engine e in Mission Control.
- **Visuali SVG Interattive 0-CDN (`PortalSVGViewport`)**: motore SVG condiviso in `portal-ui.js` (wheel-zoom, drag-pan, Fit, Export SVG) a supporto di 5 nuovi grafici 0-CDN — **`Schema Diff Sankey`** (`data-contracts.html`), **`Coverage Treemap`** (`test-oracle.html`), **`24h Beat Gantt`** (`worker-tasks.html`), **`Bipartite Store↔Component`** (`frontend-state.html`) e **`Inline Sparklines`** (`mission-control.html`).

---

*Knowledge Portal v3.0.0 Enterprise Edition — 40 Viste Air-Gapped · 37 Tool MCP OSS · 22 Risorse `portal://` — Realizzato per massimizzare la sinergia tra intelligenza umana e intelligenza artificiale.*
