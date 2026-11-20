# 📘 Manuale Operativo Knowledge Portal — Per Sviluppatori Umani e Agenti AI

> **Guida Integrata all'Uso, Navigazione Ergonomica e Protocollo di Comprensione AST Polyglot (v2.4.0 Peak Excellence Edition)**

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
| `data/views-manifest.json` | **Manifest delle Viste**: elenco delle viste e funzionalità attive nel portale. | `available_views`: `["home", "reader", "graph", "db-lineage", "floorplan"]` |

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
- **Comandi CLI & Server MCP Nativo (`stdio` JSON-RPC 2.0)**:
  - `knowledge-portal status --json`: stato live `/api/telemetry` o snapshot statico.
  - `knowledge-portal query "<term>" --type search|flow|schema|stack`: query diretta sui JSON del portale.
  - `knowledge-portal mcp --dir . --url http://127.0.0.1:8000`: espone i 6 tool MCP read-only (`portal_search`, `portal_process_flow`, `portal_db_schema`, `portal_stack`, `portal_telemetry`, `portal_read_doc`) configurabili in qualsiasi client MCP:
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

*Knowledge Portal v2.7 — Floorplan Carbon-Black & Production Hardened Edition — Realizzato per massimizzare la sinergia tra intelligenza umana e intelligenza artificiale.*
